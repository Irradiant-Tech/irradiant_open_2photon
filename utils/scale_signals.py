from typing import List

import numpy as np
from numpy.typing import DTypeLike


def scale_signals(
    signals: List[np.ndarray],
    amplitudes: List[float],
    dtype: DTypeLike | None = None,
    clip: bool = False,
) -> List[np.ndarray]:
    """
    Scale multiple signals by an amplitude.
    Optionally clip to [-clipped_signal_min, +clipped_signal_max].

    Args: - signals: list of signals
          - amplitudes: list of amplitudes to scale each signal
          - dtype: Optional output data type of signals. If None, the input signal dtype is preserved.
          - clip: True for clipping, False otherwise. Clips to +/- amplitude.

    Output: List of scaled signals in the specified dtype.
    """
    if len(signals) != len(amplitudes):
        raise ValueError("Number of signals must match number of amplitudes.")

    signals_out = []

    for i, signal in enumerate(signals):
        dtype_out = signal.dtype if dtype is None else dtype
        # Promote the calculation dtype before scaling specifically for fp16 -> int16 conversion.
        # fp16 cannot represent INT16_MAX (32767) and rounds it to 32768, which overflows to
        # -32768 when cast to int16.
        working_dtype = np.result_type(signal.dtype, dtype_out)

        scaled = np.multiply(signal, amplitudes[i], dtype=working_dtype)
        if clip:
            np.clip(scaled, -amplitudes[i], amplitudes[i], out=scaled)
        signals_out.append(scaled.astype(dtype_out, copy=False))

    return signals_out
