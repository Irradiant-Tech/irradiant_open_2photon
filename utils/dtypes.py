import numpy as np
import torch

from config import PROCESSING_DTYPE_STR


def get_fp_torch_dtype(dtype_str: str) -> torch.dtype:
    """
    Validate and convert a dtype string into the corresponding PyTorch dtype for processing.
    Must be a floating point dtype.
    """
    torch_dtype = getattr(torch, dtype_str, None)
    if not isinstance(torch_dtype, torch.dtype):
        raise ValueError(f"Invalid torch dtype string: {dtype_str}")

    if not torch_dtype.is_floating_point:
        raise ValueError(f"{dtype_str} is not a floating torch dtype.")

    return torch_dtype


def get_fp_numpy_dtype(dtype_str: str) -> np.dtype:
    """
    Validate and convert a dtype string into the corresponding numpy dtype for processing.
    Must be a floating point dtype.
    """
    try:
        np_dtype = np.dtype(dtype_str)
    except TypeError:
        raise ValueError(f"Invalid numpy dtype string: {dtype_str}")

    if not np.issubdtype(np_dtype, np.floating):
        raise ValueError(f"{dtype_str} is not a floating numpy dtype.")

    return np_dtype


class ProcessingDataTypes:
    torch_dtype: torch.dtype = get_fp_torch_dtype(PROCESSING_DTYPE_STR)
    numpy_dtype: np.dtype = get_fp_numpy_dtype(PROCESSING_DTYPE_STR)

    @classmethod
    def cast_numpy(cls, x) -> np.ndarray:
        return np.asarray(x, dtype=cls.numpy_dtype)

    @classmethod
    def cast_torch(cls, x) -> torch.Tensor:
        return torch.as_tensor(x, dtype=cls.torch_dtype)
