"""Convert normalized laser power fractions to normalized AOM voltage values.

Both columns of the calibration table are normalized to the range [0, 1].
The resulting AOM signal remains as normalized voltages; the DAQ converts it to
physical voltage by multiplying by the configured AOM channel amplitude.
"""

import math

import numpy as np
import torch

from config import (
    AOM_PROCESSING_DTYPE_TORCH,
    FP16_POS_INF_BITS,
    FP16_POS_ZERO_BITS,
    FP16_WORKING_LIMIT,
    LUT_CSV_PATH,
    MASK_TOLERANCE,
)


def _compute_slopes_and_intercepts(
    x: torch.Tensor, y: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Computes slope and intercept parameters for linear interpolation over a lookup table.
    Requires monotonic x and corresponding y values.

    Given a lookup table defined by (x, y) pairs, this returns tensors slopes
    and intercepts such that for any interval: x[i] <= interp_val < x[i+1]

    the interpolated value can be computed as: y(interp_val) = slopes[i] * interp_val + intercepts[i]

    where: slopes[i] = (y[i+1] - y[i]) / (x[i+1] - x[i])
           intercepts[i] = y[i] - m[i] * x[i]

    Returns: (slopes, intercepts), tensor of shape (N-1,)
    """
    slopes = (y[1:] - y[:-1]) / (x[1:] - x[:-1])
    intercepts = y[:-1] - slopes * x[:-1]

    return slopes, intercepts


def _linear_interp_inplace(
    values: torch.Tensor,
    x_lut: torch.Tensor,
    slopes: torch.Tensor,
    intercepts: torch.Tensor,
) -> None:
    """Linearly interpolate values in place using precomputed LUT slopes and intercepts.

    For each value, finds the LUT interval immediately to its left and
    evaluates ``y = mx + b`` while minimizing temporary memory use.
    """
    # Find index of left neighbor
    idx = torch.searchsorted(x_lut, values)
    idx.sub_(1)
    idx.clamp_(0, len(x_lut) - 2)

    # Use corresponding slope and intercept for in-place interpolation
    m = slopes[idx]
    values.mul_(m)
    del m

    b = intercepts[idx]
    values.add_(b)
    del b, idx


class AOMCalibrator:
    """AOM calibration data and its precomputed interpolation lookup tables."""

    def __init__(self, calibration_file: str):
        """
        Args: - calibration_file: CSV path to calibration LUT where:
                                  column 1 = normalized power
                                  column 2 = AOM voltage
        """
        self.calibration_file = calibration_file
        self.scale_factor = 1.0
        self.fp16_voltage_table: torch.Tensor | None = None
        self.powers_lut: torch.Tensor | None = None
        self.slopes: torch.Tensor | None = None
        self.intercepts: torch.Tensor | None = None

        # Keep the source data in FP64 to avoid introducing FP noise
        self.lut_data = np.loadtxt(
            self.calibration_file, delimiter=",", skiprows=1, ndmin=2
        )
        if self.lut_data.shape[1] != 2:
            raise ValueError(
                "AOM calibration file must contain exactly 2 columns (normalized power and AOM voltage)."
            )
        if self.lut_data.shape[0] < 2:
            raise ValueError(
                "AOM calibration file must contain at least 2 data rows after the header."
            )
        if not np.isfinite(self.lut_data).all():
            raise ValueError("AOM calibration file must contain only finite values.")
        powers = self.lut_data[:, 0]
        voltages = self.lut_data[:, 1]
        if not np.all(
            (powers >= 0) & (powers <= 1) & (voltages >= 0) & (voltages <= 1)
        ):
            raise ValueError(
                "AOM calibration voltages and powers fractions must be normalized within [0, 1]."
            )
        if not np.all(np.diff(powers) > 0):
            raise ValueError("AOM calibration powers must be strictly increasing.")

        self.powers_lut_fp64 = torch.tensor(powers, dtype=torch.float64)
        self.voltages_lut_fp64 = torch.tensor(voltages, dtype=torch.float64)
        self.slopes_fp64, self.intercepts_fp64 = _compute_slopes_and_intercepts(
            self.powers_lut_fp64, self.voltages_lut_fp64
        )

        # Max. voltage limit uses the LUT's full power voltage to maintain consistent power
        # at the sample plane, while never exceeding min/max of the normalized [0,1] range.
        self.voltage_lim_upper = min(1, self.voltages_lut_fp64[-1].item())
        self.voltage_lim_lower = max(0, self.voltages_lut_fp64[0].item())

        if AOM_PROCESSING_DTYPE_TORCH == torch.float16:
            # FP16 LUT preparation
            self.scale_factor, self.fp16_voltage_table = self._prepare_AOM_lut_fp16()
        else:
            # FP32/FP64 LUT preparation
            self.powers_lut = self.powers_lut_fp64.to(dtype=AOM_PROCESSING_DTYPE_TORCH)
            self.slopes = self.slopes_fp64.to(dtype=AOM_PROCESSING_DTYPE_TORCH)
            self.intercepts = self.intercepts_fp64.to(dtype=AOM_PROCESSING_DTYPE_TORCH)

    def _prepare_AOM_lut_fp16(self):
        """Precompute the FP16 AOM voltage LUT and input scale factor. The returned LUT is converted
        back to normalized voltage units and clamped to configured hardware/calibration limits.

        Input powers are scaled before FP16 conversion to move FP16 subnormal range values upward
        so they retain normal FP16 significand precision. Scale factor is a power of two matrix values
        are shifted by exponent only (avoiding additional quantization).
        ``prepare_AOM_matrix()`` should be called on an input matrix before ``get_AOM_voltage()``.
        """
        # Create LUT of all non-negative FP16 values in FP64 to avoid precision loss
        fp16_values = (
            torch.arange(FP16_POS_ZERO_BITS, FP16_POS_INF_BITS, dtype=torch.int16)
            .view(torch.float16)
            .to(torch.float64)
        )

        # Compute scale factor; largest power-of-two scale within the working limit of FP16.
        # At runtime, only scaled FP16 quantity is input power matrix. All other calcs happen in FP64.
        self.scale_factor = 2.0 ** math.floor(math.log2(FP16_WORKING_LIMIT / 1))

        # Scale input LUT values into the same domain as the matrix
        powers_lut_scaled_fp64 = self.powers_lut_fp64 * self.scale_factor
        intercepts_scaled_fp64 = self.intercepts_fp64 * self.scale_factor

        # Interpolate each value, return voltage to normalized units, and clamp
        _linear_interp_inplace(
            fp16_values,
            powers_lut_scaled_fp64,
            self.slopes_fp64,
            intercepts_scaled_fp64,
        )
        voltage_fp64 = fp16_values / self.scale_factor
        voltage_fp64.clamp_(self.voltage_lim_lower, self.voltage_lim_upper)

        # Return final table in processing dtype
        fp16_voltage_table = voltage_fp64.to(dtype=AOM_PROCESSING_DTYPE_TORCH)
        return self.scale_factor, fp16_voltage_table

    def _interpolate_AOM_voltage(self, matrix: torch.Tensor) -> None:
        """Converts a power matrix to AOM voltages using linear interpolation using a lookup table in-place.
        Used for processing dtypes other than FP16, where ``SCALE_FACTOR`` must be 1.0.
        """
        if self.scale_factor != 1.0:
            raise ValueError(
                "_interpolate_AOM_voltage requires an unscaled matrix (``scale_factor`` must be 1.0)."
            )
        if self.powers_lut is None or self.slopes is None or self.intercepts is None:
            raise RuntimeError(
                "FP32/FP64 LUT is unavailable because AOM_PROCESSING_DTYPE_TORCH is torch.float16."
            )

        mask = (matrix > MASK_TOLERANCE) & (matrix < 1.0 - MASK_TOLERANCE)
        vals_to_interp = matrix[mask]
        _linear_interp_inplace(
            vals_to_interp, self.powers_lut, self.slopes, self.intercepts
        )

        # Map endpoints to the LUT's boundary voltages: power 0 -> V(0) and power 1 -> V(full).
        # Interior values are overwritten below by ``masked_scatter_``.
        matrix.mul_(self.voltage_lim_upper - self.voltage_lim_lower)
        matrix.add_(self.voltage_lim_lower)
        matrix.masked_scatter_(mask, vals_to_interp)

        # Write back in-place using scatter: original matrix tensor is permanently modified
        matrix.clamp_(self.voltage_lim_lower, self.voltage_lim_upper)

    def _lookup_fp16_voltage(self, matrix: torch.Tensor) -> None:
        """Replace scaled FP16 powers with voltages using the direct FP16 LUT where each non-negative
        FP16 bit maps directly to its corresponding integer LUT index.
        """
        if self.fp16_voltage_table is None:
            raise RuntimeError(
                "FP16 voltage LUT is unavailable because AOM_PROCESSING_DTYPE_TORCH is not torch.float16."
            )
        # Reinterpret each FP16 value's raw bits as a LUT index
        indices = matrix.view(torch.int16).to(torch.int32)
        # Look up each voltage and write it directly into the matrix without allocating a separate output tensor
        torch.index_select(
            self.fp16_voltage_table, 0, indices.view(-1), out=matrix.view(-1)
        )

    def prepare_AOM_matrix(self, matrix: torch.Tensor) -> torch.Tensor:
        """Scale and convert the original power matrix to the AOM processing dtype.

        FP16 inputs are scaled before conversion to improve resolution for subnormal
        powers. The scale is 1.0 for other processing dtypes.

        This step is separate from voltage conversion so the caller can replace and release
        the original matrix before temporary tensors are allocated.
        """
        if not torch.isfinite(matrix).all():
            raise ValueError("AOM power matrix must contain only finite values.")
        # abs_() turns IEEE -0 into +0 so FP16 bit-index lookup stays in-range
        matrix.clamp_(0, 1).abs_()
        matrix.mul_(self.scale_factor)
        return matrix.to(AOM_PROCESSING_DTYPE_TORCH)

    def get_AOM_voltage(self, matrix: torch.Tensor) -> None:
        """Convert a prepared power matrix to normalized AOM voltage in place.

        For FP16 processing, the matrix must already be scaled by ``scale_factor``
        and converted to FP16 by ``prepare_AOM_matrix``. Its FP16 bit patterns are
        used directly as indices into the precomputed voltage table.

        For FP32 or FP64 processing, voltages are computed directly from the
        calibration LUT using linear interpolation.
        """
        if AOM_PROCESSING_DTYPE_TORCH == torch.float16:
            self._lookup_fp16_voltage(matrix)
        else:  # (torch.float32, torch.float64)
            self._interpolate_AOM_voltage(matrix)


# Initialize one instance of AOM calibrator using the default LUT path
AOM_CALIBRATOR = AOMCalibrator(LUT_CSV_PATH)
