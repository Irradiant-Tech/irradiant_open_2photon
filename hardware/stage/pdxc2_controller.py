"""
PDXC2 Stage Controller

Uses Thorlabs Kinesis Motion Control software:
https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Motion_Control

This implementation uses the Kinesis DLL (Thorlabs.MotionControl.Benchtop.Piezo.dll)
to control PDXC2 piezo controllers. All internal operations use nanometers (nm).
"""

import os
import sys
import threading
import time
from ctypes import Structure, c_char_p, c_int, c_uint32, cdll, pointer
from enum import Enum
from typing import Type

from config import PDXC2_CONFIG, THREADING_CONFIG

from .utils import validate_position_limit


class ControlMode(Enum):
    PZ_OpenLoop = 1
    PZ_CloseLoop = 2


class PDXC2_ClosedLoopParameters(Structure):
    _fields_ = [
        ("RefSpeed", c_uint32),
        ("Proportional", c_uint32),
        ("Integral", c_uint32),
        ("Differential", c_uint32),
        ("Acceleration", c_uint32),
    ]


class PDXC2Controller:
    @staticmethod
    def _load_lib():
        """Load and initialize the Kinesis DLL."""
        kinesis_dir = PDXC2_CONFIG["kinesis_path"]
        dll_file = "Thorlabs.MotionControl.Benchtop.Piezo.dll"
        if sys.version_info < (3, 8):
            os.chdir(kinesis_dir)
        else:
            os.add_dll_directory(kinesis_dir)
        lib = cdll.LoadLibrary(dll_file)
        lib.TLI_InitializeSimulations()
        return lib

    @classmethod
    def is_connected(cls: Type["PDXC2Controller"], serial: str) -> bool:
        """Check if device is connected."""
        try:
            lib = cls._load_lib()
            if lib.TLI_BuildDeviceList() == 0:
                ret = lib.PDXC2_Open(c_char_p(serial.encode()))
                if ret == 0:
                    lib.PDXC2_Close(c_char_p(serial.encode()))
                    return True
            return False
        except Exception:
            return False

    def __init__(self, serial: str, home: bool = False, axis: str = "X") -> None:
        """Initialize the PDXC2 controller"""
        self.serial = c_char_p(serial.encode())
        self.position_c = c_int(1)
        self.position_pointer = pointer(self.position_c)
        self.position = int(self.position_c.value)
        self.axis = axis
        self._position_timer = None  # Add timer reference
        self._stop_timer = False  # Add flag to control timer
        self._last_desired_position = None

        print(f"{axis} axis: Connected to PDXC2Controller")
        self.lib = self._load_lib()
        self.setup(home=home)

    def setup(self, home: bool = False) -> None:
        max_retries = 10
        retry_delay = 2
        retry_count = 0

        while retry_count < max_retries:
            if self.lib.TLI_BuildDeviceList() == 0:
                ret = self.lib.PDXC2_Open(self.serial)
                print(f"PDXC2_Open Returned {ret} for {self.axis} axis.")
                if ret == 0:
                    self.lib.PDXC2_Enable(self.serial)
                    print(f"Device Enabled for {self.axis} axis.")
                    print(f"Device successfully enabled for {self.axis} axis.")

                    self.lib.PDXC2_SetPositionControlMode(
                        self.serial, ControlMode.PZ_CloseLoop.value
                    )
                    print(
                        f"Set the operation mode to closed loop mode for {self.axis} axis."
                    )
                    time.sleep(1)

                    params = [
                        c_uint32(PDXC2_CONFIG["ref_speed"]),  # ref_speed
                        c_uint32(PDXC2_CONFIG["proportional"]),  # proportional
                        c_uint32(PDXC2_CONFIG["integral"]),  # integral
                        c_uint32(PDXC2_CONFIG["differential"]),  # differential
                        c_uint32(PDXC2_CONFIG["acceleration"]),  # acceleration
                    ]
                    params_struct = PDXC2_ClosedLoopParameters(*params)
                    self.lib.PDXC2_SetClosedLoopParams(self.serial, params_struct)

                    if home:
                        self.home()

                    self._stop_timer = False

                    def monitor_position():
                        while not self._stop_timer:
                            position = self.get_position()
                            if position is not None:
                                self.position = position
                            time.sleep(THREADING_CONFIG["position_monitor_interval"])

                    self._position_timer = threading.Thread(
                        target=monitor_position, daemon=True
                    )
                    self._position_timer.start()
                    return
            print(
                f"Error enabling device. Retrying... ({retry_count + 1}/{max_retries})"
            )
            retry_count += 1
            time.sleep(retry_delay)

        raise RuntimeError("Failed to enable the device after multiple attempts.")

    def get_position(self) -> int:
        """Get the current position"""
        self.lib.PDXC2_RequestPosition(self.serial)
        self.lib.PDXC2_GetPosition(self.serial, self.position_pointer)
        return self.position_c.value

    def get_desired_position(self) -> int:
        """Get the last desired position in nanometers."""
        if self._last_desired_position is not None:
            return int(self._last_desired_position)
        # Fallback to current position if no desired position has been set
        return self.get_position()

    def move(
        self,
        target: float,
        tolerance: int = PDXC2_CONFIG["movement"]["tolerance"],
        wait_for_settled: bool = False,
    ) -> None:
        """Move to target position in nanometers.

        Args:
            target: Target position in nanometers
            tolerance: Tolerance in nanometers
            wait_for_settled: Ignored (PDXC2 already waits internally)
        """
        sleep_step = PDXC2_CONFIG["movement"]["sleep_step"]
        target_nm = target

        # Check per-axis limits
        is_valid, error_msg = validate_position_limit(self.axis, target_nm)
        if not is_valid:
            print(error_msg)
            return

        self._last_desired_position = target_nm
        self.lib.PDXC2_SetClosedLoopTarget(self.serial, c_int(int(target_nm)))
        self.lib.PDXC2_MoveStart(self.serial)
        try:
            while bool(
                self.lib.PDXC2_GetStatusBits(self.serial)
                & PDXC2_CONFIG["status_bits_mask"]
            ):
                time.sleep(sleep_step)
        except Exception as e:
            print(f"Error: {e}")

        current_pos = self.position
        while abs(current_pos - target_nm) > tolerance:
            time.sleep(sleep_step)
            current_pos = self.position

    def stop(self) -> None:
        current_pos = self.get_position()
        self._last_desired_position = current_pos
        self.lib.PDXC2_SetClosedLoopTarget(self.serial, c_int(current_pos))
        self.lib.PDXC2_MoveStop(self.serial)
        print(f"Stopped movement for {self.axis} axis")

    def home(self) -> None:
        """Find reference position and move to zero."""
        print(f"Starting reference finding for {self.axis} axis.")
        pos_check_cnt = 0
        self.lib.PDXC2_Home(self.serial)

        for _ in range(PDXC2_CONFIG["reference_finding"]["check_count"]):
            self.lib.PDXC2_RequestPosition(self.serial)
            self.lib.PDXC2_GetPosition(self.serial, self.position_pointer)
            if (
                abs(self.position_c.value)
                < PDXC2_CONFIG["reference_finding"]["tolerance"]
            ):
                if pos_check_cnt > 3:
                    time.sleep(PDXC2_CONFIG["reference_finding"]["final_sleep"])
                    break
                pos_check_cnt += 1
            time.sleep(PDXC2_CONFIG["reference_finding"]["sleep_time"])
        # Update last desired position to 0 after reference finding completes
        self._last_desired_position = 0
        print(f"Reference finding finished for {self.axis} axis.")

    def close(self) -> None:
        """Close the connection to the device"""
        self._stop_timer = True  # Stop the position monitoring
        if self._position_timer:
            self._position_timer.join()  # Wait for thread to finish
        self.lib.PDXC2_Close(self.serial)
        print(f"Device connection closed for {self.axis} axis.")
