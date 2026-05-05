"""API endpoints for tool management.

Provides two categories of tools:
- **Shared tools**: built-in tools loaded at startup, available to all users.
- **Private tools**: per-user Python source files stored under
  ``users/{username}/tools/`` in the active POSIX storage root.

All endpoints require authentication.
"""

import inspect
from pathlib import Path
from typing import Any, Literal

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel, PrincipalType, ResourceAccess, ResourceType
from app.models.user import User
from app.orchestration.tool import get_tool_manager
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.group_service import GroupService
from app.services.tool_service import (
    ToolSourceType,
    delete_manual_tool_resource,
    get_tool_resource,
    list_usable_tools,
    set_tool_access,
)
from app.services.user_service import UserService
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
from pydantic import BaseModel, Field
from sqlmodel import Session

router = APIRouter()


# ---------------------------------------------------------------------------
# Shared (built-in) tools
# ---------------------------------------------------------------------------


@router.get("/tools/shared")
async def get_shared_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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


class ToolAccessUpdate(BaseModel):
    """Payload for replacing one tool's selected access."""

    use_scope: Literal["all", "selected"] = "all"
    use_user_ids: list[int] = Field(default_factory=list)
    use_group_ids: list[int] = Field(default_factory=list)
    edit_user_ids: list[int] = Field(default_factory=list)
    edit_group_ids: list[int] = Field(default_factory=list)


class ToolAccessResponse(ToolAccessUpdate):
    """Direct use/edit grants for one tool."""

    tool_name: str
    source_type: ToolSourceType
    read_only: bool


class ToolAccessUserOption(BaseModel):
    """Selectable user in a tool auth editor."""

    id: int
    username: str
    display_name: str | None
    email: str | None


class ToolAccessGroupOption(BaseModel):
    """Selectable group in a tool auth editor."""

    id: int
    name: str
    description: str
    member_count: int


class ToolAccessOptionsResponse(BaseModel):
    """Selectable users and groups for a tool auth editor."""

    users: list[ToolAccessUserOption]
    groups: list[ToolAccessGroupOption]


def _grant_principal_ids(
    grants: list[ResourceAccess],
    principal_type: PrincipalType,
) -> list[int]:
    """Return integer principal IDs for one principal type."""
    principal_ids: list[int] = []
    for grant in grants:
        if grant.principal_type == principal_type:
            principal_ids.append(int(grant.principal_id))
    return sorted(principal_ids)


def _serialize_tool_access(
    *,
    tool_name: str,
    source_type: ToolSourceType,
    use_scope: str,
    grants: list[ResourceAccess],
) -> ToolAccessResponse:
    """Serialize direct grants for one tool."""
    use_grants = [grant for grant in grants if grant.access_level == AccessLevel.USE]
    edit_grants = [grant for grant in grants if grant.access_level == AccessLevel.EDIT]
    return ToolAccessResponse(
        tool_name=tool_name,
        source_type=source_type,
        read_only=source_type == "builtin",
        use_scope="selected" if use_scope == "selected" else "all",
        use_user_ids=_grant_principal_ids(use_grants, PrincipalType.USER),
        use_group_ids=_grant_principal_ids(use_grants, PrincipalType.GROUP),
        edit_user_ids=_grant_principal_ids(edit_grants, PrincipalType.USER),
        edit_group_ids=_grant_principal_ids(edit_grants, PrincipalType.GROUP),
    )


def _serialize_tool_access_options(db: Session) -> ToolAccessOptionsResponse:
    """Serialize selectable users and groups for one tool access editor."""
    group_service = GroupService(db)
    member_counts = group_service.get_member_count_by_group_id()
    return ToolAccessOptionsResponse(
        users=[
            ToolAccessUserOption(
                id=user.id or 0,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
            )
            for user in UserService(db).list_users()
            if user.id is not None and user.status == "active"
        ],
        groups=[
            ToolAccessGroupOption(
                id=group.id or 0,
                name=group.name,
                description=group.description,
                member_count=member_counts.get(group.id or 0, 0),
            )
            for group in group_service.list_groups()
            if group.id is not None
        ],
    )


@router.get("/tools/private")
async def get_private_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> list[dict[str, Any]]:
    """List all private tools belonging to the current user.

    Returns:
        List of dicts with ``name``, ``filename``, and ``tool_type`` keys.
    """
    return list_user_tools(current_user.username)


