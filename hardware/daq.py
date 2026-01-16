import time

import nidaqmx
import nidaqmx.system
import numpy as np
from nidaqmx.constants import AcquisitionType

from config import (
    DAQ_CHANNEL_ORDER,
    DAQ_CHANNELS,
    DAQ_DEVICE,
    TIMING,
    VOLTAGE_AMPLITUDES,
)
from utils.scale_signals import scale_signals
from utils.stop_flag import StopFlag


def is_daq_connected():
    try:
        devices = [device.name for device in nidaqmx.system.System.local().devices]
        return DAQ_DEVICE in devices
    except Exception:
        return False


def execute_analog_output_daq(
    sample_rate_hz: float,
    channel_0_x_galvo: np.ndarray,
    channel_1_y_galvo: np.ndarray,
    channel_2_aom: np.ndarray,
    channel_3_z_piezo: np.ndarray,
    stop_flag: StopFlag,
) -> bool:
    """
    Outputs synchronized analog voltages to four DAQ channels at a given frequency.

    Channels:
        channel_0_x_galvo: X-galvo scan signal (fast axis)
        channel_1_y_galvo: Y-galvo scan signal (slow axis)
        channel_2_aom: AOM signal (laser intensity)
        channel_3_z_piezo: Z-piezo signal

    All buffers must be equal length and scaled to their voltage ranges.
    Returns True if all samples are written successfully, False if stopped or failed.
    """
    num_samples = len(channel_0_x_galvo)

    # Scale all channels to voltage ranges
    scaled_channels = scale_signals(
        signals=[
            channel_0_x_galvo,
            channel_1_y_galvo,
            channel_2_aom,
            channel_3_z_piezo,
        ],
        amplitudes=[VOLTAGE_AMPLITUDES[ch] for ch in DAQ_CHANNEL_ORDER],
        dtype=np.float64,
        clip=True,
    )

    output_array = np.vstack(scaled_channels)
    ao_channels = [DAQ_CHANNELS[ch] for ch in DAQ_CHANNEL_ORDER]
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
                task.write(np.zeros((4, 1)), auto_start=True)  # type: ignore
        except Exception as cleanup_error:
            print(f"Failed to reset DAQ channels to 0V: {cleanup_error}")


def output_constant_voltage_daq(
    channel: str,
    voltage: float,
    stop_flag: StopFlag,
) -> None:
    """
    Output a constant DC voltage on a single channel using the DAQ.
    Resets channel to 0V when output is stopped.

    Args:
        - voltage: The voltage to output.
        - channel: The DAQ channel (x_galvo, y_galvo, aom, or z_piezo).
        - stop_flag: stop_flag.stop = True to stop output.
    """
    if channel not in DAQ_CHANNELS:
        raise ValueError(f"Invalid channel: {channel}")

    try:
        with nidaqmx.Task() as task:
            # Start output and then release channel
            task.ao_channels.add_ao_voltage_chan(DAQ_CHANNELS[channel])
            task.write(voltage)
            task.start()

            check_interval = TIMING["check_interval"]
            while not stop_flag.stop:
                time.sleep(check_interval)
    except Exception as e:
        raise Exception(f"DAQ constant voltage output failed: {e}")
    finally:
        try:
            # Reset channel to 0V
            with nidaqmx.Task() as task:
                task.ao_channels.add_ao_voltage_chan(DAQ_CHANNELS[channel])
                task.write(0.0)
        except Exception as cleanup_error:
            print(f"Failed to reset DAQ channel {channel} to 0V: {cleanup_error}")
