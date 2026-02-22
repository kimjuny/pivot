"""
Word count tool - counts the number of words in text.
"""

from app.orchestration.tool import tool


@tool(
    name="word_count",
    description="Count the number of words in a text",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to count words in"},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)
def word_count(text: str) -> int:
    """
    Count the number of words in a text.

    Args:
        text: The text to analyze.

    Returns:
        The number of words in the text.
    """
    return len(text.split())
