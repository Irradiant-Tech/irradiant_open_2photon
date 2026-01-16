"""
Configuration file for Irradiant-2photon application.
Contains all hardcoded values and device settings.
"""

import os
from pathlib import Path

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
# Default Application Parameters
# ============================================================================

DEFAULT_PRINT_FILE_PARAMS = {
    "matrix_x": 1300,  # Matrix X dimension (pixels)
    "matrix_y": 1300,  # Matrix Y dimension (pixels)
    "matrix_z": 1,  # Matrix Z dimension (layers)
    "dense_matrix_value": 1.0,  # Dense matrix value (0 to 1)
}

DEFAULT_PRINT_PARAMS = {
    "z_step": 1.5,  # Z step size (µm)
    "time_per_pixel": 5.0,  # Time per pixel (µs)
    "fov_x": 650.0,  # Field of view X dimension (µm)
    "fov_y": 650.0,  # Field of view Y dimension (µm)
}

# ============================================================================
# DAQ Device and Analog Output Channels
# ============================================================================

DAQ_DEVICE = "Dev1"

DAQ_CHANNEL_ORDER = ["x_galvo", "y_galvo", "aom", "z_piezo"]

DAQ_CHANNELS = {
    "x_galvo": f"{DAQ_DEVICE}/ao0",
    "y_galvo": f"{DAQ_DEVICE}/ao1",
    "aom": f"{DAQ_DEVICE}/ao2",
    "z_piezo": f"{DAQ_DEVICE}/ao3",
}

VOLTAGE_AMPLITUDES = {
    "x_galvo": 1.4,  # Voltage amplitude (V)
    "y_galvo": 1.4,  # Voltage amplitude (V)
    "aom": 3.0,  # Voltage amplitude (V)
    "z_piezo": 1.0,  # Voltage amplitude (V)
}

# ============================================================================
# Signal Processing & Calibration
# ============================================================================

GALVO_SCALING = {"x": 613, "y": 748}  # Galvo scaling (µm/V), full range -1V to 1V
GALVO_RECOVERY_TIME = 547 * 2e-6  # Galvo recovery time (s)

AOM_POWER_RANGE = (0.0, 1.0)  # Min and max allowed powers for AOM

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
        "duration": 0.80,  # time of stability required (s)
        "settling_tolerance": 30,  # tolerance (nm) absolute not +-
        "timeout": 10.0,  # maximum time to wait for settling (s)
    },
    # Reference position (nm) - position to move to after finding index/reference - on GUI start
    "reference_position": {
        "ZAXIS": 1540000,  # nm (Dover DOF5 axis name)
    },
}

STAGE_POSITION_LIMITS = {
    # Per-axis position limits (min, max) (nm)
    # Note: These limits are based on Xeryon stage hardware limits.
    # PDXC2 may have different limits - this is suboptimal but kept shared
    # for simplicity. New stage installations will need new per-controller limits.
    "axis_limits": {
        "X": {"min": -45e6, "max": 45e6},  # -45mm to 45mm
        "Y": {"min": -45e6, "max": 45e6},  # -45mm to 45mm
        "Z": {"min": -5e6, "max": 5e6},  # -5mm to 5mm
        "ZAXIS": {
            "min": -2.5e6,
            "max": 2.5e6,
        },  # -2.5mm to 2.5mm (Dover DOF5 axis name)
    },
}

# ============================================================================
# Joystick Configuration
# ============================================================================

JOYSTICK_CONFIG = {
    "deadzone": 0.1,  # Joystick deadzone threshold (unitless, 0-1)
    "base_position_scale_xy": 500000,  # Position scale for X/Y axes (nm/joystick unit)
    "base_position_scale_z": 50000,  # Position scale for Z axis (nm/joystick unit)
    "fine_control_multiplier": 0.1,  # Multiplier for fine control mode (unitless)
}
