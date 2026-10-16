from typing import List, Tuple

from config import CHANNELS


def normalize_and_validate_channels(
    channel: str | List[str],
    voltage: float | List[float],
) -> Tuple[List[str], List[float | int]]:
    """
    Normalize and validate channel and voltage inputs.

    Args:
    - channel: Channel name or list of channel names.
    - voltage: Voltage or list of voltages corresponding to channels

    Returns:
    - Tuple of (list of channel names, list of voltages)
    """
    channel_names = [channel] if isinstance(channel, str) else list(channel)
    voltages = [voltage] if isinstance(voltage, (int, float)) else list(voltage)

    if len(channel_names) != len(voltages):
        raise ValueError("Inputs channel and voltage must be the same length.")

    if len(set(channel_names)) != len(channel_names):
        raise ValueError("All channels must be unique.")

    for ch in channel_names:
        if ch not in CHANNELS:
            raise ValueError(f"Invalid channel: {ch}")

    return channel_names, voltages
