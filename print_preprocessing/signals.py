from typing import List, Tuple, Union

import numpy as np
import torch

# Set device to GPU if available, otherwise CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
from print_preprocessing.aom_voltage import get_AOM_voltage
from print_preprocessing.matrix_processing import (
    generate_Z_signal_vectors,
    matrix_3D_to_vector_list_and_filter,
    pad_matrix_width,
)


def generate_signals_all_frames(
    matrix: Union[torch.Tensor, np.ndarray],
    samplesBetweenLines: int,
    z_step_nm: float,
    nm_per_volt: float,
    invert_scan_direction: bool = False,
) -> tuple[np.ndarray, np.ndarray, int]:
    # Convert input matrix to 64-bit tensor on GPU if it's not already a tensor
    if not isinstance(matrix, torch.Tensor):
        matrix = torch.from_numpy(matrix)
        print("converted matrix to tensor")
    if matrix.dtype != torch.float64:
        matrix = matrix.to(torch.float64)
        print("converted matrix to float64")

    try:
        # Process matrix in-place where possible
        matrix_voltage = get_AOM_voltage(matrix)  # Keep as tensor
        del matrix  # Free input matrix
        torch.cuda.empty_cache()
        Padded_matrix = pad_matrix_width(matrix_voltage, samplesBetweenLines)
        del matrix_voltage  # Free memory
        torch.cuda.empty_cache()
        # Get line signals and filter in one pass
        LineSignals_tensor = matrix_3D_to_vector_list_and_filter(Padded_matrix)
        del Padded_matrix  # Free memory
        torch.cuda.empty_cache()
        num_points = LineSignals_tensor.shape[1]
        num_nonzero_frames = LineSignals_tensor.shape[0]

        # Generate Z signals only for non-zero frames
        Z_Signals_tensor = generate_Z_signal_vectors(
            num_nonzero_frames, num_points, z_step_nm / nm_per_volt
        )

        # Invert signals if invert_scan_direction is True (in-place)
        if invert_scan_direction:
            # Create flipped views and copy in-place
            LineSignals_tensor.copy_(torch.flip(LineSignals_tensor, [0]))
            Z_Signals_tensor.copy_(torch.flip(Z_Signals_tensor, [0]))

        # Move tensors to CPU and convert to numpy arrays
        LineSignals = LineSignals_tensor.to(torch.float64).cpu().numpy()
        Z_Signals = Z_Signals_tensor.to(torch.float64).cpu().numpy()

        if num_nonzero_frames:
            print(
                f"LineSignals max: {np.max(LineSignals)}, min: {np.min(LineSignals)}; Z_Signals max: {np.max(Z_Signals)}, min: {np.min(Z_Signals)}"
            )
        else:
            print("WARNING: Print file is empty, nothing will be printed.")

        return LineSignals, Z_Signals, num_points
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
