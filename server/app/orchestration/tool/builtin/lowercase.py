"""
Lowercase tool - converts text to lowercase.
"""

from app.orchestration.tool import tool


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
