"""
Stage controller assembly and shared behavior.

Builds and homes the full set of stage controllers for the GUI. This lives above
the individual controllers in the import graph (it imports them), which is why it
is separate from ``utils.py`` (which the controllers import for limit validation).
"""

from config import PDXC2_CONFIG, STAGE_AXIS_MAP

from .dover_controller import DoverController
from .mock_controller import MockController
from .pdxc2_controller import PDXC2Controller
from .xeryon.xeryon_controller import XeryonController

StageController = XeryonController | PDXC2Controller | DoverController | MockController


def create_stage_controller(gui_axis: str, xeryon_connected: bool) -> StageController:
    """Create the best available controller for a single GUI axis.

    The GUI<->hardware axis swap lives entirely in ``STAGE_AXIS_MAP``, so the rest
    of the GUI works purely in the GUI frame (X/Y/Z). Priority: Xeryon > PDXC2 > Mock.
    """
    pdxc2_serial = PDXC2_CONFIG["device_serials"][f"{gui_axis.lower()}_axis"]
    if xeryon_connected:
        hw_axis = STAGE_AXIS_MAP["xeryon"][gui_axis]
        return XeryonController(serial="", home=False, axis=hw_axis, gui_axis=gui_axis)

    hw_axis = STAGE_AXIS_MAP["default"][gui_axis]
    if PDXC2Controller.is_connected(pdxc2_serial):
        return PDXC2Controller(
            serial=pdxc2_serial, home=False, axis=hw_axis, gui_axis=gui_axis
        )
    return MockController(
        serial=pdxc2_serial, home=False, axis=hw_axis, gui_axis=gui_axis
    )


def _home_or_fallback(
    gui_axis: str, controller: StageController, axis_map: dict
) -> StageController:
    """Home a controller; on failure fall back to Dover (Z only) then Mock.

    Returns the working controller (possibly a replacement).
    """
    try:
        controller.home()
        return controller
    except (RuntimeError, Exception) as e:
        # Special handling for Z axis: try Dover as fallback
        if gui_axis == "Z" and not isinstance(controller, DoverController):
            print(
                f"Z axis: Reference finding failed ({e}), trying Dover as fallback..."
            )
            if DoverController.is_connected(""):
                try:
                    dover_z = DoverController(
                        serial="", home=False, axis="Z", gui_axis="Z"
                    )
                    dover_z.home()
                    print("Z axis: Successfully fell back to DoverController")
                    return dover_z
                except Exception as dover_error:
                    print(
                        f"Z axis: Dover homing also failed ({dover_error}), using MockController"
                    )
            else:
                print("Z axis: Dover not available, using MockController")

        # Default fallback to MockController
        print(
            f"{gui_axis} axis: Reference finding failed ({e}), replacing with MockController"
        )
        serial = PDXC2_CONFIG["device_serials"][f"{gui_axis.lower()}_axis"]
        return MockController(
            serial=serial, home=False, axis=axis_map[gui_axis], gui_axis=gui_axis
        )


def create_stage_controllers():
    """Create and home the stage controllers.

    Returns ``(x_controller, y_controller, z_controller, axis_map)`` where
    ``axis_map`` is the resolved GUI->hardware axis mapping.
    Priority: Xeryon > PDXC2 > Dover (Z only) > Mock.
    """
    xeryon_connected = XeryonController.is_connected("")
    # Single source of truth for the GUI<->hardware axis swap.
    axis_map = (
        STAGE_AXIS_MAP["xeryon"] if xeryon_connected else STAGE_AXIS_MAP["default"]
    )

    # Create all controllers first (Z, then X, Y for Xeryon compatibility).
    controllers: dict[str, StageController] = {
        gui_axis: create_stage_controller(gui_axis, xeryon_connected)
        for gui_axis in ("Z", "X", "Y")
    }

    # Home each explicitly; on failure fall back (Dover for Z, else Mock).
    for gui_axis in ("Z", "X", "Y"):
        controllers[gui_axis] = _home_or_fallback(
            gui_axis, controllers[gui_axis], axis_map
        )

    return controllers["X"], controllers["Y"], controllers["Z"], axis_map


def get_z_step_direction(stage: StageController) -> int:
    """Return the stage direction for increasing print layer indices.
    Dover moves the objective upward as layers progress; other stages move downward.
    """
    return 1 if isinstance(stage, DoverController) else -1
