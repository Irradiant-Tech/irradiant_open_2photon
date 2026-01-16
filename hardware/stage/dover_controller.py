"""
Dover Stage Controller

Uses Dover Motion MotionSynergy API via Python.NET.
All internal operations use nanometers (nm).
"""

import ctypes
import os
import sys
import threading
import time
from typing import Any, Callable

import clr

from config import DOVER_CONFIG, THREADING_CONFIG

from .utils import validate_position_limit

# Thread-safe lock for all .NET API calls
# Serializes access to prevent COM threading conflicts after PyQt loads
_net_api_lock = threading.Lock()

# Module-level globals (initialized by initialize_motion_synergy_api)
_motion_synergy_api: Any = None
_axis_list: list[Any] = []
_axis_names: list[str] = []
_axis_dict: dict[str, Any] = {}


def _safe_net_call(
    func: Callable[[], Any], operation_name: str, axis_name: str = ""
) -> Any | None:
    """Thread-safe wrapper for .NET API calls to prevent COM threading conflicts."""
    with _net_api_lock:
        try:
            return func()
        except Exception as e:
            axis_msg = f" for {axis_name} axis" if axis_name else ""
            print(f"{operation_name} failed{axis_msg}: {type(e).__name__}: {e}")
            import traceback

            traceback.print_exc()
            return None


def initialize_motion_synergy_api() -> None:
    """Initialize MotionSynergyAPI before any PyQt/matplotlib imports."""
    global _motion_synergy_api, _axis_list, _axis_names, _axis_dict

    if _motion_synergy_api is not None:
        return  # Already initialized

    dll_path = os.path.join(DOVER_CONFIG["dover_root"], "MotionSynergyAPI.dll")
    if not os.path.isfile(dll_path):
        raise RuntimeError(f"ERROR: MotionSynergyAPI.dll not found at {dll_path}")

    dover_root = DOVER_CONFIG["dover_root"]

    # Set DLL directory for .NET runtime native DLL loading
    ctypes.windll.kernel32.SetDllDirectoryW(dover_root)

    if dover_root not in sys.path:
        sys.path.insert(0, dover_root)
    if DOVER_CONFIG["python_modules_dir"] not in sys.path:
        sys.path.insert(0, DOVER_CONFIG["python_modules_dir"])

    os.chdir(dover_root)

    clr.AddReference("MotionSynergyAPI")  # type: ignore[attr-defined]
    from MotionSynergyAPI import (  # type: ignore[import-untyped]
        InstrumentSettings,
        MotionSynergyAPINative,
    )

    _motion_synergy_api = MotionSynergyAPINative()

    instrumentSettings = InstrumentSettings()
    instrumentSettings.ApplicationVersionString = DOVER_CONFIG["application_version"]
    instrumentSettings.SupportFolder = DOVER_CONFIG["support_folder"]
    instrumentSettings.ProgramDataFolder = DOVER_CONFIG["program_data_folder"]
    instrumentSettings.ConfigurationFilename = DOVER_CONFIG["config_filename"]

    if not os.path.isfile(
        os.path.join(
            instrumentSettings.SupportFolder, instrumentSettings.ConfigurationFilename
        )
    ):
        raise RuntimeError(
            "The MotionSynergyGUI application must be run to select your product and communications settings."
        )

    result = _motion_synergy_api.Configure(instrumentSettings).Result
    if not result.Success:
        raise RuntimeError(f"Configuration failed: {result}")

    result = _motion_synergy_api.Initialize().Result
    if not result.Success:
        raise RuntimeError(f"Initialization failed: {result}")

    # Cache axis data BEFORE PyQt loads to avoid COM threading issues
    # Extract axis information into Python native types while we can still access the API
    _axis_list = list(_motion_synergy_api.AxisList)
    _axis_names = [ax.Name for ax in _axis_list]
    _axis_dict = {ax.Name.upper(): ax for ax in _axis_list}


def shutdown_motion_synergy_api():
    """Shutdown the shared MotionSynergyAPI instance."""
    if _motion_synergy_api is not None:
        _motion_synergy_api.Shutdown()


