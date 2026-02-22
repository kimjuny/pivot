"""
Uppercase tool - converts text to uppercase.
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
