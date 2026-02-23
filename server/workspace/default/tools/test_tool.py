from app.orchestration.tool import tool


@tool
def test_tool(input: str) -> str:
    """Describe what your tool does.

    Args:
        input: Description of the input parameter.

    Returns:
        Description of the return value.
    """
    return input
