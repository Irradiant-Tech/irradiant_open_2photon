import time
from datetime import timedelta

from PyQt5.QtCore import QMutex, QThread, pyqtSignal

from hardware.stage.stage import StageController, get_z_step_direction
from hardware.stage.utils import validate_position_limit
from hardware.voltage_device.voltage_devices import AnalogDevice
from print_data.print_item import PrintItem
from printing.job_executor import run_print_job
from utils.stop_flag import StopFlag


class PointscanThread(QThread):
    finished = pyqtSignal()

    def __init__(
        self,
        z_stage: StageController,
        voltage_device: AnalogDevice | None,
        movement_lock: QMutex,
        print_item: PrintItem,
    ) -> None:
        super().__init__()
        self.running = True
        self.print_item = print_item
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
            # Validate print parameters and that final Z position of print item is within stage limits
            self.print_item.validate_print_params()
            _, _, z_um = self.print_item.matrix_extents_um()
            print_end_z_nm = (
                float(self.z_stage.position)
                + get_z_step_direction(self.z_stage) * z_um * 1e3
            )
            is_valid, error = validate_position_limit(
                self.z_stage.gui_axis, print_end_z_nm
            )
            if not is_valid and error is not None:
                raise RuntimeError(
                    f"Aborting print job. Matrix Z extent of {z_um} um exceeds the stage limits. {error}"
                )

            run_print_job(
                z_stage=self.z_stage,
                voltage_device=self.voltage_device,
                stop_flag=self.stop_flag,
                print_item=self.print_item,
            )
        except Exception as e:
            error_occurred = True
            print(f"\nPrint thread errored: {str(e)}")
        finally:
            # Fall back cleanup: run_print_job clears the matrix early to
            # reduce peak memory; clear it again here in case an earlier step failed
            self.print_item.clear_matrix()
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
