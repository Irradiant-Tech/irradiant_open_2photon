from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from hardware.voltage_device.daq import (
    execute_analog_output_daq,
    hardware_constraints_daq,
    is_daq_connected,
    output_constant_voltage_daq,
)
from utils.stop_flag import StopFlag


@dataclass(frozen=True)
class AnalogDevice:
    execute_analog_output: Callable[
        [float, np.ndarray, np.ndarray, np.ndarray, np.ndarray, StopFlag, list[float]],
        bool,
    ]
    get_hardware_constraints: Callable[[], tuple[float, float]]
    output_constant_voltage: Callable[
        [str | List[str], float | List[float], StopFlag], None
    ]
    is_connected: Callable[[], bool]


VOLTAGE_DEVICES: dict[str, AnalogDevice] = {
    "DAQ": AnalogDevice(
        execute_analog_output=execute_analog_output_daq,
        get_hardware_constraints=hardware_constraints_daq,
        output_constant_voltage=output_constant_voltage_daq,
        is_connected=is_daq_connected,
    ),
}


def get_voltage_device() -> tuple[Optional[AnalogDevice], Optional[str]]:
    """
    Return the AnalogDevice object and name of the first connected voltage device.
    Returns None if no devices are connected.
    """
    for name, device in VOLTAGE_DEVICES.items():
        if device.is_connected():
            print(f"Using {name} for voltage output.")
            return device, name

    print("No voltage device connected.")
    return None, None
