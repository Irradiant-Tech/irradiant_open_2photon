import torch


def matrix_3D_to_vector_list_and_filter(
    matrix_box: list, width_increase: int
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Filter and pad matrix, then convert matrix to flattened list.
    The input tensor's dtype is preserved throughout processing.

    Args:
        - matrix_box (list): Single-element list holding the 3D tensor.
        - width_increase (int): The number of columns of zeros to add to the left.

    Returns:
        - result (torch.Tensor): Non-zero flattened and padded aom frame vectors.
        - z_indices (torch.Tensor): Indices of non-blank z-frames.
    """
    matrix_tensor = matrix_box.pop()
    torch_dtype = matrix_tensor.dtype

    # Filter out empty z-layers, preserving original z-indices
    nonzero_mask = torch.any(matrix_tensor != 0, dim=(0, 1))
    z_indices = torch.nonzero(nonzero_mask, as_tuple=False).flatten()
    if z_indices.numel() == 0:
        return torch.empty((0, 0), dtype=torch_dtype), z_indices
    filtered = matrix_tensor[:, :, nonzero_mask]
    del matrix_tensor, nonzero_mask
    matrix_tensor = filtered

    # Pad surviving layers filling the right part with the input matrix
    output_shape = (
        matrix_tensor.shape[0] + width_increase,
        matrix_tensor.shape[1],
        matrix_tensor.shape[2],
    )
    expanded_tensor = torch.zeros(output_shape, dtype=torch_dtype)
    expanded_tensor[width_increase:, :, :] = matrix_tensor
    del matrix_tensor

    # Flatten the tensor and return
    result = expanded_tensor.permute(2, 1, 0).reshape(expanded_tensor.shape[2], -1)
    return result, z_indices
