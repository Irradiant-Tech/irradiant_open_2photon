from typing import List, Tuple, Union

import numpy as np
import torch

from hardware.voltage_device.voltage_devices import AnalogDevice
from print_preprocessing.aom_voltage import get_AOM_voltage
from print_preprocessing.matrix_processing import (
    matrix_3D_to_vector_list_and_filter,
    pad_matrix_width,
)
from utils.dtypes import ProcessingDataTypes


def generate_signals_all_frames(
    matrix: Union[torch.Tensor, np.ndarray],
    samplesBetweenLines: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate AOM voltage signals and original z-indices for non-blank frames.

    Returns:
        LineSignals: 2D float (num_nonzero_frames, num_points), AOM voltage per frame.
        z_indices:   1D int  (num_nonzero_frames,), original z-axis index of each
                     non-blank frame in matrix-order. Caller multiplies by z-step
                     to get per-frame stage targets and uses the indices to log
                     blank-frame skips.
    """
    # Convert input matrix to tensor
    if not isinstance(matrix, torch.Tensor):
        matrix = torch.from_numpy(matrix)
        print("Converted matrix to tensor")

    # Convert matrix to correct dtype
    if matrix.dtype != ProcessingDataTypes.torch_dtype:
        matrix = matrix.to(ProcessingDataTypes.torch_dtype)
        print(f"Converted matrix to {ProcessingDataTypes.torch_dtype}")

    try:
        # Convert matrix to voltage (in-place) and pad for blanking
        get_AOM_voltage(matrix)
        Padded_matrix = pad_matrix_width(matrix, samplesBetweenLines)
        del matrix  # Free memory
        torch.cuda.empty_cache()

        # Create flattened line signals and filter, keeping original z-indices
        LineSignals_tensor, z_indices_tensor = matrix_3D_to_vector_list_and_filter(
            Padded_matrix
        )
        del Padded_matrix  # Free memory
        torch.cuda.empty_cache()

        num_nonzero_frames = LineSignals_tensor.shape[0]

        # Move tensors to CPU and convert to numpy arrays
        LineSignals = LineSignals_tensor.cpu().numpy()
        del LineSignals_tensor
        z_indices = z_indices_tensor.cpu().numpy()
        del z_indices_tensor

        if num_nonzero_frames:
            print(
                f"LineSignals max: {np.max(LineSignals)}, min: {np.min(LineSignals)}, dtype: {LineSignals.dtype}; "
                f"num_nonzero_frames: {num_nonzero_frames}, original z range: [{int(z_indices[0])}..{int(z_indices[-1])}]"
            )
        else:
            print("WARNING: Print file is empty, nothing will be printed.")

        return LineSignals, z_indices
    except Exception as e:
        raise e


def filter_signals_by_reference(
    reference_signal: np.ndarray,
    other_signals: List[np.ndarray],
    samps_per_line: int,
    verbose: bool = True,
) -> Tuple[np.ndarray, List[np.ndarray]]:
    """
    Filter multiple signals based on on/off activity in a reference signal.

    Args: reference_signal: The signal used to determine which lines to keep (e.g. AOM signal).
          other_signals: list of other signals to filter in the same way.
          samps_per_line: Number of samples per line.
          verbose: If True, prints information about filtering. Default is True.

    Output: Tuple of (filtered_reference, filtered_other_signals)
            where filtered_reference is the filtered reference signal (1D array),
            and filtered_other_signals is a list of filtered signals, same order as input.
    """
    num_lines = len(reference_signal) // samps_per_line

    # Reshape and create mask from reference signal
    ref_reshaped = reference_signal[: num_lines * samps_per_line].reshape(
        num_lines, samps_per_line
    )

    # Create mask: True for lines that have any non-zero values
    line_mask = ref_reshaped.any(axis=1)

    # Filter reference signal
    filtered_reference = ref_reshaped[line_mask].flatten()

    # Filter other signals
    filtered_other_signals = []
    for sig in other_signals:
        sig_reshaped = sig[: num_lines * samps_per_line].reshape(
            num_lines, samps_per_line
        )
        filtered_other_signals.append(sig_reshaped[line_mask].flatten())

    if verbose:
        print(
            f"   num_samples: {len(reference_signal)}, filtered_num_samples: {len(filtered_reference)}"
        )

    return filtered_reference, filtered_other_signals


def compute_custom_rate_raster_params(
    voltage_device: AnalogDevice,
    xraster_custom_rate_hz: float,
    time_per_pixel: float,
    print_height_px: int,
    scan_size: int,
    samples_between_lines: int,
) -> tuple[float, int]:
    """
    Compute raster parameters for running at a custom output rate while staying
    within device memory and sample output rate limits.

    Args:
        voltage_device: Analog output device. Used to get the max sample clock and max total samples allowed in a buffer
        time_per_pixel: Dwell time per pixel in seconds.
        print_height_px: Number of x-raster lines (image height in pixels).
        scan_size: Number of samples in one line for the x-raster
        samples_between_lines: Number of samples in the blanking period.

    Returns:
        sample_rate_hz: device output rate (Hz)
        samples_per_value: oversampling factor
    """
    max_sample_rate_hz, max_samples_per_channel = (
        voltage_device.get_hardware_constraints()
    )

    def _memory_limited_sample_rate_hz() -> float:
        """Returns the maximum sample rate that still fits in device memory."""
        buffer_len_per_channel = (scan_size + samples_between_lines) * print_height_px

        # Max oversampling allowed by memory
        max_samples_per_value = max(1, max_samples_per_channel / buffer_len_per_channel)

        # Convert oversampling limit into a sample rate limit based on the time per pixel
        return max_samples_per_value / time_per_pixel

    # Clamp requested rate to what the device is able to output
    sample_rate_hz = min(
        xraster_custom_rate_hz,  # Requested rate
        _memory_limited_sample_rate_hz(),  # Rate limited by device memory
        max_sample_rate_hz,  # Rate limited by device max sample clock
    )

    # Oversampling factor at output rate to maintain the set time per pixel
    samples_per_value = max(1, round(sample_rate_hz * time_per_pixel))

    print(
        f"Using output rate {sample_rate_hz*10**-6:.1f} MHz, with oversampling factor of {samples_per_value}x."
    )
    if sample_rate_hz < xraster_custom_rate_hz:
        print(
            f"  Requested custom output rate of {xraster_custom_rate_hz*10**-6:.1f} MHz exceeded device limits."
        )

    return sample_rate_hz, samples_per_value
