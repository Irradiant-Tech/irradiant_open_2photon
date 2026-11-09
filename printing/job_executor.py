import time
from datetime import timedelta

import numpy as np
import torch

from config import (
    AO_PROCESSING_DTYPE,
    VOLTAGE_AMPLITUDES,
    ZSTAGE_PROCESSING_DTYPE_NUMPY,
)
from hardware.stage.stage import StageController, get_z_step_direction
from hardware.voltage_device.voltage_devices import AnalogDevice
from print_data.print_item import PrintItem
from print_preprocessing.aom_voltage import AOMCalibrator
from print_preprocessing.galvo_control import (
    compute_galvo_amplitude,
    generate_x_galvo_output,
    generate_y_galvo_output,
)
from print_preprocessing.scan_params import ScanParams
from print_preprocessing.signals import (
    filter_signals_by_reference,
    generate_signals_all_frames,
)
from utils.scale_signals import scale_signals
from utils.stop_flag import StopFlag


def run_print_job(
    z_stage: StageController,
    voltage_device: AnalogDevice | None,
    stop_flag: StopFlag,
    print_item: PrintItem,
    aom_calibrator: AOMCalibrator,
) -> None:
    matrix_3D = print_item.load_matrix()
    scan_params = ScanParams.from_print_item(
        print_item=print_item, voltage_device=voltage_device
    )

    # Print parameters
    time_per_pixel_us = print_item.print_params["time_per_pixel"]
    FOV_X_um = print_item.print_params["fov_x"]
    FOV_Y_um = print_item.print_params["fov_y"]

    # Scan parameters
    scan_size = scan_params.scan_samples
    print_height_px = matrix_3D.shape[1]
    number_of_z_frames = matrix_3D.shape[2]
    z_step_nm = print_item.print_params["z_step"] * 1000

    print(
        f"\nStarting print job. FOV_X_um: {FOV_X_um}, FOV_Y_um: {FOV_Y_um}, z_step_nm: {z_step_nm}, time_per_pixel_us: {time_per_pixel_us}"
    )
    if scan_params.samples_per_value > 1:
        print(
            f"Using output rate {scan_params.sample_rate_hz*10**-6:.1f} MHz, with oversampling factor of {scan_params.samples_per_value}x."
        )

    # Generate AOM signals + original z-indices of non-blank frames
    # Hand the matrix off via a list and drop our reference so the function can
    # release the original before allocating the padded/flattened tensors.
    # Torch uses the corresponding NumPy dtype exactly; omit explicit dtype conversion.
    matrix_box = [torch.from_numpy(matrix_3D)]

    # Remove the cached reference. ``matrix_box`` still keeps the memory alive.
    print_item.clear_matrix()
    del matrix_3D

    LineSignals, z_indices = generate_signals_all_frames(
        matrix_box, *scan_params.base_line_padding, aom_calibrator
    )
    # Map original z-axis index -> position in filtered arrays. The loop below uses
    # `.get(orig)` for one-shot "is blank? where in filtered arrays?" lookup.
    orig_to_filtered = {idx: i for i, idx in enumerate(z_indices.tolist())}

    z_start = z_stage.get_position()
    if z_start is None:
        raise RuntimeError(
            f"Failed to get initial Z position from {z_stage.__class__.__name__}"
        )
    # Per-frame absolute stage targets, 1D float (num_nonzero,).
    target_zs = (
        z_start + get_z_step_direction(z_stage) * z_indices * z_step_nm
    ).astype(ZSTAGE_PROCESSING_DTYPE_NUMPY)

    # Per-frame z-piezo voltage, 1D float (num_nonzero,), normalized to ±1.
    if len(target_zs) and np.max(np.abs(target_zs)) > 0:
        z_normalized = target_zs / np.max(np.abs(target_zs))
    else:
        z_normalized = target_zs.copy()

    # Generate signals for x and y galvos scaled from -1 to 1
    x_galvo_output = generate_x_galvo_output(
        print_height_px,
        scan_size,
        scan_params.preacceleration_samples,
        scan_params.fov_extension_samples,
        scan_params.swing_back_samples,
    )
    y_galvo_output = generate_y_galvo_output(
        print_height_px,
        scan_size,
        scan_params.blanking_samples,
    )

    # Scale each galvo for the requested FOV relative to its output amplitude.
    x_normalized_amplitude = (
        compute_galvo_amplitude(FOV_X_um, "x") / scan_params.x_galvo_clip_magnitude_v
    )
    y_normalized_amplitude = (
        compute_galvo_amplitude(FOV_Y_um, "y") / VOLTAGE_AMPLITUDES["y_galvo"]
    )

    # DAQ clips FP noise during output conversion; no intermediate clip after normalization
    x_galvo_norm, y_galvo_norm = scale_signals(
        signals=[x_galvo_output, y_galvo_output],
        amplitudes=[x_normalized_amplitude, y_normalized_amplitude],
    )

    # Scaled signals are copies, delete x_galvo_output and y_galvo_output
    del x_galvo_output, y_galvo_output

    # Per-channel voltage amplitudes for this print job (order: CHANNEL_ORDER)
    channel_amplitudes = [
        scan_params.x_galvo_clip_magnitude_v,
        VOLTAGE_AMPLITUDES["y_galvo"],
        VOLTAGE_AMPLITUDES["aom"],
        VOLTAGE_AMPLITUDES["z_piezo"],
    ]

    # Execute analog signals for each frame
    start_time = time.time()
    print(
        f"Total number of z frames: {number_of_z_frames}, nonzero z frames: {len(LineSignals)}"
    )

    if not voltage_device:
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

        move_succeeded = z_stage.move(target_z, wait_for_settled=True)
        if not move_succeeded:
            raise RuntimeError(
                f"Aborting print job. Failed to move to z-position for print item: {target_z} nm"
            )

        final_pos = z_stage.get_position()
        print(f"   Z position after moving and settling: {final_pos} nm")

        aom_frame = LineSignals[filtered_idx]

        # Expand to num_points * samples_per_value samples per frame.
        # AOM varies per pixel; z-piezo is a constant DC value for the whole frame.
        aom_frame_expanded = np.repeat(aom_frame, scan_params.samples_per_value)
        z_piezo_frame_expanded = np.full_like(
            aom_frame_expanded, z_normalized[filtered_idx], dtype=AO_PROCESSING_DTYPE
        )

        # Filter signals based on AOM being on/off
        aom_filtered_frame, (
            x_galvo_filtered,
            y_galvo_filtered,
            z_piezo_filtered_frame,
        ) = filter_signals_by_reference(
            aom_frame_expanded,
            [x_galvo_norm, y_galvo_norm, z_piezo_frame_expanded],
            scan_params.samples_per_line,
        )
        # Filtered signals are copies, delete aom_frame_expanded and z_piezo_frame_expanded
        del aom_frame_expanded, z_piezo_frame_expanded

        if voltage_device:
            if not voltage_device.execute_analog_output(
                scan_params.sample_rate_hz,
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
