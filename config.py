"""
Configuration file for Irradiant-2photon application.
Contains all hardcoded values and device settings.
"""

import os
from pathlib import Path

import numpy as np
import torch

_CONFIG_DIR = Path(__file__).parent.absolute()

# ============================================================================
# Application & File Paths
# ============================================================================

STATE_FILE = str(_CONFIG_DIR / "gui/gui_state.json")

# ============================================================================
# GUI Configuration
# ============================================================================

GUI_CONFIG = {
    "window_title": "Irradiant-2photon",
    "window_icon": str(_CONFIG_DIR / "gui/logo.png"),
    "window_geometry": (
        300,
        300,
        600,
        900,
    ),  # Window geometry in pixels (x, y, width, height)
    "font_size": 9,  # Font size in points
    "minimap_size": (663, 480),  # Minimap size in pixels (width, height)
}

# ============================================================================
# Print File Parameters
# ============================================================================

# NumPy file support (NPY or NPZ)
NPZ_MATRIX_KEY = "data"

# Dense matrix support
DEFAULT_PRINT_FILE_PARAMS = {
    "matrix_x": 1300,  # Matrix X dimension (pixels)
    "matrix_y": 1300,  # Matrix Y dimension (pixels)
    "matrix_z": 1,  # Matrix Z dimension (layers)
    "dense_matrix_value": 1.0,  # Dense matrix value (0 to 1)
}

# ============================================================================
# Print Parameters
# ============================================================================

DEFAULT_PRINT_PARAMS = {
    "z_step": 1.5,  # Z step size (µm)
    "time_per_pixel": 5.0,  # Time per pixel (µs)
    "fov_x": 300.0,  # Field of view X dimension (µm)
    "fov_y": 300.0,  # Field of view Y dimension (µm)
    "use_custom_xraster_rate": False,  # Send X raster at the custom sample rate
    "xraster_custom_rate_hz": 6
    * 10
    ** 6,  # Custom sample rate for X raster (Hz), if use_xraster_custom_rate_hz is True
}

REQUIRED_PRINT_PARAMS = ["z_step", "time_per_pixel", "fov_x", "fov_y"]

# ============================================================================
# Hardware Devices
# ============================================================================

DAQ_DEVICE = "Dev1"

# ============================================================================
# Analog Output Channels
# ============================================================================

CHANNEL_ORDER = ["x_galvo", "y_galvo", "aom", "z_piezo"]

CHANNELS = {
    "x_galvo": {"DAQ": f"{DAQ_DEVICE}/ao0"},
    "y_galvo": {"DAQ": f"{DAQ_DEVICE}/ao1"},
    "aom": {"DAQ": f"{DAQ_DEVICE}/ao2"},
    "z_piezo": {"DAQ": f"{DAQ_DEVICE}/ao3"},
}

VOLTAGE_AMPLITUDES = {
    "x_galvo": 1.4,  # Voltage amplitude (V)
    "y_galvo": 1.4,  # Voltage amplitude (V)
    "aom": 3.0,  # Voltage amplitude (V)
    "z_piezo": 1.0,  # Voltage amplitude (V)
}

# AOM voltage range is 0 V to +VOLTAGE_AMPLITUDES["aom"], rather than +/-VOLTAGE_AMPLITUDES["aom"].
AOM_VOLTAGE_RANGE = (0, VOLTAGE_AMPLITUDES["aom"])

# DAQ Configuration
DTYPE_DAQ = np.float64  # NI-DAQ functions convert output values to FP64 internally.

# ============================================================================
# Signal Processing
# ============================================================================

# Load in FP32 to preserve low-power precision before scaling and FP16 conversion.
LOAD_DTYPE_NUMPY = np.float32

# AOM processing uses FP16 to reduce peak memory usage during preprocessing;
# precision should be sufficient for grayscale control.
AOM_PROCESSING_DTYPE_TORCH = torch.float16

# Process Z-stage positions in FP64 to preserve positioning precision and represent the full range.
ZSTAGE_PROCESSING_DTYPE_NUMPY = np.float64

# Galvo signals in FP32 so FP16 quantization of the normalized -1 to 1 waveform doesn't limit resolution.
AO_PROCESSING_DTYPE = np.float32

# FP16 limits used to construct the direct lookup table for AOM power -> voltage conversion
FP16_WORKING_LIMIT = torch.finfo(torch.float16).max / 4
FP16_POS_ZERO_BITS = 0x0000
FP16_POS_INF_BITS = 0x7C00

# ============================================================================
# Galvo Calibration
# ============================================================================

