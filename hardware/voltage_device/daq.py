import time
from typing import List

import nidaqmx
import nidaqmx.system
import numpy as np
from nidaqmx.constants import AcquisitionType
from nidaqmx.system.device import Device

from config import CHANNEL_ORDER, CHANNELS, DAQ_DEVICE, DTYPE_DAQ, TIMING
from utils.channel_validation import normalize_and_validate_channels
from utils.scale_signals import scale_signals
from utils.stop_flag import StopFlag


def is_daq_connected() -> bool:
    try:
        devices = [device.name for device in nidaqmx.system.System.local().devices]
        return DAQ_DEVICE in devices
    except Exception as e:
        print(f"DAQ connection failed: {e}")
        return False


def hardware_constraints_daq() -> tuple[float, float]:
    """
    Returns DAQ hardware limits: (max_sample_rate_hz, max_samples_per_channel)
        - max_sample_rate_hz: maximum sample clock rate supported by the DAQ
        - max_samples_per_channel: maximum number of sample values that can fit in DAQ onboard memory per channel
    """
    try:
        # Convert total rate shared across all AO channels to sample rate per channel
        device = nidaqmx.system.System.local().devices[DAQ_DEVICE]
        if not isinstance(device, Device):
            raise TypeError(f"Expected Device, got {type(device).__name__}")
        max_sample_rate_hz = device.ao_max_rate / len(CHANNELS)

        # DAQ AO supports continuous streaming, so there is no fixed maxmimum samples per buffer.
        return max_sample_rate_hz, np.inf
    except Exception as e:
        raise Exception(f"Failed to get DAQ hardware constraints: {e}")


def execute_analog_output_daq(
    sample_rate_hz: float,
    channel_0_x_galvo: np.ndarray,
    channel_1_y_galvo: np.ndarray,
    channel_2_aom: np.ndarray,
    channel_3_z_piezo: np.ndarray,
    stop_flag: StopFlag,
    channel_amplitudes: list[float],
) -> bool:
    """
    Outputs synchronized analog voltages to four DAQ channels at a given frequency.

    Channels:
        channel_0_x_galvo: X-galvo scan signal (fast axis)
        channel_1_y_galvo: Y-galvo scan signal (slow axis)
        channel_2_aom: AOM signal (laser intensity)
        channel_3_z_piezo: Z-piezo signal

    channel_amplitudes: [x_galvo, y_galvo, aom, z_piezo] voltage amplitude (V) per channel.
    All buffers must be equal length and scaled to their voltage ranges.
    Returns True if all samples are written successfully, False if stopped or failed.
    """
    num_samples = len(channel_0_x_galvo)

    scaled_channels = scale_signals(
        signals=[
            channel_0_x_galvo,
            channel_1_y_galvo,
            channel_2_aom,
            channel_3_z_piezo,
        ],
        amplitudes=channel_amplitudes,
        dtype=DTYPE_DAQ,
        clip=True,
    )

    output_array = np.vstack(scaled_channels)
    ao_channels = [CHANNELS[ch]["DAQ"] for ch in CHANNEL_ORDER]
    try:
        with nidaqmx.Task() as task:
            for channel in ao_channels:
                task.ao_channels.add_ao_voltage_chan(channel)

            task.timing.cfg_samp_clk_timing(
                sample_rate_hz,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=num_samples,
            )

            task.write(output_array, auto_start=False)  # type: ignore
            task.start()

            timeout = num_samples / sample_rate_hz
            check_interval = TIMING["check_interval"]
            elapsed_time = 0

            while elapsed_time < timeout:
                if stop_flag.stop:
                    task.stop()
                    return False
                time.sleep(check_interval)
                elapsed_time += check_interval

            task.wait_until_done(timeout=timeout * TIMING["timeout_multiplier"])
            task.stop()

            return True
    except Exception as e:
        raise Exception(f"DAQ output failed: {e}")
    finally:
        try:
            # Zero all channels
            with nidaqmx.Task() as task:
                for channel in ao_channels:
                    task.ao_channels.add_ao_voltage_chan(channel)
                task.write(np.zeros((4, 1), dtype=DTYPE_DAQ), auto_start=True)  # type: ignore
        except Exception as cleanup_error:
            print(f"Failed to reset DAQ channels to 0V: {cleanup_error}")


def output_constant_voltage_daq(
    channel: str | List[str],
    voltage: float | List[float],
    stop_flag: StopFlag,
) -> None:
    """
    Output a constant DC voltage on a single channel using the DAQ.
    Resets channel to 0V when output is stopped.

    Args:
        - channel: DAQ channel (x_galvo, y_galvo, aom, or z_piezo) or list of channel names.
        - voltage: Voltage or list of voltages corresponding to channels
        - stop_flag: stop_flag.stop = True to stop output.
    """
    channel_names, voltages = normalize_and_validate_channels(channel, voltage)

    try:
        with nidaqmx.Task() as task:
            # Start output
            for ch in channel_names:
                task.ao_channels.add_ao_voltage_chan(CHANNELS[ch]["DAQ"])
            task.write(voltages)
            task.start()

            for ch, v in zip(channel_names, voltages):
                print(f"DAQ outputting {v} V continuously on {ch}")

            check_interval = TIMING["check_interval"]
            while not stop_flag.stop:
                time.sleep(check_interval)
    except Exception as e:
        raise Exception(f"DAQ constant voltage output failed: {e}")
    finally:
        try:
            # Reset channel to 0V
            with nidaqmx.Task() as task:
                for ch in channel_names:
                    task.ao_channels.add_ao_voltage_chan(CHANNELS[ch]["DAQ"])
                task.write([0.0] * len(channel_names))
            print(
                f"DAQ stopped output on the following channels: {', '.join(channel_names)}."
            )
        except Exception as cleanup_error:
            print(f"Failed to reset DAQ channels to 0V: {cleanup_error}")
