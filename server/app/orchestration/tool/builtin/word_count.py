"""Built-in tool: count the number of words in a text."""

from app.orchestration.tool import tool


@tool
def word_count(text: str) -> int:
    """Count the number of words in a text.

    Args:
        text: The text to count words in.

    Returns:
        The number of words.
    """
    return len(text.split())