# Galvo scaling (µm/V)
# Factor is computed as the measured FOV (numerator) divided by the full scan range
# from -_GALVO_CALIBRATION_AMP_V to +_GALVO_CALIBRATION_AMP_V (denominator).
_GALVO_CALIBRATION_AMP_V = 1.4
GALVO_UM_PER_V = {
    "x": 322.857 / (2 * _GALVO_CALIBRATION_AMP_V),  # Measured 322.857 µm over 2.8 V
    "y": 435.063 / (2 * _GALVO_CALIBRATION_AMP_V),  # Measured 435.063 µm over 2.8 V
}
GALVO_RECOVERY_TIME = 547 * 2e-6  # Galvo recovery time (s)

# X galvo symmetric clip (blanking overshoot): allow X_GALVO_CLIP_EXTRA_FRACTION beyond effective
# amplitude; clip magnitude capped at X_GALVO_CLIP_MAX_V.
# GALVO_RECOVERY_TIME isn't large enough for x-galvo to respond to 50% extension period, but is sufficient for printing.
X_GALVO_CLIP_EXTRA_FRACTION = 0.5
X_GALVO_CLIP_MAX_V = max(3.0, VOLTAGE_AMPLITUDES["x_galvo"])  # (V), max clip magnitude

# ============================================================================
# AOM Calibration
# ============================================================================

MASK_TOLERANCE = 1e-10  # Mask tolerance to avoid floating-point noise
LUT_CSV_PATH = str(
    _CONFIG_DIR
    / "print_preprocessing/calibration_files/aom_voltage_lut_interpolate.csv"
)


# ============================================================================
# Timing Configuration
# ============================================================================

TIMING = {
    "check_interval": 0.001,  # time between DAQ status checks (s)
    "timeout_multiplier": 1.5,  # multiplier for DAQ timeout (unitless)
}

THREADING_CONFIG = {
    "position_update_interval": 100,  # ms
    "state_save_interval": 5000,  # ms
    "joystick_poll_interval": 0.1,  # time between joystick polls (s)
    "position_monitor_interval": 0.05,  # time between position updates (s)
    "wait_timeout": 15000,  # ms
}

# ============================================================================
# Stage Controllers
# ============================================================================

PDXC2_CONFIG = {
    "kinesis_path": r"C:\Program Files\Thorlabs\Kinesis",
    "device_serials": {
        "x_axis": "112450097",
        "y_axis": "112496548",
        "z_axis": "112486529",
    },
    "ref_speed": 10000000,  # Reference speed (nm/s) (10 mm/s)
    "proportional": 8192,  # PID proportional gain (unitless)
    "integral": 8192,  # PID integral gain (unitless)
    "differential": 0,  # PID differential gain (unitless)
    "acceleration": 50000000,  # Acceleration (nm/s^2) (50 mm/s^2)
    "status_bits_mask": 0x00000200,  # Status bits mask for movement detection
    # Movement parameters
    "movement": {
        "tolerance": 10000,  # Position tolerance (nm) for move completion check
        "sleep_step": 0.025,  # time between movement checks (s)
    },
    # Reference finding parameters
    "reference_finding": {
        "tolerance": 6000,  # Reference position tolerance (nm)
        "check_count": 100,  # number of position checks during reference finding
        "sleep_time": 0.2,  # time between position checks (s)
        "final_sleep": 0.5,  # time to wait after reference finding (s)
    },
}

