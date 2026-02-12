"""
Example text processing tools for demonstration.
"""

from app.orchestration.tool import tool


@tool(
    name="uppercase",
    description="Convert text to uppercase",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert to uppercase",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)
def uppercase(text: str) -> str:
    """
    Convert text to uppercase.

    Args:
        text: The text to convert.

    Returns:
        The text in uppercase.
    """
    return text.upper()


@tool(
    name="lowercase",
    description="Convert text to lowercase",
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert to lowercase",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    },
)
def lowercase(text: str) -> str:
    """
    Convert text to lowercase.

    Args:
        text: The text to convert.

    Returns:
        The text in lowercase.
    """
    return text.lower()


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
