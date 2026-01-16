"""
Xeryon Stage Controller

Wrapper around xeryon_library to match other stage controllers interfaces.
All internal operations use nanometers (nm).
"""

import threading
import time
from typing import Type

from config import THREADING_CONFIG, XERYON_CONFIG

from ..utils import validate_position_limit
from .xeryon_library import Stage, Units, Xeryon

# Module-level dictionary to share Xeryon controllers per COM port
_xeryon_controllers = {}
_controller_lock = threading.Lock()
_pending_home_axes = {}


def _find_xeryon_com_port() -> str | None:
    """Scan all COM ports and find Xeryon device by hardware ID."""
    try:
        import serial.tools.list_ports

        ports = list(serial.tools.list_ports.comports())
        hardware_id = XERYON_CONFIG.get("hardware_id", "04D8")
        for port in ports:
            if hardware_id in str(port.hwid):
                return str(port.device)
    except Exception:
        pass
    return None


def _get_com_port(serial: str) -> str:
    """Extract COM port from serial string or auto-detect Xeryon by scanning all COM ports."""
    if serial and serial.startswith("COM"):
        return serial

    # Scan all COM ports
    found_port = _find_xeryon_com_port()
    return found_port if found_port else ""


def _get_xeryon_controller(com_port, baudrate):
    """Get or create shared Xeryon controller for a COM port."""
    with _controller_lock:
        if com_port not in _xeryon_controllers:
            controller = Xeryon(com_port, baudrate)
            _xeryon_controllers[com_port] = controller
        return _xeryon_controllers[com_port]


