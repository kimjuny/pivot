"""Built-in tool: add two numbers together."""

from app.orchestration.tool import tool


@tool
def add(a: float, b: float) -> float:
    """Add two numbers together.

    Args:
        a: First number to add.
        b: Second number to add.

    Returns:
        The sum of a and b.
    """
    return a + b
