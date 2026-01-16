import torch

# Set device to GPU if available, otherwise CPU
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def pad_matrix_width(matrix_tensor: torch.Tensor, width_increase: int) -> torch.Tensor:
    # Pre-allocate the full output tensor
    output_shape = (
        matrix_tensor.shape[0],
        matrix_tensor.shape[1] + width_increase,
        matrix_tensor.shape[2],
    )
    expanded_tensor = torch.zeros(output_shape, dtype=torch.float16, device=device)

    # Fill the right part with the input matrix (more efficient than cat)
    expanded_tensor[:, width_increase:, :] = matrix_tensor

    return expanded_tensor


def matrix_3D_to_vector_list_and_filter(matrix_tensor: torch.Tensor) -> torch.Tensor:
    # Create view with permuted dimensions (view, no memory allocated)
    reshaped = matrix_tensor.permute(2, 0, 1).reshape(matrix_tensor.shape[2], -1)
    del matrix_tensor  # Free original tensor since we only need the view

    # Pre-allocate final tensor with space for data and zero column
    result = torch.zeros(
        (reshaped.shape[0], reshaped.shape[1]), dtype=torch.float16, device=device
    )
    # Copy data excluding first 3 entries directly (no intermediate tensors)
    result[:, :-1] = reshaped[:, 1:]  # FOR PS2 NO SYNCING SO Only 1 pixel offset
    del reshaped  # Free the view immediately

    # Find non-zero vectors efficiently
    nonzero_mask = torch.any(result != 0, dim=1)

    # Filter out zero vectors (creates new tensor, but we need it for return)
    filtered_vectors = result[nonzero_mask]
    del result  # Free intermediate result
    del nonzero_mask  # Free mask tensor

    torch.cuda.empty_cache()  # Clear any unused memory in GPU cache

    return filtered_vectors


def generate_Z_signal_vectors(
    num_vectors: int, vector_length: int, step_value: float
) -> torch.Tensor:
    # Create and reshape in one operation
    vectors = torch.zeros(
        (num_vectors, vector_length), dtype=torch.float64, device=device
    )

    # Fill with values in-place
    arange_tensor = torch.arange(num_vectors, dtype=torch.float64, device=device)
    vectors[:, 0] = arange_tensor * step_value
    del arange_tensor  # Free temporary tensor

    # Broadcast the first column to all other columns (in-place)
    vectors[:, 1:] = vectors[:, :1]  # This is a view operation

    torch.cuda.empty_cache()  # Clear any unused memory in GPU cache
    return vectors
