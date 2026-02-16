"""API endpoints for tool management.

All endpoints require authentication.
"""

from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.orchestration.tool import get_tool_manager
from fastapi import APIRouter, Depends
from sqlmodel import Session

router = APIRouter()


@router.get("/tools")
async def get_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
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
