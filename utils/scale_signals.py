from typing import List

import numpy as np


def scale_signals(
    signals: List[np.ndarray],
    amplitudes: List[float],
    dtype: type = np.float64,
    clip: bool = False,
) -> List[np.ndarray]:
    """
    Scale multiple signals by an amplitude.
    Optionally clip to [-clipped_signal_min, +clipped_signal_max].

    Args: - signals: list of signals
          - amplitudes: list of amplitudes to scale each signal
          - dtype: data type of signals
          - clip: True for clipping, False otherwise. Clips to +/- amplitude.

    Output: List of scaled signals in the specified dtype.
    """
    if len(signals) != len(amplitudes):
        raise ValueError("Number of signals must match number of amplitudes.")

    signals_out = []

    for i, signal in enumerate(signals):
        signal = signal.copy() * amplitudes[i]
        if clip:
            signal = np.clip(signal, -amplitudes[i], amplitudes[i])
        signals_out.append(signal.astype(dtype))

    return signals_out
