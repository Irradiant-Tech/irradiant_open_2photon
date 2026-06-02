import torch

from utils.dtypes import ProcessingDataTypes

# Set device to GPU if available, otherwise CPU
device_torch = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def pad_matrix_width(matrix_tensor: torch.Tensor, width_increase: int) -> torch.Tensor:
    # Pre-allocate the full output tensor
    output_shape = (
        matrix_tensor.shape[0],
        matrix_tensor.shape[1] + width_increase,
        matrix_tensor.shape[2],
    )
    expanded_tensor = torch.zeros(
        output_shape, dtype=ProcessingDataTypes.torch_dtype, device=device_torch
    )

    # Fill the right part with the input matrix (more efficient than cat)
    expanded_tensor[:, width_increase:, :] = matrix_tensor

    return expanded_tensor


def matrix_3D_to_vector_list_and_filter(
    matrix_tensor: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    # Create view with permuted dimensions (view, no memory allocated)
    reshaped = matrix_tensor.permute(2, 0, 1).reshape(matrix_tensor.shape[2], -1)
    del matrix_tensor  # Free original tensor since we only need the view

    # Find non-zero vectors efficiently
    nonzero_mask = torch.any(reshaped != 0, dim=1)

    # Capture original z-indices of surviving frames before discarding the mask
    z_indices = torch.nonzero(nonzero_mask, as_tuple=False).flatten()

    # Filter out zero vectors (creates new tensor, but we need it for return)
    filtered_vectors = reshaped[nonzero_mask]
    del reshaped  # Free intermediate tensor
    del nonzero_mask  # Free mask tensor

    torch.cuda.empty_cache()  # Clear any unused memory in GPU cache

    return filtered_vectors, z_indices
