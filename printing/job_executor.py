import time

import numpy as np
import torch

from config import (
    DEFAULT_PRINT_FILE_PARAMS,
    DEFAULT_PRINT_PARAMS,
    GALVO_RECOVERY_TIME,
    GALVO_SCALING,
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

    # Generate AOM and z-voltage signals for each frame
    LineSignals, Z_Signals, num_points = generate_signals_all_frames(
        torch.tensor(matrix_3D),
        samplesBetweenLines,
        z_step_nm,
        nm_per_volt=1,
        invert_scan_direction=False,
    )

    z_start = z_stage.get_position()
    if z_start is None:
        raise RuntimeError(
            f"Failed to get initial Z position from {z_stage.__class__.__name__}"
        )
    # Dover moves the objective upward (positive direction) as layers progress
    if isinstance(z_stage, DoverController):
        Z_Signals = float(z_start) + np.array(Z_Signals)
    else:
        Z_Signals = float(z_start) - np.array(Z_Signals)
    Z_analog_out = Z_Signals.copy()
    if len(Z_analog_out) and np.max(np.abs(Z_analog_out)) > 0:
        Z_analog_out = Z_analog_out / np.max(np.abs(Z_analog_out))

    # Generate signals for x and y galvos scaled from -1 to 1V
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

    # Execute analog signals for each frame
    start_time = time.time()
    print(f"Starting print job with {len(LineSignals)} z frames")
    print(f"z_start position: {z_start} nm")

    # Warning if no device connected for analog output
    if not daq_connected:
        print(
            "No device connected to execute analog output. Movement will still be tested."
        )

    for z_frame in range(len(LineSignals)):
        if stop_flag.stop:
            print("Print stopped by user")
            break

        print(f"z_frame {z_frame}/{len(LineSignals)-1}")
        target_z = float(
            Z_Signals[z_frame, 0]
        )  # Extract scalar from array (all values in frame are same)
        current_pos = z_stage.get_position()
        print(f"   Current Z position: {current_pos} nm, Target Z: {target_z} nm")
        z_stage.move(int(target_z), wait_for_settled=True)
        final_pos = z_stage.get_position()
        print(f"   Final Z position after moving and settling: {final_pos} nm")

        aom_frame = LineSignals[z_frame]
        z_piezo_frame = Z_analog_out[z_frame]

        # Filter signals based on AOM being on/off
        aom_filtered_frame, (
            x_galvo_filtered,
            y_galvo_filtered,
            z_piezo_filtered_frame,
        ) = filter_signals_by_reference(
            aom_frame,
            [x_galvo_scaled, y_galvo_scaled, z_piezo_frame],
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
            ):
                break
        else:
            print(
                f"Skipping analog output (no device), frame {z_frame} movement completed"
            )

    print(
        "Print completed successfully."
        if not stop_flag.stop
        else "Print stopped by user during analog output."
    )
    print(f"Time taken to print: {time.time() - start_time}")
