"""Built-in tool: multiply two numbers together."""

from app.orchestration.tool import tool


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers together.

    Args:
        a: First number to multiply.
        b: Second number to multiply.

    Returns:
        The product of a and b.
    """
    return a * b