class XeryonController:
    """Xeryon stage controller matching PDXC2Controller interface."""

    @classmethod
    def is_connected(cls: Type["XeryonController"], serial: str = "") -> bool:
        """Check if device is connected."""
        try:
            import serial as serial_lib

            com_port = _get_com_port(serial)
            if not com_port:
                return False

            ser = serial_lib.Serial(
                com_port,
                XERYON_CONFIG["baudrate"],
                timeout=XERYON_CONFIG["serial_timeout_connect"],
            )
            ser.close()
            return True
        except Exception:
            return False

    def __init__(self, serial: str = "", home: bool = False, axis: str = "X") -> None:
        """Initialize the Xeryon controller."""
        self.serial = serial
        self.axis = axis.upper()
        self.position = 0
        self._position_timer = None
        self._stop_timer = False
        self._last_desired_position = None

        # Use provided serial or fall back to config
        com_port = _get_com_port(serial)
        if not com_port:
            raise ValueError(
                f"COM port must be specified for {self.axis} axis (e.g., 'COM4') or set in XERYON_CONFIG"
            )

        # Get or create shared Xeryon controller for this COM port
        self.xeryon = _get_xeryon_controller(com_port, XERYON_CONFIG["baudrate"])

        # Determine stage type based on axis
        if self.axis == "Z":
            stage_type = Stage.XVP_80_5
        else:  # X or Y
            stage_type = Stage.XLS_3_120_5

        # Check if axis already exists, otherwise add it
        with _controller_lock:
            self.axis_obj = self.xeryon.getAxis(self.axis)
            is_new_axis = self.axis_obj is None
            if is_new_axis:
                self.axis_obj = self.xeryon.addAxis(stage_type, self.axis)
                # Set units to nanometers
                self.axis_obj.setUnits(Units.nm)

            # Start controller after all axes are added
            all_axes = self.xeryon.getAllAxis()
            axis_letters = [ax.getLetter() for ax in all_axes]
            has_all_axes = (
                "X" in axis_letters and "Y" in axis_letters and "Z" in axis_letters
            )

            # Start if we have all three axes and haven't started yet
            if has_all_axes and len(all_axes) == 3:
                if not hasattr(self.xeryon, "_started"):
                    self.xeryon.start()
                    self.xeryon._started = True

                    # Perform reference finding for all axes in order: Z first, then X and Y
                    pending_copy = dict(_pending_home_axes)
                    reference_finding_order = ["Z", "X", "Y"]
                    for axis_letter in reference_finding_order:
                        if axis_letter in pending_copy:
                            controller_instance = pending_copy[axis_letter]
                            if controller_instance.xeryon == self.xeryon:
                                try:
                                    controller_instance.home()
                                except Exception as e:
                                    print(
                                        f"Error finding reference for {axis_letter} axis: {e}"
                                    )
                                # Remove from pending
                                _pending_home_axes.pop(axis_letter, None)

        # Find reference if requested
        if home:
            # If controller is already started, find reference immediately
            if hasattr(self.xeryon, "_started") and self.xeryon._started:
                self.home()
            else:
                # Otherwise, defer reference finding until controller is started
                _pending_home_axes[self.axis] = self

        # Start position monitoring thread
        self._stop_timer = False

        def monitor_position():
            while not self._stop_timer:
                # Request position update from device
                self.axis_obj.sendCommand("EPOS=?")
                position = self.get_position()
                if position is not None:
                    self.position = position
                time.sleep(THREADING_CONFIG["position_monitor_interval"])

        self._position_timer = threading.Thread(target=monitor_position, daemon=True)
        self._position_timer.start()

        print(f"{self.axis} axis: Connected to XeryonController")

    def get_position(self) -> int:
        """Get the current position in nanometers."""
        epos_nm = self.axis_obj.getEPOS()
        return int(epos_nm)

    def get_desired_position(self) -> int:
        """Get the last desired position in nanometers."""
        if self._last_desired_position is not None:
            return int(self._last_desired_position)
        # Fallback to current position if no desired position has been set
        return self.get_position()

    def move(
        self,
        target: float,
        tolerance: int | None = None,
        wait_for_settled: bool = False,
    ) -> None:
        """Move to target position in nanometers.

        Args:
            target: Target position in nanometers
            tolerance: Tolerance in nanometers (used when wait_for_settled=True, defaults to XERYON_CONFIG["settling"]["settling_tolerance"])
            wait_for_settled: If True, wait until position is settled before returning
        """
        # Check per-axis limits
        is_valid, error_msg = validate_position_limit(self.axis, target)
        if not is_valid:
            print(error_msg)
            return

        self._last_desired_position = target
        self.axis_obj.setDPOS(target, outputToConsole=False, forceWaiting=True)

        if wait_for_settled:
            self.wait_until_settled(
                target=target,
                poll_interval=XERYON_CONFIG["settling"]["poll_interval"],
                duration=XERYON_CONFIG["settling"]["duration"],
                settling_tolerance=XERYON_CONFIG["settling"]["settling_tolerance"],
                timeout=XERYON_CONFIG["settling"]["timeout"],
            )

    def wait_until_settled(
        self, target, poll_interval, duration, settling_tolerance, timeout
    ):
        """
        Wait until axis position fluctuation stays within tolerance for the prescribed duration.

        Args:
            target: Target position in nanometers (passed from move() to avoid stale cached data)
            poll_interval: Polling interval in seconds
            duration: Required duration of stability (seconds)
            settling_tolerance: Maximum allowed position range (in axis current units)
            timeout: Maximum time to wait (seconds)

        Returns:
            bool: True if position fluctuation stayed within tolerance for full duration, False if timeout
        """

        # Get PTOL setting for this axis (in encoder units) and convert to nanometers
        ptol_setting = self.axis_obj.getSetting("PTOL")
        ptol_encoder_units = int(ptol_setting) if ptol_setting is not None else 30

        # Convert from encoder units to nanometers
        encoder_resolution = (
            self.axis_obj.stage.encoderResolution
        )  # nm per encoder count
        ptol = (
            ptol_encoder_units * encoder_resolution
        )  # e.g., 30 encoder units * 5 nm = 150 nm

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
                current = self.axis_obj.getEPOS()
                range_val = max(positions) - min(positions) if positions else 0
                distance_from_target = (
                    abs(current - target) if target is not None else float("inf")
                )
                print(
                    f"WARNING: wait_until_settled timed out after {timeout:.2f}s. "
                    f"Current: {current:.6f}, Target: {target:.6f}, "
                    f"Distance from target: {distance_from_target:.6f}, PTOL: {ptol:.6f}, "
                    f"Range: {range_val:.6f}, Tolerance: {settling_tolerance:.6f}"
                )
                return False

            current_pos = self.axis_obj.getEPOS()

            # Only add position if it's within PTOL of target
            if target is not None and abs(current_pos - target) <= ptol:
                positions.append(current_pos)

                # Keep only last num_samples to avoid memory growth
                if len(positions) > num_samples:
                    positions = positions[-num_samples:]

                # Check if range of last num_samples is within tolerance
                if len(positions) == num_samples:
                    if max(positions) - min(positions) <= settling_tolerance:
                        return True
            else:
                # Reset positions if we're not within PTOL of target
                positions = []

            time.sleep(poll_interval)

        return False

    def stop(self) -> None:
        """Stop movement."""
        self.axis_obj.sendCommand("STOP=0")

    def home(self) -> None:
        """Find reference/index position and move to reference position."""
        # Find index with retries
        max_retries = 3
        index_found = False

        for attempt in range(max_retries + 1):
            index_found = self.axis_obj.findIndex(forceWaiting=True)
            if index_found:
                break
            if attempt < max_retries:
                print(
                    f"Index not found for {self.axis} axis, retrying ({attempt + 1}/{max_retries})..."
                )

        if not index_found:
            error_msg = (
                f"Index not found for {self.axis} axis after {max_retries + 1} attempts"
            )
            print(f"Warning: {error_msg}")
            raise RuntimeError(error_msg)

        # Move to reference position after finding index
        reference_pos = XERYON_CONFIG.get("reference_position", {})
        if self.axis in reference_pos:
            target_pos = reference_pos[self.axis]
            self._last_desired_position = target_pos
            self.axis_obj.setDPOS(target_pos, outputToConsole=False, forceWaiting=True)

    def close(self) -> None:
        """Close the connection to the device."""
        self._stop_timer = True
        if self._position_timer:
            self._position_timer.join(timeout=1.0)

        # Stop movement
        self.axis_obj.sendCommand("STOP=0")

        # Check if this is the last axis before closing
        with _controller_lock:
            remaining_axes = [
                ax for ax in self.xeryon.getAllAxis() if ax.getLetter() != self.axis
            ]

            if len(remaining_axes) == 0:
                self.xeryon.stop()
                _xeryon_controllers.pop(self.xeryon.comm.COM_port, None)
