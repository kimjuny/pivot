"""
Power tool - raises a number to a power.
"""

from app.orchestration.tool import tool


@tool(
    name="power",
    description="Raise a number to a power. Returns result as a string for very large numbers.",
    parameters={
        "type": "object",
        "properties": {
            "base": {"type": "number", "description": "The base number"},
            "exponent": {"type": "number", "description": "The exponent"},
        },
        "required": ["base", "exponent"],
        "additionalProperties": False,
    },
)
def power(base: float, exponent: float) -> str | float:
    """
    Raise a number to a power.

    Args:
        base: The base number.
        exponent: The exponent.

    Returns:
        base raised to the power of exponent.
        Returns string for very large numbers (>1e15) to avoid precision loss.
    """
    result = base**exponent

    # For very large numbers, return as string to avoid JSON serialization issues
    if abs(result) > 1e15:
        return str(int(result))

    return result
