from typing import List, Tuple

import numpy as np
import torch

from print_preprocessing.aom_voltage import AOMCalibrator
from print_preprocessing.matrix_processing import matrix_3D_to_vector_list_and_filter


def generate_signals_all_frames(
    matrix_box: list[torch.Tensor],
    samples_before_line: int,
    samples_after_line: int,
    aom_calibrator: AOMCalibrator,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate AOM voltage signals and original z-indices for non-blank frames.

    Args:
        matrix_box: A list containing the 3D matrix as a torch tensor.
                    It must be threaded through every function call until preprocessing
                    takes ownership of it with ``pop()``. Passing the raw tensor would leave
                    references alive in each caller and prevent its storage from being released.
        samples_before_line: Number of blank samples before each scan line.
        samples_after_line: Number of blank samples after each scan line.
        aom_calibrator: Initialized calibration for the selected AOM LUT.

    Returns:
        LineSignals: 2D float (num_nonzero_frames, num_points), AOM voltage per frame.
        z_indices:   1D int  (num_nonzero_frames,), original z-axis index of each
                     non-blank frame in matrix-order. Caller multiplies by z-step
                     to get per-frame stage targets and uses the indices to log
                     blank-frame skips.
    """
    matrix_box[0] = aom_calibrator.prepare_AOM_matrix(matrix_box[0])
    aom_calibrator.get_AOM_voltage(matrix_box[0])

    # Create flattened line signals, then filter and pad, keeping original z-indices
    LineSignals_tensor, z_indices_tensor = matrix_3D_to_vector_list_and_filter(
        matrix_box, samples_before_line, samples_after_line
    )

    # Convert tensors to numpy arrays
    LineSignals = LineSignals_tensor.numpy()
    del LineSignals_tensor
    z_indices = z_indices_tensor.numpy()
    del z_indices_tensor

    num_nonzero_frames = LineSignals.shape[0]
    if num_nonzero_frames:
        print(
            f"LineSignals max: {np.max(LineSignals)}, min: {np.min(LineSignals)}, dtype: {LineSignals.dtype}; "
            f"num_nonzero_frames: {num_nonzero_frames}, original z range: [{int(z_indices[0])}..{int(z_indices[-1])}]"
        )
    else:
        print("WARNING: Print file is empty, nothing will be printed.")

    return LineSignals, z_indices


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
