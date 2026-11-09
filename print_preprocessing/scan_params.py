"""Helper functions for calculating scan parameters."""

from dataclasses import dataclass

from config import DEFAULT_PRINT_PARAMS, VOLTAGE_AMPLITUDES, X_GALVO_PREACCELERATION_S
from hardware.voltage_device.voltage_devices import AnalogDevice
from print_data.print_item import PrintItem
from print_preprocessing.galvo_control import (
    calculate_line_padding,
    compute_x_galvo_clip_magnitude,
)


@dataclass(frozen=True)
class ScanParams:
    """Scan parameters calculated for a given print configuration.

    All stored sample counts are at the final output rate, after oversampling.
    Each input pixel corresponds to samples_per_value output samples.

    FOV extension is applied equally on both sides of the active scan,
    preacceleration is added before the scan, and swing-back follows it.
    """

    sample_rate_hz: float  # Final output sample rate after oversampling
    samples_per_value: int  # Number of output samples per input pixel
    scan_samples: int  # Active scan samples per line (scan size)
    preacceleration_samples: int  # Preacceleration samples before the scan
    fov_extension_samples: int  # Extra scan samples on each side of the FOV
    swing_back_samples: int  # Return ramp samples after the scan
    x_galvo_clip_magnitude_v: float  # Maximum X galvo voltage required for the scan

    @property
    def blanking_samples(self) -> int:
        """Total output samples while the laser is off around each scan line."""
        return (
            self.preacceleration_samples
            + 2 * self.fov_extension_samples
            + self.swing_back_samples
        )

    @property
    def samples_per_line(self) -> int:
        return self.scan_samples + self.blanking_samples

    @property
    def base_line_padding(self) -> tuple[int, int]:
        """Return AOM padding before and after each line, before oversampling."""
        before = (
            self.preacceleration_samples
            + self.fov_extension_samples
            + self.swing_back_samples
        )
        return int(before / self.samples_per_value), int(
            self.fov_extension_samples / self.samples_per_value
        )

    @classmethod
    def from_print_item(
        cls, print_item: PrintItem, voltage_device: AnalogDevice | None = None
    ) -> "ScanParams":
        # Extract print item parameters
        matrix_shape = print_item.matrix_extents_voxels()
        time_per_pixel_us = print_item.print_params["time_per_pixel"]
        fov_x_um = print_item.print_params["fov_x"]
        use_custom_rate = print_item.print_params.get(
            "use_custom_xraster_rate", DEFAULT_PRINT_PARAMS["use_custom_xraster_rate"]
        )
        custom_rate_hz = print_item.print_params.get(
            "xraster_custom_rate_hz", DEFAULT_PRINT_PARAMS["xraster_custom_rate_hz"]
        )
        hardware_constraints = (
            voltage_device.hardware_constraints if voltage_device else None
        )

        # Base counts precede oversampling.
        base_scan_samples, print_height_px, _ = matrix_shape
        time_per_pixel_s = time_per_pixel_us * 1e-6
        sample_rate_hz = 1 / time_per_pixel_s
        samples_per_value = 1  # Oversampling factor

        # Compute custom raster rate
        if use_custom_rate and hardware_constraints is not None:
            sample_rate_hz = custom_rate_hz
            # Round the oversampling factor to a whole number
            samples_per_value = max(1, round(sample_rate_hz * time_per_pixel_s))

        # Integer oversampling quantizes the pixel dwell time at the output rate.
        quantized_time_per_pixel_s = samples_per_value / sample_rate_hz
        (
            base_preacceleration_samples,
            base_fov_extension_samples,
            base_swing_back_samples,
        ) = calculate_line_padding(
            fov_x_um, base_scan_samples, 1 / quantized_time_per_pixel_s
        )

        # Convert base pixel counts to output sample counts once for this job.
        scan_samples = base_scan_samples * samples_per_value
        preacceleration_samples = base_preacceleration_samples * samples_per_value
        fov_extension_samples = base_fov_extension_samples * samples_per_value
        swing_back_samples = base_swing_back_samples * samples_per_value

        x_galvo_clip_magnitude_v = compute_x_galvo_clip_magnitude(
            fov_x_um, scan_samples, preacceleration_samples, fov_extension_samples
        )
        scan_params = cls(
            sample_rate_hz=sample_rate_hz,
            samples_per_value=samples_per_value,
            scan_samples=scan_samples,
            preacceleration_samples=preacceleration_samples,
            fov_extension_samples=fov_extension_samples,
            swing_back_samples=swing_back_samples,
            x_galvo_clip_magnitude_v=x_galvo_clip_magnitude_v,
        )

        # Reject output rates and frames that exceed device limits.
        if hardware_constraints is not None:
            max_sample_rate_hz, max_samples_per_channel = hardware_constraints
            if scan_params.sample_rate_hz > max_sample_rate_hz:
                message = (
                    "Lower the custom sample rate."
                    if use_custom_rate
                    else "Increase the pixel dwell time."
                )
                raise ValueError(
                    f"Requested output rate of {scan_params.sample_rate_hz:g} Hz exceeds "
                    f"the device maximum of {max_sample_rate_hz:g} Hz. {message}"
                )

            required_samples_per_channel = (
                scan_params.samples_per_line * print_height_px
            )
            if required_samples_per_channel > max_samples_per_channel:
                message = (
                    "Lower the custom sample rate."
                    if scan_params.samples_per_value > 1
                    else "The frame is already at 1x oversampling; lowering the sample rate "
                    "cannot reduce the pixel count. Reduce the frame dimensions or adjust scan timing."
                )
                raise ValueError(
                    f"Generated frame will exceed device memory limits. \n{message}"
                )

        # FOV extension, if any, is symmetric. Preacceleration is added only before
        # the scan (not after), so the negative endpoint has the largest magnitude.
        if scan_params.x_galvo_clip_magnitude_v > VOLTAGE_AMPLITUDES["x_galvo"]:
            raise ValueError(
                f"[X galvo scan limit] At the current scan speed, there is not enough voltage headroom "
                f"to provide the required {X_GALVO_PREACCELERATION_S*1e3} ms of preacceleration "
                f"before the active scan; decrease the scan speed."
            )

        return scan_params
