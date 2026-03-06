import numpy as np
import torch

from config import AOM_POWER_RANGE, LUT_CSV_PATH, MASK_TOLERANCE
from utils.dtypes import ProcessingDataTypes

# -----------------------------------------------------------------------------
# LOAD AND CAST LUT DATA
# On first import, LUT tensors are loaded and cast once to the configured
# processing dtype to avoid repeated dtype conversions inside get_AOM_voltage().
# -----------------------------------------------------------------------------


def _compute_slopes_and_intercepts(
    x: torch.Tensor, y: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Computes slope and intercept parameters for linear interpolation over a lookup table.
    Requires monotonic x and corresponding y values.

    Given a lookup table defined by (x, y) pairs, this returns tensors slopes
    and intercepts such that for any interval:
        x[i] <= interp_val < x[i+1]

    the interpolated value can be computed as:
        y(interp_val) = slopes[i] * interp_val + intercepts[i]

    where:
        slopes[i] = (y[i+1] - y[i]) / (x[i+1] - x[i])
        intercepts[i] = y[i] - m[i] * x[i]

    Returns:
        slopes: Tensor of shape (N-1,)
        intercepts: Tensor of shape (N-1,)
    """
    slopes = (y[1:] - y[:-1]) / (x[1:] - x[:-1])
    intercepts = y[:-1] - slopes * x[:-1]

    return slopes, intercepts


# Load LUT data once (float64 for numerical stability)
_LUT_DATA = np.loadtxt(
    LUT_CSV_PATH, delimiter=",", skiprows=1
)  # Column 1 = powers, Column 2 = voltages
_POWERS_LUT_FP64 = torch.tensor(_LUT_DATA[:, 0], dtype=torch.float64)
_AOMS_LUT_FP64 = torch.tensor(_LUT_DATA[:, 1], dtype=torch.float64)

# Precompute slopes and intercepts in fp64 to avoid introducing rounding errors
_SLOPES_FP64, _INTERCEPTS_FP64 = _compute_slopes_and_intercepts(
    _POWERS_LUT_FP64, _AOMS_LUT_FP64
)

# Cast LUT and interpolation values to processing dtype
POWERS_LUT, SLOPES, INTERCEPTS = (
    ProcessingDataTypes.cast_torch(t)
    for t in (_POWERS_LUT_FP64, _SLOPES_FP64, _INTERCEPTS_FP64)
)


def get_AOM_voltage(matrix: torch.Tensor) -> None:
    """
    Converts a power matrix to AOM voltages using linear interpolation over a lookup table in-place.
    Requires LUT data to be monotonic.
    The input tensor's dtype is preserved throughout processing.

    Args:
        - matrix (torch.tensor): Input 2D or 3D matrix.

    No return: matrix is modified directly.
    """
    # Mask to filter out 0s and 1s within a tolerance
    mask = (matrix > MASK_TOLERANCE) & (matrix < 1.0 - MASK_TOLERANCE)
    vals_to_interp = matrix[mask]

    # Find index of left neighbor
    idx = torch.searchsorted(POWERS_LUT, vals_to_interp) - 1
    idx.clamp_(0, len(POWERS_LUT) - 2)

    # Use corresponding slope and intercept for in-place interpolation
    m = SLOPES[idx]
    vals_to_interp.mul_(m)
    del m
    b = INTERCEPTS[idx]
    vals_to_interp.add_(b)
    del idx, b

    # Clamp to avoid values outside of AOM voltage range.
    vals_to_interp.clamp_(AOM_POWER_RANGE[0], AOM_POWER_RANGE[1])

    # Write back in-place using scatter: original matrix tensor is permanently modified
    matrix.masked_scatter_(mask, vals_to_interp)
    del mask, vals_to_interp
