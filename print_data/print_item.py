from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from config import NPZ_MATRIX_KEY, REQUIRED_PRINT_PARAMS
from utils.dtypes import ProcessingDataTypes


def load_matrix_from_path(file_path: str) -> np.ndarray:
    """Load matrix from NumPy file (NPY or NPZ). Promotes 2D arrays to 3D (adds Z-axis of size 1)."""
    matrix = np.load(file_path)

    if file_path.lower().endswith(".npz"):  # Load full npz
        try:
            matrix = matrix[NPZ_MATRIX_KEY]
        except KeyError:
            raise KeyError(f"NPZ file {file_path} is missing the {NPZ_MATRIX_KEY} key.")

    return np.atleast_3d(matrix).astype(ProcessingDataTypes.numpy_dtype)


def generate_dense_matrix(
    matrix_x: int, matrix_y: int, matrix_z: int, value: float
) -> np.ndarray:
    """Generate dense matrix with given dimensions and value."""
    dense_value = max(0.0, min(1.0, value))  # Clamp to 0-1
    return (np.ones((matrix_y, matrix_x, matrix_z)) * dense_value).astype(
        ProcessingDataTypes.numpy_dtype
    )


@dataclass
class PrintItem:
    """Single print job configuration: 3D matrix and print parameters."""

    file_type: str  # "numpy" | "dense"
    file_path: Optional[str] = None  # Required if file_type == "numpy"
    dense_params: Optional[Dict[str, Any]] = None  # Required if file_type == "dense"
    print_params: Dict[str, Any] = field(
        default_factory=dict
    )  # z_step (µm), time_per_pixel (µs), fov_x (µm), fov_y (µm), use_custom_xraster_rate (bool), xraster_custom_rate_hz (Hz)
    _matrix: Optional[np.ndarray] = field(
        default=None, init=False, repr=False
    )  # Lazy-loaded 3D matrix (y, x, z), values typically 0-1

    def _validate_matrix_params(self) -> None:
        """Validate that required parameters are present for matrix loading."""
        if self.file_type == "numpy":
            if not self.file_path:
                raise ValueError("file_path is required when file_type is 'numpy'")
        elif self.file_type == "dense":
            if not self.dense_params:
                raise ValueError("dense_params is required when file_type is 'dense'")
        else:
            raise ValueError(
                f"Invalid file_type: {self.file_type}. Must be 'numpy' or 'dense'"
            )

    def load_matrix(self) -> np.ndarray:
        """Load or generate matrix on-demand."""
        if self._matrix is None:
            self._validate_matrix_params()
            if self.file_type == "numpy":
                # file_path is guaranteed to be non-None after validation
                assert self.file_path is not None
                print(f"Loading matrix from file: {self.file_path}")
                self._matrix = load_matrix_from_path(self.file_path)
            else:  # dense
                # dense_params is guaranteed to be non-None after validation
                assert self.dense_params is not None
                print(
                    f"Generating dense matrix: {self.dense_params['matrix_x']} x {self.dense_params['matrix_y']} x {self.dense_params['matrix_z']}, value = {self.dense_params['dense_matrix_value']}"
                )
                self._matrix = generate_dense_matrix(
                    self.dense_params["matrix_x"],
                    self.dense_params["matrix_y"],
                    self.dense_params["matrix_z"],
                    self.dense_params["dense_matrix_value"],
                )
        return self._matrix

    def clear_matrix(self) -> None:
        """Free matrix memory."""
        self._matrix = None

    def validate_print_params(self) -> None:
        """Validate that required parameters are present for printing."""
        for param in REQUIRED_PRINT_PARAMS:
            if param not in self.print_params:
                raise ValueError(f"{param} is required in print_params")

    @classmethod
    def from_gui_inputs(
        cls,
        use_dense: bool,
        npy_path: str,
        matrix_x: int,
        matrix_y: int,
        matrix_z: int,
        dense_value: float,
        z_step: float,
        time_per_pixel: float,
        fov_x: float,
        fov_y: float,
        use_custom_xraster_rate: bool,
        xraster_custom_rate_hz: float,
    ) -> "PrintItem":
        """Create PrintItem from GUI inputs."""
        print_params = {
            "z_step": z_step,
            "time_per_pixel": time_per_pixel,
            "fov_x": fov_x,
            "fov_y": fov_y,
            "use_custom_xraster_rate": use_custom_xraster_rate,
            "xraster_custom_rate_hz": xraster_custom_rate_hz,
        }

        if use_dense:
            return cls(
                file_type="dense",
                dense_params={
                    "matrix_x": matrix_x,
                    "matrix_y": matrix_y,
                    "matrix_z": matrix_z,
                    "dense_matrix_value": dense_value,
                },
                print_params=print_params,
            )
        else:
            return cls(
                file_type="numpy",
                file_path=npy_path,
                print_params=print_params,
            )
