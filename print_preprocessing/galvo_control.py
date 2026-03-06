import numpy as np


def generate_x_galvo_output(
    print_height_px: int, scan_size: int, samplesBetweenLines: int
) -> np.ndarray:
    """Generates normalized X-galvo (fast axis) output signal."""
    n = samplesBetweenLines + scan_size
    # start so that index samplesBetweenLines (first point of the raster) has value -1
    start = -(2 * samplesBetweenLines + scan_size - 1) / max(1, scan_size - 1)
    x_line = np.linspace(start, 1.0, n, dtype=np.float64)
    x_galvo_output = np.tile(x_line, print_height_px)
    return x_galvo_output


def generate_y_galvo_output(
    print_height_px: int, scan_size: int, samplesBetweenLines: int
) -> np.ndarray:
    """Generates normalized Y-galvo (slow axis) output signal."""
    y_raster = np.linspace(
        -1.0,
        1.0,
        print_height_px,
        dtype=np.float64,
    )
    y_galvo_output = np.repeat(y_raster, samplesBetweenLines + scan_size)
    return y_galvo_output
