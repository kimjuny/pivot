"""API endpoints for tool management.

This module provides CRUD operations for tools, including both shared
builtin tools and user-created private tools.
All endpoints require authentication.
"""

import logging
from pathlib import Path
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.tool import (
    ToolCreate,
    ToolResponse,
    ToolSourceResponse,
    ToolUpdate,
    UserTool,
)
from app.models.user import User
from app.orchestration.tool import ToolManager, get_tool_manager
from app.services.tool_service import get_tool_service
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

router = APIRouter()

# Path to builtin tools directory
BUILTIN_TOOLS_DIR = Path(__file__).parent.parent / "orchestration" / "tool" / "builtin"


def _get_builtin_tools_info(tool_manager: ToolManager) -> dict[str, dict[str, Any]]:
    """Get builtin tools with their metadata.

    Only returns tools that exist in the builtin directory, filtering out
    user tools that may also be registered in the tool manager.

    Args:
        tool_manager: The tool manager instance.

    Returns:
        Dictionary mapping tool name to metadata.
    """
    builtin_tools: dict[str, dict[str, Any]] = {}
    for tool in tool_manager.list_tools():
        # Only include tools that exist in the builtin directory
        tool_file = BUILTIN_TOOLS_DIR / f"{tool.name}.py"
        if tool_file.exists():
            builtin_tools[tool.name] = {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
    return builtin_tools


@router.get("/tools")
async def get_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ToolResponse]:
    """Get list of all tools (shared + private) with ownership info.

    Tools from both builtin and user workspace directories are returned.
    Private tools include owner information and edit permissions.

    Args:
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        List of tool metadata including ownership and permission info.
    """
    tool_manager = get_tool_manager()

    # Get builtin (shared) tools
    builtin_tools = _get_builtin_tools_info(tool_manager)

    # Get user-created (private) tools from database
    statement = select(UserTool)
    user_tools = db.exec(statement).all()

    # Build response
    result: list[ToolResponse] = []

    # Add shared tools
    for name, info in builtin_tools.items():
        result.append(
            ToolResponse(
                name=name,
                description=info["description"],
                parameters=info["parameters"],
                tool_type="shared",
                owner_id=None,
                owner_username=None,
                can_edit=False,
                can_delete=False,
            )
        )

    # Add private tools
    for tool in user_tools:
        # Get owner username
        owner_statement = select(User).where(User.id == tool.owner_id)
        owner = db.exec(owner_statement).first()
        owner_username = owner.username if owner else None

        # Check permissions
        is_owner = tool.owner_id == current_user.id
        can_edit = is_owner
        can_delete = is_owner

        result.append(
            ToolResponse(
                name=tool.name,
                description=tool.description,
                parameters={},  # Parameters loaded dynamically when needed
                tool_type="private",
                owner_id=tool.owner_id,
                owner_username=owner_username,
                can_edit=can_edit,
                can_delete=can_delete,
            )
        )

    return result


