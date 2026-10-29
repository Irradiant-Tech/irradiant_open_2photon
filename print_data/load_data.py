import zipfile

import numpy as np
import numpy.lib.format as npy_format

from config import LOAD_DTYPE_NUMPY, NPZ_MATRIX_KEY

# -----------------------------------------------------------------------------
# Full volume loading
# -----------------------------------------------------------------------------


def load_matrix_from_path(file_path: str) -> np.ndarray:
    """Load matrix from NumPy file (NPY or NPZ). Promotes 2D arrays to 3D (adds Z-axis of size 1)."""
    matrix = np.load(file_path)

    if file_path.lower().endswith(".npz"):  # Load full npz
        try:
            matrix = matrix[NPZ_MATRIX_KEY]
        except KeyError:
            raise KeyError(f"NPZ file {file_path} is missing the {NPZ_MATRIX_KEY} key.")

    return np.atleast_3d(matrix).astype(LOAD_DTYPE_NUMPY)


def generate_dense_matrix(
    matrix_x: int, matrix_y: int, matrix_z: int, value: float
) -> np.ndarray:
    """Generate dense matrix with given dimensions and value."""
    dense_value = max(0.0, min(1.0, value))  # Clamp to 0-1
    return (np.ones((matrix_x, matrix_y, matrix_z)) * dense_value).astype(
        LOAD_DTYPE_NUMPY
    )


# -----------------------------------------------------------------------------
# Peeking volume shape
# -----------------------------------------------------------------------------


def _read_npy_header_public(raw):
    """
    Read a .npy header using public NumPy APIs.
    Only format versions 1.0 and 2.0 have documented public header-reading functions:
    https://numpy.org/devdocs/reference/generated/numpy.lib.format.html.

    This loader only reads data.npy, which should contain a plain 3D numeric volume,
    so version 3.0 support for Unicode metadata is not required.
    """
    version = npy_format.read_magic(raw)
    read_header = {
        (1, 0): npy_format.read_array_header_1_0,
        (2, 0): npy_format.read_array_header_2_0,
    }
    if version not in read_header:
        raise ValueError(f"Unsupported .npy file format version: {version}")
    return read_header[version](raw)


def peek_volume_shape(path: str) -> tuple[int, int, int]:
    """3D shape without loading payload: ``.npy`` mmap; ``.npz`` reads ``{NPZ_MATRIX_KEY}.npy`` header only."""
    if path.lower().endswith(".npz"):
        with zipfile.ZipFile(path, "r") as zf:
            try:
                info = zf.getinfo(f"{NPZ_MATRIX_KEY}.npy")
            except KeyError as e:
                raise ValueError(
                    f"NPZ has no {NPZ_MATRIX_KEY}.npy entry (expected np.savez with key '{NPZ_MATRIX_KEY}'): {path!r}"
                ) from e
            with zf.open(info, "r") as raw:
                sh, _, _ = _read_npy_header_public(raw)
    else:
        mmap = np.load(path, mmap_mode="r")
        try:
            sh = mmap.shape
        finally:
            mm = getattr(mmap, "_mmap", None)
            if mm is not None:
                mm.close()
    if len(sh) == 1:
        return (int(sh[0]), 1, 1)
    if len(sh) == 2:
        return (int(sh[0]), int(sh[1]), 1)
    if len(sh) != 3:
        raise ValueError(f"Expected 1D, 2D, or 3D volume, got shape {sh!r}")
    return (int(sh[0]), int(sh[1]), int(sh[2]))
