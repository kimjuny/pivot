"""
Add tool - adds two numbers together.
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