@router.get("/tools/{name}/source")
async def get_tool_source(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ToolSourceResponse:
    """Get tool source code by name.

    Searches both shared and private tools.

    Args:
        name: The tool name.
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        Tool source code and metadata.

    Raises:
        HTTPException: If tool not found (404).
    """
    tool_service = get_tool_service()

    # First check builtin tools
    source_code = tool_service.read_shared_tool_file(name)
    if source_code is not None:
        return ToolSourceResponse(
            name=name,
            source_code=source_code,
            tool_type="shared",
        )

    # Then check user tools
    statement = select(UserTool).where(UserTool.name == name)
    user_tool = db.exec(statement).first()

    if user_tool:
        # Get owner username to find the workspace
        owner_statement = select(User).where(User.id == user_tool.owner_id)
        owner = db.exec(owner_statement).first()

        if owner:
            source_code = tool_service.read_tool_file(owner.username, name)
            if source_code is not None:
                return ToolSourceResponse(
                    name=name,
                    source_code=source_code,
                    tool_type="private",
                )

    raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")


@router.post("/tools", status_code=201)
async def create_tool(
    tool_data: ToolCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ToolResponse:
    """Create a new private tool.

    The tool name and description are automatically extracted from the
    @tool decorator in the source code.

    Validates:
    - Source code is valid Python
    - Source code contains exactly one @tool decorated function
    - Tool name is unique (no conflicts with existing tools)

    Args:
        tool_data: Tool creation data (only source_code required).
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        The created tool metadata.

    Raises:
        HTTPException: If validation fails or name conflicts (400/409).
    """
    tool_service = get_tool_service()
    tool_manager = get_tool_manager()

    # Validate source code and extract metadata
    is_valid, source_error, metadata = tool_service.validate_tool_source(
        tool_data.source_code
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail=source_error)

    if not metadata:
        raise HTTPException(
            status_code=400, detail="Could not extract tool metadata from source code"
        )

    # Extract name and description from metadata
    tool_name = metadata.get("name", "")
    tool_description = metadata.get("description", "")

    # Validate tool name format
    is_valid_name, name_error = tool_service.validate_tool_name(tool_name)
    if not is_valid_name:
        raise HTTPException(status_code=400, detail=name_error)

    # Check for name conflicts with builtin tools
    if tool_service.tool_exists_in_builtin(tool_name):
        raise HTTPException(
            status_code=409,
            detail=f"Tool '{tool_name}' already exists as a shared tool",
        )

    # Check for name conflicts with existing user tools
    statement = select(UserTool).where(UserTool.name == tool_name)
    existing_tool = db.exec(statement).first()
    if existing_tool:
        raise HTTPException(
            status_code=409, detail=f"Tool '{tool_name}' already exists"
        )

    # Create tool file in user's workspace
    try:
        tool_service.create_tool_file(
            current_user.username, tool_name, tool_data.source_code
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None

    # Create database record
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    user_tool = UserTool(
        name=tool_name,
        description=tool_description,
        owner_id=current_user.id,
    )
    db.add(user_tool)
    db.commit()
    db.refresh(user_tool)

    # Refresh tool manager to load the new user tool
    tool_manager.refresh_user_tools(current_user.username)

    logger.info(f"User {current_user.username} created tool '{tool_name}'")

    return ToolResponse(
        name=tool_name,
        description=tool_description,
        parameters=metadata.get("parameters", {}),
        tool_type="private",
        owner_id=current_user.id,
        owner_username=current_user.username,
        can_edit=True,
        can_delete=True,
    )


@router.put("/tools/{name}")
async def update_tool(
    name: str,
    tool_data: ToolUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ToolResponse:
    """Update an existing tool.

    Only the owner can update a private tool.
    Shared tools cannot be updated through this API.

    Args:
        name: The tool name.
        tool_data: Tool update data.
        db: Database session.
        current_user: The currently authenticated user.

    Returns:
        The updated tool metadata.

    Raises:
        HTTPException: If tool not found (404) or not authorized (403).
    """
    tool_service = get_tool_service()
    tool_manager = get_tool_manager()

    # Check if it's a shared tool
    if tool_service.tool_exists_in_builtin(name):
        raise HTTPException(status_code=403, detail="Shared tools cannot be modified")

    # Find user tool
    statement = select(UserTool).where(UserTool.name == name)
    user_tool = db.exec(statement).first()

    if not user_tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")

    # Check ownership
    if user_tool.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own tools")

    # Validate source code if provided
    metadata = None
    if tool_data.source_code:
        is_valid, source_error, metadata = tool_service.validate_tool_source(
            tool_data.source_code, expected_name=name
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=source_error)

        # Update file
        try:
            tool_service.update_tool_file(
                current_user.username, name, tool_data.source_code
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Tool file '{name}' not found"
            ) from None

        # Update description from extracted metadata
        if metadata:
            user_tool.description = metadata.get("description", user_tool.description)

    db.add(user_tool)
    db.commit()
    db.refresh(user_tool)

    # Refresh tool manager to reload the updated user tool
    if tool_data.source_code:
        tool_manager.refresh_user_tools(current_user.username)

    logger.info(f"User {current_user.username} updated tool '{name}'")

    return ToolResponse(
        name=name,
        description=user_tool.description,
        parameters=metadata.get("parameters", {}) if metadata else {},
        tool_type="private",
        owner_id=current_user.id,
        owner_username=current_user.username,
        can_edit=True,
        can_delete=True,
    )


@router.delete("/tools/{name}", status_code=204)
async def delete_tool(
    name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a private tool.

    Only the owner can delete a private tool.
    Shared tools cannot be deleted.

    Args:
        name: The tool name.
        db: Database session.
        current_user: The currently authenticated user.

    Raises:
        HTTPException: If tool not found (404), not authorized (403),
                       or is a shared tool (403).
    """
    tool_service = get_tool_service()
    tool_manager = get_tool_manager()

    # Check if it's a shared tool
    if tool_service.tool_exists_in_builtin(name):
        raise HTTPException(status_code=403, detail="Shared tools cannot be deleted")

    # Find user tool
    statement = select(UserTool).where(UserTool.name == name)
    user_tool = db.exec(statement).first()

    if not user_tool:
        raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")

    # Check ownership
    if user_tool.owner_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="You can only delete your own tools"
        )

    # Delete file
    tool_service.delete_tool_file(current_user.username, name)

    # Delete database record
    db.delete(user_tool)
    db.commit()

    # Remove from tool registry (if loaded)
    if tool_manager.get_tool(name) is not None:
        tool_manager.remove_entry(name)

    logger.info(f"User {current_user.username} deleted tool '{name}'")

    return None
