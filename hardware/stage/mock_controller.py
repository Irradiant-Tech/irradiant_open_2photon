"""
Mock Stage Controller

A mock controller for testing when no physical stage is connected.
All position updates return 0 and movement commands do nothing.
"""


class MockController:
    """Mock controller for testing on the manual stage."""

    def __init__(self, serial: str = "", home: bool = False, axis: str = "X") -> None:
        self.serial = serial
        self.position = 0
        self.axis = axis
        self._last_desired_position = None
        print(f"{axis} axis: Using MockController (device not connected)")

    def get_position(self) -> int:
        return 0

    def get_desired_position(self) -> int:
        return 0

    def move(
        self,
        target: float,
        tolerance: int = 10000,
        wait_for_settled: bool = False,
    ) -> None:
        """Move to target position (no-op for mock controller).

        Args:
            target: Target position in nanometers
            tolerance: Tolerance in nanometers (ignored)
            wait_for_settled: Ignored (mock controller does nothing)
        """
        self._last_desired_position = target

    def stop(self) -> None:
        pass

    def home(self) -> None:
        pass

    def close(self) -> None:
        pass
