"""
Multiply tool - multiplies two numbers together.
"""

from app.orchestration.tool import tool


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
