"""API endpoints for managing agent-tool associations.

This module provides endpoints for viewing and updating which tools
are available to each agent.
"""

import logging
from pathlib import Path
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.models.agent_tool import AgentTool, AgentToolResponse, AgentToolsUpdate
from app.models.user import User
from app.orchestration.tool import get_tool_manager
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

router = APIRouter()

# Path to builtin tools directory
BUILTIN_TOOLS_DIR = Path(__file__).parent.parent / "orchestration" / "tool" / "builtin"


@router.get("/agents/{agent_id}/tools", response_model=list[AgentToolResponse])
async def get_agent_tools(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get all available tools with their enabled status for an agent.

    Returns a list of all tools (shared and private) with a flag indicating
    whether each tool is enabled for the specified agent.

    Args:
        agent_id: The ID of the agent.
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        List of tools with enabled status.

    Raises:
        HTTPException: If the agent is not found (404).
    """
    # Verify agent exists
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get all available tools from the tool manager
    tool_manager = get_tool_manager()
    all_tools = tool_manager.list_tools()

    # Get enabled tools for this agent
    enabled_tools = db.exec(
        select(AgentTool.tool_name).where(AgentTool.agent_id == agent_id)
    ).all()
    enabled_tool_names = set(enabled_tools)

    # Build response
    result = []
    for tool in all_tools:
        # Determine if this is a builtin or user tool
        tool_file = BUILTIN_TOOLS_DIR / f"{tool.name}.py"
        tool_type = "shared" if tool_file.exists() else "private"

        result.append(
            {
                "name": tool.name,
                "description": tool.description,
                "tool_type": tool_type,
                "is_enabled": tool.name in enabled_tool_names,
            }
        )

    return result


@router.put("/agents/{agent_id}/tools", response_model=list[AgentToolResponse])
async def update_agent_tools(
    agent_id: int,
    tools_update: AgentToolsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Update the list of tools enabled for an agent.

    Replaces the current tool assignments with the provided list.
    Tools not in the list will be disabled for this agent.

    Args:
        agent_id: The ID of the agent.
        tools_update: Object containing the list of tool names to enable.
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        Updated list of tools with enabled status.

    Raises:
        HTTPException: If the agent is not found (404).
    """
    # Verify agent exists
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get all valid tool names from the registry
    tool_manager = get_tool_manager()
    valid_tool_names = {tool.name for tool in tool_manager.list_tools()}

    # Validate that all provided tool names exist
    invalid_tools = set(tools_update.tool_names) - valid_tool_names
    if invalid_tools:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tool names: {', '.join(sorted(invalid_tools))}",
        )

    # Delete all existing tool assignments for this agent
    existing_assignments = db.exec(
        select(AgentTool).where(AgentTool.agent_id == agent_id)
    ).all()
    for assignment in existing_assignments:
        db.delete(assignment)

    # Create new assignments
    for tool_name in tools_update.tool_names:
        new_assignment = AgentTool(agent_id=agent_id, tool_name=tool_name)
        db.add(new_assignment)

    db.commit()

    logger.info(
        f"Updated tools for agent {agent_id}: {len(tools_update.tool_names)} tools enabled"
    )

    # Return updated list
    return await get_agent_tools(agent_id, db, current_user)