class DoverController:
    """Dover stage controller matching PDXC2Controller/XeryonController interface."""

    @classmethod
    def is_connected(cls, serial: str = "") -> bool:
        """Check if device is connected."""
        # Use cached axis list to avoid COM threading issues after PyQt loads
        return len(_axis_list) > 0

    def __init__(self, serial: str = "", home: bool = False, axis: str = "X") -> None:
        """Initialize the Dover controller."""
        self.serial = serial
        # Auto-detect axis if only one is available
        if len(_axis_names) == 1:
            self.axis = _axis_names[0].upper()
        else:
            self.axis = axis.upper()
        self.position = 0
        self._stop_timer = False

        # Use cached axis dictionary to avoid COM threading issues after PyQt loads
        axis_obj = _axis_dict.get(self.axis)
        if axis_obj is None:
            raise ValueError(f"Axis '{self.axis}' not found. Available: {_axis_names}")
        self.axis_obj: Any = axis_obj

        if home:
            self.home()

        def monitor_position():
            while not self._stop_timer:
                pos = self.get_position()
                if pos is not None:
                    self.position = pos
                time.sleep(THREADING_CONFIG["position_monitor_interval"])

        threading.Thread(target=monitor_position, daemon=True).start()
        print(f"{self.axis} axis: Connected to DoverController")

    def get_position(self) -> int | None:
        """Get the current position in nanometers."""

        def _get_pos():
            # GetActualPosition() returns InstrumentResult[Double] directly, not a Task
            result = self.axis_obj.GetActualPosition()
            return int(result.Value * 1e6) if result.Success else None

        return _safe_net_call(_get_pos, "GetActualPosition", self.axis)

    def get_desired_position(self) -> int | None:
        """Get the commanded position in nanometers."""
        return _safe_net_call(
            lambda: (lambda r: int(r.Value * 1e6) if r.Success else None)(
                self.axis_obj.GetCommandedPosition()
            ),
            "GetCommandedPosition",
            self.axis,
        )

    def move(
        self,
        target: float,
        tolerance: int | None = None,
        wait_for_settled: bool = False,
    ) -> None:
        """Move to target position in nanometers.

        Args:
            target: Target position in nanometers
            tolerance: Tolerance in nanometers (used when wait_for_settled=True, defaults to DOVER_CONFIG["settling"]["settling_tolerance"])
            wait_for_settled: If True, wait until position is settled before returning
        """
        is_valid, error_msg = validate_position_limit(self.axis, target)
        if not is_valid:
            print(error_msg)
            return

        def _move():
            return self.axis_obj.MoveAbsolute(target / 1e6).Result

        result = _safe_net_call(_move, "MoveAbsolute", self.axis)
        if result is None:
            print(f"Move failed for {self.axis} axis: .NET call failed")
            return
        if not result.Success:
            print(f"Move failed for {self.axis} axis: {result}")
            return

        if wait_for_settled:
            self._wait_until_settled(
                target=target,
                poll_interval=DOVER_CONFIG["settling"]["poll_interval"],
                duration=DOVER_CONFIG["settling"]["duration"],
                settling_tolerance=DOVER_CONFIG["settling"]["settling_tolerance"],
                timeout=DOVER_CONFIG["settling"]["timeout"],
            )

    def stop(self) -> None:
        """Stop movement."""

        def _stop():
            return self.axis_obj.Stop().Result

        result = _safe_net_call(_stop, "Stop", self.axis)
        if result is None:
            print(f"Stop failed for {self.axis} axis: .NET call failed")
            return
        if not result.Success:
            print(f"Stop failed for {self.axis} axis: {result}")

    def home(self) -> None:
        """Find reference/index position and move to reference position."""

        def _home():
            return self.axis_obj.ResetPosition(0.0).Result

        result = _safe_net_call(_home, "ResetPosition", self.axis)
        if result is None:
            raise RuntimeError(f"Homing failed for {self.axis} axis: .NET call failed")
        if not result.Success:
            raise RuntimeError(f"Homing failed for {self.axis} axis: {result}")
        print(f"Reference finding finished for {self.axis} axis.")

        # Move to reference position after finding index
        reference_pos = DOVER_CONFIG.get("reference_position", {})
        if "ZAXIS" in reference_pos:
            self.move(reference_pos["ZAXIS"])

    def _wait_until_settled(
        self,
        target: float,
        poll_interval: float,
        duration: float,
        settling_tolerance: float,
        timeout: float,
    ) -> bool:
        """
        Wait until axis position fluctuation stays within tolerance for the prescribed duration.

        Args:
            target: Target position in nanometers (passed from move() to avoid stale cached data)
            poll_interval: Polling interval in seconds
            duration: Required duration of stability (seconds)
            settling_tolerance: Maximum allowed position range (nm)
            timeout: Maximum time to wait (seconds)

        Returns:
            bool: True if position fluctuation stayed within tolerance for full duration, False if timeout
        """
        # Use settling_tolerance as the position tolerance check (similar to PTOL in Xeryon)
        position_tolerance = settling_tolerance  # nm

        num_samples = int(duration / poll_interval)
        positions = []
        start_time = time.monotonic()

        while (
            len(positions) < num_samples
            or max(positions[-num_samples:]) - min(positions[-num_samples:])
            > settling_tolerance
        ):
            # Check timeout
            if time.monotonic() - start_time >= timeout:
                actual = self.get_position()
                current = actual if actual is not None else 0
                range_val = max(positions) - min(positions) if positions else 0
                distance_from_target = (
                    abs(current - target)
                    if target is not None and actual is not None
                    else float("inf")
                )
                print(
                    f"WARNING: wait_until_settled timed out after {timeout:.2f}s. "
                    f"Current: {current:.6f}, Target: {target:.6f}, "
                    f"Distance from target: {distance_from_target:.6f}, "
                    f"Range: {range_val:.6f}, Tolerance: {settling_tolerance:.6f}"
                )
                return False

            actual = self.get_position()

            # Only add position if it's within position_tolerance of target
            if (
                target is not None
                and actual is not None
                and abs(actual - target) <= position_tolerance
            ):
                positions.append(actual)

                # Keep only last num_samples to avoid memory growth
                if len(positions) > num_samples:
                    positions = positions[-num_samples:]

                # Check if range of last num_samples is within tolerance
                if len(positions) == num_samples:
                    if max(positions) - min(positions) <= settling_tolerance:
                        return True
            else:
                # Reset positions if we're not within position_tolerance of target
                positions = []

            time.sleep(poll_interval)

        return False

    def close(self) -> None:
        """Close the connection to the device."""
        self._stop_timer = True
