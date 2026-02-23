"""Built-in tool: convert text to lowercase."""

from app.orchestration.tool import tool


@tool
def lowercase(text: str) -> str:
    """Convert text to lowercase.

    Args:
        text: The text to convert to lowercase.

    Returns:
        The lowercased text.
    """
    return text.lower()
