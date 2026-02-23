"""Built-in tool: raise a number to a power."""

from app.orchestration.tool import tool


@tool
def power(base: float, exponent: float) -> str | float:
    """Raise a number to a power.

    Returns a string representation for very large results to avoid
    JSON precision loss.

    Args:
        base: The base number.
        exponent: The exponent.

    Returns:
        base raised to the power of exponent, or its string form if > 1e15.
    """
    result = base**exponent

    # For very large numbers, return as string to avoid JSON serialization issues
    if abs(result) > 1e15:
        return str(int(result))

    return result
