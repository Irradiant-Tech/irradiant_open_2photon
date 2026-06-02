import time
from datetime import timedelta

import numpy as np
import torch

from config import (
    DEFAULT_PRINT_FILE_PARAMS,
    DEFAULT_PRINT_PARAMS,
    GALVO_RECOVERY_TIME,
    GALVO_SCALING,
    VOLTAGE_AMPLITUDES,
    X_GALVO_CLIP_EXTRA_FRACTION,
    X_GALVO_CLIP_MAX_V,
)
from hardware.daq import execute_analog_output_daq
from hardware.stage.dover_controller import DoverController
from hardware.stage.mock_controller import MockController
from hardware.stage.pdxc2_controller import PDXC2Controller
from hardware.stage.xeryon.xeryon_controller import XeryonController
from print_preprocessing.galvo_control import (
    generate_x_galvo_output,
    generate_y_galvo_output,
)
from print_preprocessing.signals import (
    filter_signals_by_reference,
    generate_signals_all_frames,
)
from utils.dtypes import ProcessingDataTypes
from utils.scale_signals import scale_signals
from utils.stop_flag import StopFlag


def run_print_job(
    z_stage: PDXC2Controller | XeryonController | DoverController | MockController,
    daq_connected: bool,
    stop_flag: StopFlag,
    matrix_3D: np.ndarray = np.ones(
        (
            DEFAULT_PRINT_FILE_PARAMS["matrix_y"],
            DEFAULT_PRINT_FILE_PARAMS["matrix_x"],
            DEFAULT_PRINT_FILE_PARAMS["matrix_z"],
        )
    ),
    z_step_microns: float = DEFAULT_PRINT_PARAMS["z_step"],
    timePerPixel: float = DEFAULT_PRINT_PARAMS["time_per_pixel"] * 1e-6,
    FOV_X_um: float = DEFAULT_PRINT_PARAMS["fov_x"],
    FOV_Y_um: float = DEFAULT_PRINT_PARAMS["fov_y"],
) -> None:
    scan_size = matrix_3D.shape[1]
    print_height_px = matrix_3D.shape[0]
    z_step_nm = z_step_microns * 1000  # nm
    timeBetweenLines = GALVO_RECOVERY_TIME  # Galvo recovery time (constant)
    samplesBetweenLines = int(timeBetweenLines / timePerPixel)
    sample_rate_hz = float(1 / timePerPixel)

    print(
        f"\nStarting print job. FOV_X_um: {FOV_X_um}, FOV_Y_um: {FOV_Y_um}, z_step_nm: {z_step_nm}, time_per_pixel_us: {timePerPixel}"
    )

    # Generate AOM signals + original z-indices of non-blank frames
    LineSignals, z_indices = generate_signals_all_frames(
        torch.tensor(matrix_3D, dtype=ProcessingDataTypes.torch_dtype),
        samplesBetweenLines,
    )
    # Map original z-axis index -> position in filtered arrays. The loop below uses
    # `.get(orig)` for one-shot "is blank? where in filtered arrays?" lookup.
    orig_to_filtered = {idx: i for i, idx in enumerate(z_indices.tolist())}

    z_start = z_stage.get_position()
    if z_start is None:
        raise RuntimeError(
            f"Failed to get initial Z position from {z_stage.__class__.__name__}"
        )
    # Per-frame absolute stage targets, 1D float (num_nonzero,). Dover moves the
    # objective upward as layers progress; other stages move downward.
    sign = 1 if isinstance(z_stage, DoverController) else -1
    target_zs = (z_start + sign * z_indices * z_step_nm).astype(
        ProcessingDataTypes.numpy_dtype
    )

    # Per-frame z-piezo voltage, 1D float (num_nonzero,), normalized to ±1.
    if len(target_zs) and np.max(np.abs(target_zs)) > 0:
        z_normalized = target_zs / np.max(np.abs(target_zs))
    else:
        z_normalized = target_zs.copy()

    # Generate signals for x and y galvos scaled from -1 to 1
    x_galvo_output = generate_x_galvo_output(
        print_height_px, scan_size, samplesBetweenLines
    )
    y_galvo_output = generate_y_galvo_output(
        print_height_px, scan_size, samplesBetweenLines
    )

    # Scale galvo signals to FOV
    FOV_x_galvo_scaling = FOV_X_um / GALVO_SCALING["x"]
    FOV_y_galvo_scaling = FOV_Y_um / GALVO_SCALING["y"]
    x_galvo_scaled, y_galvo_scaled = scale_signals(
        signals=[x_galvo_output, y_galvo_output],
        amplitudes=[FOV_x_galvo_scaling, FOV_y_galvo_scaling],
    )

    # Scaled signals are copies, delete x_galvo_output and y_galvo_output
    del x_galvo_output, y_galvo_output

    # X galvo symmetric clip: magnitude = min(effective * (1 + extra), max V)
    effective_x_amplitude = FOV_x_galvo_scaling * VOLTAGE_AMPLITUDES["x_galvo"]
    x_galvo_clip_magnitude_v = min(
        effective_x_amplitude * (1 + X_GALVO_CLIP_EXTRA_FRACTION),
        X_GALVO_CLIP_MAX_V,
    )
    # Normalize x_galvo so ±1 = clip magnitude
    x_galvo_norm_scale = VOLTAGE_AMPLITUDES["x_galvo"] / x_galvo_clip_magnitude_v
    x_galvo_scaled_normalized = np.clip(
        x_galvo_scaled * x_galvo_norm_scale,
        -1.0,
        1.0,
        dtype=ProcessingDataTypes.numpy_dtype,
    )

    del x_galvo_scaled

    # Per-channel voltage amplitudes for this print job (order: CHANNEL_ORDER)
    channel_amplitudes = [
        x_galvo_clip_magnitude_v,
        VOLTAGE_AMPLITUDES["y_galvo"],
        VOLTAGE_AMPLITUDES["aom"],
        VOLTAGE_AMPLITUDES["z_piezo"],
    ]

    # Execute analog signals for each frame
    start_time = time.time()
    number_of_z_frames = matrix_3D.shape[2]
    print(
        f"Total number of z frames: {number_of_z_frames}, nonzero z frames: {len(LineSignals)}"
    )

    # Warning if no device connected for analog output
    if not daq_connected:
        print(
            "No device connected to execute analog output. Movement will still be tested."
        )

    # March through the original z-axis. Blank frames log and skip; non-blank frames
    # take their filtered position from the orig->filtered dict.
    for orig in range(number_of_z_frames):
        if stop_flag.stop:
            break

        filtered_idx = orig_to_filtered.get(orig)
        if filtered_idx is None:
            print(f"z_frame {orig + 1}/{number_of_z_frames}: blank frame skipped")
            continue

        print(f"z_frame {orig + 1}/{number_of_z_frames}")
        target_z = int(target_zs[filtered_idx])

        z_stage.move(target_z, wait_for_settled=True)
        final_pos = z_stage.get_position()
        print(f"   Z position after moving and settling: {final_pos} nm")

        aom_frame = LineSignals[filtered_idx]
        # z-piezo is a constant DC value for the whole frame
        z_piezo_frame = np.full_like(aom_frame, z_normalized[filtered_idx])

        # Filter signals based on AOM being on/off
        aom_filtered_frame, (
            x_galvo_filtered,
            y_galvo_filtered,
            z_piezo_filtered_frame,
        ) = filter_signals_by_reference(
            aom_frame,
            [x_galvo_scaled_normalized, y_galvo_scaled, z_piezo_frame],
            samplesBetweenLines + scan_size,
        )

        if daq_connected:
            if not execute_analog_output_daq(
                sample_rate_hz,
                x_galvo_filtered,
                y_galvo_filtered,
                aom_filtered_frame,
                z_piezo_filtered_frame,
                stop_flag,
                channel_amplitudes,
            ):
                break
        else:
            print(
                f"   Skipping analog output (no device), frame {orig + 1} movement completed"
            )

    if not stop_flag.stop:
        print("Print job finished successfully")
    print(
        f"Time taken to print item: {timedelta(seconds=round(time.time() - start_time))}"
    )
