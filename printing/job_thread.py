import time

import numpy as np
from PyQt5.QtCore import QMutex, QThread, pyqtSignal

from hardware.daq import output_constant_voltage_daq
from hardware.stage.dover_controller import DoverController
from hardware.stage.mock_controller import MockController
from hardware.stage.pdxc2_controller import PDXC2Controller
from hardware.stage.xeryon.xeryon_controller import XeryonController
from printing.job_executor import run_print_job
from utils.stop_flag import StopFlag


class PointscanThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        z_stage: PDXC2Controller | XeryonController | DoverController | MockController,
        daq_connected: bool,
        movement_lock: QMutex,
    ) -> None:
        super().__init__()
        self.running = True
        self.matrix: np.ndarray = np.array([])
        self.params = {}
        self.z_stage = z_stage
        self.daq_connected = daq_connected
        self.stop_flag = StopFlag()
        self.movement_lock = movement_lock

    def run(self) -> None:
        # Acquire lock with stop_flag checking - allows immediate stop even while waiting
        while not self.movement_lock.tryLock():
            if self.stop_flag.stop:
                return
            time.sleep(0.01)  # 10ms polling interval

        # Lock acquired - hold for entire print duration
        try:
            run_print_job(
                z_stage=self.z_stage,
                daq_connected=self.daq_connected,
                stop_flag=self.stop_flag,
                matrix_3D=self.matrix,
                z_step_microns=self.params["z_step_microns"],
                timePerPixel=self.params["timePerPixel"],
                FOV_X_um=self.params["FOV_X_um"],
                FOV_Y_um=self.params["FOV_Y_um"],
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.movement_lock.unlock()
            self.finished.emit()

    def stop(self) -> None:
        self.stop_flag.stop = True
        self.running = False


class LaserThread(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, daq_connected: bool, voltage: float, channel: str = "aom"):
        """
        Args:
            voltage: The output voltage to set (e.g., 1.0 = laser ON, 0.0 = laser OFF).
            channel: The output channel to use. Defaults to "aom" (laser control),
                    but can be set to "x_galvo", "y_galvo", or "z_piezo" to apply
                    a constant voltage on those channels instead.
        """
        super().__init__()
        self.daq_connected = daq_connected
        self.voltage = voltage
        self.channel = channel
        self.stop_flag = StopFlag()

    def run(self):
        try:
            if not self.daq_connected:
                print("No device connected to output a constant voltage.")
                return

            output_constant_voltage_daq(
                channel=self.channel,
                voltage=self.voltage,
                stop_flag=self.stop_flag,
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def stop(self):
        self.stop_flag.stop = True
