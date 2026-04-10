"""API endpoints for tool management.

Provides two categories of tools:
- **Shared tools**: built-in tools loaded at startup, available to all users.
- **Private tools**: per-user Python source files stored under
  ``users/{username}/tools/`` in the active POSIX storage root.

All endpoints require authentication.
"""

import inspect
from pathlib import Path
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.orchestration.tool import get_tool_manager
from app.services.workspace_service import (
    check_ast,
    check_pyright,
    check_ruff,
    delete_user_tool,
    list_user_tools,
    read_user_tool,
    write_user_tool,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared (built-in) tools
# ---------------------------------------------------------------------------


@router.get("/tools/shared")
async def get_shared_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get all shared (built-in) tools available to every user.

    Returns:
        List of tool metadata dicts with ``name``, ``description``,
        and ``parameters`` fields.
    """
    tool_manager = get_tool_manager()
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "tool_type": t.tool_type,
        }
        for t in tool_manager.list_tools()
    ]


def _read_shared_tool_source(tool_name: str) -> str:
    """Read source code for a shared tool by name.

    Args:
        tool_name: Tool name in the shared tool catalog.

    Returns:
        Full Python source code for the module that defines the tool.

    Raises:
        FileNotFoundError: If the tool does not exist or source cannot be read.
    """
    tool_manager = get_tool_manager()
    tool_metadata = tool_manager.get_tool(tool_name)
    if tool_metadata is None:
        raise FileNotFoundError(f"Shared tool '{tool_name}' not found.")

    source_file = inspect.getsourcefile(tool_metadata.func)
    if source_file is not None:
        source_path = Path(source_file)
        if source_path.exists():
            return source_path.read_text(encoding="utf-8")

    try:
        return inspect.getsource(tool_metadata.func)
    except (OSError, TypeError) as exc:
        raise FileNotFoundError(
            f"Shared tool '{tool_name}' source is unavailable."
        ) from exc


@router.get("/tools/shared/{tool_name}")
async def get_shared_tool_source(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Get source code for a shared (built-in) tool.

    Args:
        tool_name: Stem of the shared tool.

    Returns:
        Dict with ``name`` and ``source`` keys.

    Raises:
        404: If the shared tool does not exist.
    """
    try:
        source = _read_shared_tool_source(tool_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"name": tool_name, "source": source}


# ---------------------------------------------------------------------------
# Private (user-workspace) tools
# ---------------------------------------------------------------------------


class ToolWriteRequest(BaseModel):
    """Request body for creating or updating a private tool."""

    source: str


@router.get("/tools/private")
async def get_private_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all private tools belonging to the current user.

    Returns:
        List of dicts with ``name``, ``filename``, and ``tool_type`` keys.
    """
    return list_user_tools(current_user.username)


@router.get("/tools/private/{tool_name}")
async def get_private_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Get the source code of a private tool.

    Args:
        tool_name: Stem of the tool file (without ``.py``).

    Returns:
        Dict with ``name`` and ``source`` keys.

    Raises:
        404: If the tool file does not exist.
    """
    try:
        source = read_user_tool(current_user.username, tool_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"name": tool_name, "source": source}


@router.put("/tools/private/{tool_name}")
async def upsert_private_tool(
    tool_name: str,
    body: ToolWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Create or update a private tool source file.

    Args:
        tool_name: Stem of the tool file (without ``.py``).
        body: Request body containing the Python ``source`` code.

    Returns:
        Confirmation dict with ``name`` and ``status`` keys.
    """
    write_user_tool(current_user.username, tool_name, body.source)
    return {"name": tool_name, "status": "ok"}


@router.delete("/tools/private/{tool_name}")
async def delete_private_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a private tool source file.

    Args:
        tool_name: Stem of the tool file (without ``.py``).

    Returns:
        Confirmation dict with ``name`` and ``status`` keys.

    Raises:
        404: If the tool file does not exist.
    """
    try:
        delete_user_tool(current_user.username, tool_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"name": tool_name, "status": "deleted"}


# ---------------------------------------------------------------------------
# Legacy endpoint - kept for backward compatibility
# ---------------------------------------------------------------------------


@router.get("/tools")
async def get_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Get all registered shared tools (legacy endpoint).

    Returns:
        List of tool metadata including name, description, and parameters.
    """
    tool_manager = get_tool_manager()
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
            "tool_type": t.tool_type,
        }
        for t in tool_manager.list_tools()
    ]


# ---------------------------------------------------------------------------
# Code analysis endpoints
# ---------------------------------------------------------------------------


class CodeCheckRequest(BaseModel):
    """Request body for code analysis endpoints."""

    source: str


@router.post("/tools/check/ast")
async def check_tool_ast(
    body: CodeCheckRequest,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Parse Python source with the built-in ``ast`` module.

    Intended to be called ~200 ms after the user stops typing to give
    immediate syntax-error feedback.

    Args:
        body: Request body containing the Python ``source`` code.

    Returns:
        List of error dicts (empty list if source is valid).
    """
    return check_ast(body.source)


@router.post("/tools/check/ruff")
async def check_tool_ruff(
    body: CodeCheckRequest,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Lint Python source with ``ruff`` using the project configuration.

    Intended to be called ~2 s after the user stops typing.

    Args:
        body: Request body containing the Python ``source`` code.

    Returns:
        List of diagnostic dicts compatible with Monaco editor markers.
    """
    return check_ruff(body.source)


@router.post("/tools/check/pyright")
async def check_tool_pyright(
    body: CodeCheckRequest,
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Type-check Python source with ``pyright`` using the project configuration.

    Intended to be called when the user explicitly saves the file.

    Args:
        body: Request body containing the Python ``source`` code.

    Returns:
        List of diagnostic dicts compatible with Monaco editor markers.
    """
    return check_pyright(body.source)
