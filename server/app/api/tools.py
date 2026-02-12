"""API endpoints for tool management."""

from typing import Any

from app.orchestration.tool import get_tool_manager
from fastapi import APIRouter

router = APIRouter()


@router.get("/tools")
async def get_tools() -> list[dict[str, Any]]:
    """
    Get list of all registered tools.

    Returns:
        List of tool metadata including name, description, and parameters.
    """
    tool_manager = get_tool_manager()
    tools = tool_manager.list_tools()

    # Convert to serializable format
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]
