import time
from datetime import timedelta

import numpy as np
from PyQt5.QtCore import QMutex, QThread, pyqtSignal

from hardware.stage.dover_controller import DoverController
from hardware.stage.mock_controller import MockController
from hardware.stage.pdxc2_controller import PDXC2Controller
from hardware.stage.xeryon.xeryon_controller import XeryonController
from hardware.voltage_device.voltage_devices import AnalogDevice
from printing.job_executor import run_print_job
from utils.stop_flag import StopFlag


class PointscanThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        z_stage: PDXC2Controller | XeryonController | DoverController | MockController,
        voltage_device: AnalogDevice | None,
        movement_lock: QMutex,
    ) -> None:
        super().__init__()
        self.running = True
        self.matrix: np.ndarray = np.array([])
        self.params = {}
        self.z_stage = z_stage
        self.voltage_device = voltage_device
        self.stop_flag = StopFlag()
        self.movement_lock = movement_lock

    def run(self) -> None:
        thread_start_time = time.time()

        # Acquire lock with stop_flag checking - allows immediate stop even while waiting
        while not self.movement_lock.tryLock():
            if self.stop_flag.stop:
                return
            time.sleep(0.01)  # 10ms polling interval

        # Lock acquired - hold for entire print duration
        error_occurred = False
        try:
            run_print_job(
                z_stage=self.z_stage,
                voltage_device=self.voltage_device,
                stop_flag=self.stop_flag,
                matrix_3D=self.matrix,
                z_step_microns=self.params["z_step_microns"],
                timePerPixel=self.params["timePerPixel"],
                FOV_X_um=self.params["FOV_X_um"],
                FOV_Y_um=self.params["FOV_Y_um"],
            )
        except Exception as e:
            error_occurred = True
            print(f"\nPrint thread errored: {str(e)}")
        finally:
            self.movement_lock.unlock()
            self.finished.emit()
            if self.stop_flag.stop:
                print("\nPrint thread stopped by user")
            elif not error_occurred:
                print("\nPrint thread finished successfully")
                print(
                    f"Time taken to run print thread: {timedelta(seconds=round(time.time() - thread_start_time))}"
                )

    def stop(self) -> None:
        self.stop_flag.stop = True
        self.running = False


class LaserThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self, voltage_device: AnalogDevice | None, voltage: float, channel: str = "aom"
    ):
        """
        Args:
            device: The voltage device to use for outputting the constant voltage.
            voltage: The output voltage to set (e.g., 1.0 = laser ON, 0.0 = laser OFF).
            channel: The output channel to use. Defaults to "aom" (laser control),
                    but can be set to "x_galvo", "y_galvo", or "z_piezo" to apply
                    a constant voltage on those channels instead.
        """
        super().__init__()
        self.voltage_device = voltage_device
        self.voltage = voltage
        self.channel = channel
        self.stop_flag = StopFlag()

    def run(self):
        try:
            # Select device to output a constant voltage
            if not self.voltage_device:
                print("No device connected to output a constant voltage.")
                return

            self.voltage_device.output_constant_voltage(
                self.channel,
                self.voltage,
                self.stop_flag,
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self):
        self.stop_flag.stop = True
