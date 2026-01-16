"""
Utility functions for stage controllers.
"""

from config import STAGE_POSITION_LIMITS


def validate_position_limit(axis: str, target: float) -> tuple[bool, str | None]:
    """
    Validate target position against axis limits.

    Args:
        axis: Axis identifier (X, Y, or Z)
        target: Target position in nanometers

    Returns:
        Tuple of (is_valid, error_message).
        is_valid: True if target is within limits, False otherwise
        error_message: Error message string if invalid, None if valid
    """
    axis_limits = STAGE_POSITION_LIMITS["axis_limits"].get(axis.upper(), {})
    min_limit = axis_limits.get("min")
    max_limit = axis_limits.get("max")

    # Check if limits are configured
    if min_limit is None or max_limit is None:
        return (
            False,
            f"Position limits not configured for {axis} axis",
        )

    # Check if target is within limits
    if target < min_limit or target > max_limit:
        return (
            False,
            f"Error setting target position for {axis} axis to {target}nm: "
            f"target outside allowed range [{min_limit}nm, {max_limit}nm]",
        )

    return (True, None)