@router.get("/tools/usable")
async def get_usable_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, object]]:
    """List tools the current Studio user can select for agents."""
    return list_usable_tools(db, current_user=current_user)


@router.get("/tools/access-options", response_model=ToolAccessOptionsResponse)
async def get_tool_create_access_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> ToolAccessOptionsResponse:
    """Return selectable principals for a new tool access editor."""
    return _serialize_tool_access_options(db)


@router.get(
    "/tools/{source_type}/{tool_name}/access-options",
    response_model=ToolAccessOptionsResponse,
)
async def get_tool_access_options(
    source_type: ToolSourceType,
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> ToolAccessOptionsResponse:
    """Return selectable principals for one tool access editor."""
    try:
        tool = get_tool_resource(
            db,
            current_user=current_user,
            source_type=source_type,
            tool_name=tool_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if tool.source_type != "builtin":
        AccessService(db).require_resource_access(
            user=current_user,
            resource_type=ResourceType.TOOL,
            resource_id=tool.key,
            access_level=AccessLevel.EDIT,
            creator_user_id=tool.creator_id,
            use_scope=tool.use_scope,
        )
    return _serialize_tool_access_options(db)


@router.get("/tools/{source_type}/{tool_name}/access", response_model=ToolAccessResponse)
async def get_tool_access(
    source_type: ToolSourceType,
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> ToolAccessResponse:
    """Return direct use/edit grants for one tool."""
    try:
        tool = get_tool_resource(
            db,
            current_user=current_user,
            source_type=source_type,
            tool_name=tool_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    grants = [] if tool.source_type == "builtin" else AccessService(db).list_resource_grants(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
    )
    return _serialize_tool_access(
        tool_name=tool.name,
        source_type="builtin" if tool.source_type == "builtin" else "manual",
        use_scope=tool.use_scope,
        grants=grants,
    )


@router.put("/tools/{source_type}/{tool_name}/access", response_model=ToolAccessResponse)
async def update_tool_access(
    source_type: ToolSourceType,
    tool_name: str,
    payload: ToolAccessUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> ToolAccessResponse:
    """Replace direct use/edit grants for one user-created tool."""
    try:
        tool = get_tool_resource(
            db,
            current_user=current_user,
            source_type=source_type,
            tool_name=tool_name,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AccessService(db).require_resource_access(
        user=current_user,
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
        access_level=AccessLevel.EDIT,
        creator_user_id=tool.creator_id,
        use_scope=tool.use_scope,
    )
    try:
        set_tool_access(
            db,
            tool=tool,
            use_scope=payload.use_scope,
            use_user_ids=set(payload.use_user_ids),
            use_group_ids=set(payload.use_group_ids),
            edit_user_ids=set(payload.edit_user_ids),
            edit_group_ids=set(payload.edit_group_ids),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_tool_access(
        tool_name=tool.name,
        source_type="manual",
        use_scope=tool.use_scope,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.TOOL,
            resource_id=tool.key,
        ),
    )


@router.get("/tools/private/{tool_name}")
async def get_private_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": tool_name, "source": source}


@router.put("/tools/private/{tool_name}")
async def upsert_private_tool(
    tool_name: str,
    body: ToolWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> dict[str, str]:
    """Create or update a private tool source file.

    Args:
        tool_name: Stem of the tool file (without ``.py``).
        body: Request body containing the Python ``source`` code.

    Returns:
        Confirmation dict with ``name`` and ``status`` keys.
    """
    try:
        write_user_tool(current_user.username, tool_name, body.source)
        get_tool_resource(
            db,
            current_user=current_user,
            source_type="manual",
            tool_name=tool_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": tool_name, "status": "ok"}


@router.delete("/tools/private/{tool_name}")
async def delete_private_tool(
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    delete_manual_tool_resource(db, owner=current_user, tool_name=tool_name)
    return {"name": tool_name, "status": "deleted"}


# ---------------------------------------------------------------------------
# Legacy endpoint - kept for backward compatibility
# ---------------------------------------------------------------------------


@router.get("/tools")
async def get_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> list[dict[str, Any]]:
    """Type-check Python source with ``pyright`` using the project configuration.

    Intended to be called when the user explicitly saves the file.

    Args:
        body: Request body containing the Python ``source`` code.

    Returns:
        List of diagnostic dicts compatible with Monaco editor markers.
    """
    return check_pyright(body.source)