XERYON_CONFIG = {
    "baudrate": 115200,  # Serial communication speed (baud)
    "hardware_id": "04D8",  # Hardware ID for auto-detecting COM port
    "serial_timeout_connect": 0.1,  # Serial timeout for connection check (s)
    "serial_timeout": 0.01,  # Serial timeout for serial.Serial() connection (s)
    "settings_file": str(
        _CONFIG_DIR / "hardware/stage/xeryon/settings_Xeryon.txt"
    ),  # Path to settings file
    # Multipliers (used for converting settings file values to controller units)
    "amplitude_multiplier": 1456.0,  # Multiplier for amplitude settings (unitless)
    "phase_multiplier": 182,  # Multiplier for phase settings (unitless)
    "default_poli_value": 200,  # Default POLI setting value (unitless, polling interval multiplier)
    # Configuration flags
    "output_to_console": False,  # Enable/disable console output in library
    "disable_waiting": False,  # Disable waiting for position updates
    "auto_send_settings": True,  # Automatically send settings on start
    "debug_mode": True,  # Enable debug mode to skip some checks
    "auto_send_enbl": False,  # Automatically send ENBL=1 on errors
    # Reference position (nm) - position to move to after finding index/reference - on GUI start
    "reference_position": {
        "X": 531000,  # nm
        "Y": 291000,  # nm
        "Z": 0,  # nm
    },
    # Stage configurations
    "stages": {
        "XLS_3_120_5": {  # X or Y axis
            "encoder_resolution_command": "XLS3=5",
            "encoder_resolution": 5.0,  # encoder resolution (nm/count)
            "speed_multiplier": 1000,  # Multiplier for speed settings (unitless)
        },
        "XVP_80_5": {  # Z axis
            "encoder_resolution_command": "XLS1=5",
            "encoder_resolution": 5.0,  # encoder resolution (nm/count)
            "speed_multiplier": 1000,  # Multiplier for speed settings (unitless)
        },
    },
    # Settling parameters for wait_until_settled
    "settling": {
        "poll_interval": 0.002,  # time between position checks (s)
        "duration": 1.5,  # time of stability required (s)
        "settling_tolerance": 50,  # tolerance (nm)
        "timeout": 15.0,  # maximum time to wait for settling (s)
    },
    #
    "elim_recovery": {
        "timeout": 1.5,  # Maximum time to wait for error status to clear (s)
        "poll_interval": 0.01,  # ELIM status polling interval during recovery (s)
    },
}

_DOVER_ROOT = r"C:\Users\Irradiant\Dover\MotionSynergy"

DOVER_CONFIG = {
    "dover_root": _DOVER_ROOT,
    "python_modules_dir": os.path.join(
        _DOVER_ROOT, "SourceCode", "Examples", "Python", "ConsoleApplication"
    ),
    "support_folder": os.path.join(_DOVER_ROOT, "SupportFolder"),
    "program_data_folder": os.path.join(_DOVER_ROOT, "ProgramDataFolder"),
    "application_version": "1.0",
    "config_filename": "Instrument.cfg",
    "settling": {
        "poll_interval": 0.015,  # time between position checks (s)
        "duration": 0.250,  # time of stability required (s)
        "settling_tolerance": 30,  # tolerance (nm) absolute not +-
        "timeout": 10.0,  # maximum time to wait for settling (s)
    },
    # Reference position (nm) - position to move to after finding index/reference - on GUI start
    "reference_position": {
        "ZAXIS": 1540000,  # nm (Dover DOF5 axis name)
    },
}

# GUI axis -> hardware axis letter.
# Xeryon swaps X/Y to match the camera feed orientation; other backends map 1:1.
STAGE_AXIS_MAP = {
    "xeryon": {"X": "Y", "Y": "X", "Z": "Z"},
    "default": {"X": "X", "Y": "Y", "Z": "Z"},
}

STAGE_POSITION_LIMITS = {
    # Soft limits (nm) in the GUI axis frame (X/Y/Z as the user sees them), to keep
    # the objective inside the immersion holder ring. Hardware travel stays wider
    # (see settings_Xeryon.txt). Swap Sample bypasses these.
    "axis_limits": {
        "X": {"min": -4e6, "max": 9e6},  # -4mm to 9mm
        "Y": {"min": -4e6, "max": 9e6},  # -4mm to 9mm
        "Z": {"min": -5e5, "max": 2.5e6},  # -0.5mm to 2.5mm
    },
}

SWAP_SAMPLE_POSITION = {
    # X and Y are in GUI frame (x -> x_controller, y -> y_controller), which is
    # swapped relative to the Xeryon axis letters. x is outside STAGE_POSITION_LIMITS.
    "x": 45e6,  # nm
    "y": 0,  # nm
    "z": 2.5e6,  # nm (Dover Z only)
}

# ============================================================================
# Joystick Configuration
# ============================================================================

JOYSTICK_CONFIG = {
    "deadzone": 0.1,  # Joystick deadzone threshold (unitless, 0-1)
    "base_position_scale_xy": 500000,  # Position scale for X/Y axes (nm/joystick unit)
    "base_position_scale_z": 50000,  # Position scale for Z axis (nm/joystick unit)
    "fine_control_multiplier": 0.1,  # Multiplier for fine control mode (unitless)
    "reconnect_interval": 2.0,  # Time between joystick reconnect attempts (s)
    "axes": {"x": 0, "y": 1, "z": 4},  # Joystick axes mapping
    "buttons": {
        "laser": 0,
        "pointscan": 1,
        "fine_control": 5,
    },  # Joystick buttons mapping
}
