from app.orchestration.tool import tool


@tool(
    name="test_tool",
    description="returns anything you input",
    parameters={
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "input anything anything(str)"
            }
        },
        "required": ["input"],
        "additionalProperties": False
    }
)
def test_tool(input: str) -> str:
    """Tool function implementation.

    Args:
        input: Description of input parameter.

    Returns:
        Description of return value.
    """
    return input
