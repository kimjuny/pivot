"""Built-in tool: convert text to uppercase."""

from app.orchestration.tool import tool


@tool
def uppercase(text: str) -> str:
    """Convert text to uppercase.

    Args:
        text: The text to convert to uppercase.

    Returns:
        The uppercased text.
    """
    return text.upper()
