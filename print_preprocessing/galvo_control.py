import numpy as np

from config import (
    AO_PROCESSING_DTYPE,
    FOV_UPPER_LIMIT_V,
    GALVO_SCAN_BANDWIDTH_HZ,
    GALVO_UM_PER_V,
    SWING_BACK_INTERCEPT_S,
    SWING_BACK_SLOPE_S_PER_V,
    X_GALVO_PREACCELERATION_S,
)

# ------------------------------------
# Waveform Generation
# ------------------------------------


def generate_x_galvo_output(
    print_height_px: int,
    scan_size: int,
    preacceleration_samples: int,
    fov_extension_samples: int,
    swing_back_samples: int = 0,
) -> np.ndarray:
    """Generate return and scan segments; active scan runs from -1 to 1."""
    # Extend the active raster slope into the blank samples on both sides.
    raster_interval = (-1, 1)  # start/end of scan_size raster interval
    step = (raster_interval[1] - raster_interval[0]) / max(scan_size - 1, 1)
    line_start = (
        raster_interval[0] - (preacceleration_samples + fov_extension_samples) * step
    )
    line_end = raster_interval[0] + (scan_size - 1 + fov_extension_samples) * step

    n = preacceleration_samples + scan_size + 2 * fov_extension_samples
    x_raster = np.linspace(line_start, line_end, n, dtype=AO_PROCESSING_DTYPE)

    # Start at the previous line's maximum, ramp back, then accelerate into the scan.
    swing_back = np.linspace(
        line_end, line_start, swing_back_samples, dtype=AO_PROCESSING_DTYPE
    )
    x_line = np.concatenate((swing_back, x_raster))
    x_galvo_output = np.tile(x_line, print_height_px)
    return x_galvo_output


def generate_y_galvo_output(
    print_height_px: int, scan_size: int, blanking_samples: int
) -> np.ndarray:
    """Generates normalized Y-galvo (slow axis) output signal."""
    y_raster = np.linspace(-1.0, 1.0, print_height_px, dtype=AO_PROCESSING_DTYPE)
    y_galvo_output = np.repeat(y_raster, scan_size + blanking_samples)
    return y_galvo_output


# ------------------------------------
# Galvo Scan Calculations
# ------------------------------------


def compute_galvo_amplitude(fov_um: float, axis: str) -> float:
    """Return the voltage amplitude for a centered field of view (um)."""
    return (fov_um / 2) / GALVO_UM_PER_V[axis]


def compute_x_galvo_clip_magnitude(
    fov_x_um: float,
    scan_size: int,
    preacceleration_samples: int,
    fov_extension_samples: int,
) -> float:
    """Return the required X voltage magnitude, including extension and preacceleration."""
    x_amp_v = compute_galvo_amplitude(fov_x_um, "x")
    # The raster has its first and last active samples at opposite FOV edges, with
    # positions scan_size - 1 sample intervals apart; use this to calculate the
    # voltage slope for preacceleration
    volts_per_sample = (2 * x_amp_v) / max(scan_size - 1, 1)
    return x_amp_v + volts_per_sample * (
        preacceleration_samples + fov_extension_samples
    )


def calculate_min_fov(speed_mm_per_s: float) -> float:
    """Return the minimum X FOV in um needed to stay within the scan bandwidth."""
    speed_um_per_s = speed_mm_per_s * 1000
    required_extra_v = X_GALVO_PREACCELERATION_S * speed_um_per_s / GALVO_UM_PER_V["x"]
    # Line period = FOV / speed_um_per_s + preacceleration time
    #               + m_s_per_v * return voltage + b_s.
    min_fov_um = max(
        (
            1 / GALVO_SCAN_BANDWIDTH_HZ
            - X_GALVO_PREACCELERATION_S
            - SWING_BACK_SLOPE_S_PER_V * required_extra_v
            - SWING_BACK_INTERCEPT_S
        )
        / (1 / speed_um_per_s + SWING_BACK_SLOPE_S_PER_V / GALVO_UM_PER_V["x"]),
        0.0,
    )
    return min_fov_um


def calculate_line_padding(
    fov_x_um: float, scan_size: int, sample_rate_hz: float
) -> tuple[int, int, int]:
    """Return preacceleration, FOV extension per side and swing-back base counts.

    The FOV extension is applied equally on both sides of the scan area.
    Preacceleration is added only before the scan area:
        before = preacceleration_samples + fov_extension_samples
        after = fov_extension_samples
        total blanking = preacceleration_samples + 2 * fov_extension_samples
                         + swing_back_samples
    Round up samples (np.ceil) so the required duration is never shortened.
    """
    # First and last active samples are scan_size - 1 intervals apart
    intervals = max(scan_size - 1, 1)
    speed_um_per_s = fov_x_um * sample_rate_hz / intervals
    volts_per_sample = fov_x_um / GALVO_UM_PER_V["x"] / intervals

    # Use the larger of the requested FOV and the minimum width required by the bandwidth limit
    # and split any additional scan width equally between both sides of the requested FOV
    min_fov_um = calculate_min_fov(speed_um_per_s * 1e-3)
    fov_extension_samples = int(
        np.ceil(max(0, min_fov_um - fov_x_um) * intervals / fov_x_um / 2)
    )

    # PrintItem.validate_print_params() checks the requested FOV against the scan
    # limit; this check covers the extra width required by the bandwidth limit.
    extended_fov_v = (intervals + 2 * fov_extension_samples) * volts_per_sample
    if extended_fov_v > FOV_UPPER_LIMIT_V:
        extended_fov_um = extended_fov_v * GALVO_UM_PER_V["x"]
        upper_limit_fov_um = FOV_UPPER_LIMIT_V * GALVO_UM_PER_V["x"]
        raise ValueError(
            f"[X galvo bandwidth limit] For the current scan speed, the galvo bandwidth limit requires "
            f"extending the requested X FOV of {fov_x_um:.2f} µm to {extended_fov_um:.2f} µm "
            f"({extended_fov_v:.2f} V full span). This exceeds the maximum full scan "
            f"span of {upper_limit_fov_um:.2f} µm before preacceleration. "
        )

    preacceleration_samples = int(np.ceil(X_GALVO_PREACCELERATION_S * sample_rate_hz))

    # Calculate voltage return distance (active FOV + 2 * FOV extension + pre-acceleration distance)
    swing_back_v = (
        intervals + 2 * fov_extension_samples + preacceleration_samples
    ) * volts_per_sample
    swing_back_time_s = SWING_BACK_SLOPE_S_PER_V * swing_back_v + SWING_BACK_INTERCEPT_S
    swing_back_samples = int(np.ceil(swing_back_time_s * sample_rate_hz))
    return preacceleration_samples, fov_extension_samples, swing_back_samples
