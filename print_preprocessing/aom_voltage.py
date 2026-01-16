import numpy as np
import torch

from config import AOM_POWER_RANGE, LUT_CSV_PATH, MASK_TOLERANCE

# Set device to GPU if available, otherwise CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Column 1 = powers, Column 2 = voltages
LUT_DATA = np.loadtxt(LUT_CSV_PATH, delimiter=",", skiprows=1)
POWERS_LUT = torch.tensor(LUT_DATA[:, 0], dtype=torch.float64, device=device)
AOMS_LUT = torch.tensor(LUT_DATA[:, 1], dtype=torch.float64, device=device)


def get_AOM_voltage(matrix: torch.Tensor) -> torch.Tensor:
    """
    Converts a power matrix to AOM voltages using linear interpolation over a lookup table.
    Requires POWERS_LUT to be sorted in ascending order.

    Inputs: - matrix (torch.tensor): Input 2D or 3D matrix.

    Returns an evaluated 16-bit floating-point tensor.
    """
    # Mask to filter out 0s and 1s within a tolerance
    mask = (matrix > MASK_TOLERANCE) & (matrix < 1.0 - MASK_TOLERANCE)
    vals_to_interp = matrix[mask]

    # Find index of left neighbor
    idx = torch.searchsorted(POWERS_LUT, vals_to_interp) - 1
    idx = torch.clamp(idx, 0, len(POWERS_LUT) - 2)

    # Neighboring values
    x0 = POWERS_LUT[idx]
    x1 = POWERS_LUT[idx + 1]
    y0 = AOMS_LUT[idx]
    y1 = AOMS_LUT[idx + 1]
    del idx

    # In-place interpolation for minimal temporary allocations
    vals_to_interp.sub_(x0)  # (vals - x0)
    vals_to_interp.div_(x1 - x0)  # (vals - x0) / (x1 - x0)
    del x0, x1
    vals_to_interp.mul_(y1 - y0)  # ((vals - x0)/(x1 - x0)) * (y1 - y0)
    vals_to_interp.add_(
        y0
    )  # interpolated values: y0 + ((vals - x0)/(x1 - x0)) * (y1 - y0)
    del y0, y1

    # Clamp to avoid values outside of AOM voltage range.
    vals_to_interp.clamp_(AOM_POWER_RANGE[0], AOM_POWER_RANGE[1])

    # Write back in-place using scatter
    matrix.masked_scatter_(mask, vals_to_interp)
    del mask, vals_to_interp
    return matrix.to(device).half()
