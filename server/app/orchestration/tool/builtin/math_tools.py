"""
Example mathematical tools for demonstration.
"""

from app.orchestration.tool import tool


@tool(
    name="add",
    description="Add two numbers together",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number to add"},
            "b": {"type": "number", "description": "Second number to add"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
)
def add(a: float, b: float) -> float:
    """
    Add two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The sum of a and b.
    """
    return a + b


@tool(
    name="multiply",
    description="Multiply two numbers together",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number to multiply"},
            "b": {"type": "number", "description": "Second number to multiply"},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    },
)
def multiply(a: float, b: float) -> float:
    """
    Multiply two numbers.

    Args:
        a: First number.
        b: Second number.

    Returns:
        The product of a and b.
    """
    return a * b


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
