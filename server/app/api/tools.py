"""API endpoints for tool management."""

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
    create_manual_tool_source,
    delete_manual_tool,
    get_tool_resource,
    list_usable_tools,
    read_manual_tool_source,
    require_tool_access,
    set_tool_access,
    update_manual_tool_source,
)
from app.services.user_service import UserService
from app.services.workspace_service import (
    check_ast,
    check_pyright,
    check_ruff,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

router = APIRouter()


def _read_builtin_tool_source(tool_name: str) -> str:
    """Read source code for a built-in tool by name.

    Args:
        tool_name: Tool name in the built-in tool catalog.

    Returns:
        Full Python source code for the module that defines the tool.

    Raises:
        FileNotFoundError: If the tool does not exist or source cannot be read.
    """
    tool_manager = get_tool_manager()
    tool_metadata = tool_manager.get_tool(tool_name)
    if tool_metadata is None:
        raise FileNotFoundError(f"Built-in tool '{tool_name}' not found.")

    source_file = inspect.getsourcefile(tool_metadata.func)
    if source_file is not None:
        source_path = Path(source_file)
        if source_path.exists():
            return source_path.read_text(encoding="utf-8")

    try:
        return inspect.getsource(tool_metadata.func)
    except (OSError, TypeError) as exc:
        raise FileNotFoundError(
            f"Built-in tool '{tool_name}' source is unavailable."
        ) from exc


class ToolWriteRequest(BaseModel):
    """Request body for creating or updating a tool."""

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


@router.get("/tools/usable")
async def get_usable_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, object]]:
    """List tools the current Studio user can select for agents."""
    return list_usable_tools(db, current_user=current_user)


@router.get("/tools/manage")
async def get_manageable_tools(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> list[dict[str, object]]:
    """List tools visible in the Studio management page."""
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


@router.get(
    "/tools/{source_type}/{tool_name}/access", response_model=ToolAccessResponse
)
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
    try:
        require_tool_access(
            db,
            current_user=current_user,
            tool=tool,
            access_level=AccessLevel.USE,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    grants = (
        []
        if tool.source_type == "builtin"
        else AccessService(db).list_resource_grants(
            resource_type=ResourceType.TOOL,
            resource_id=tool.key,
        )
    )
    return _serialize_tool_access(
        tool_name=tool.name,
        source_type="builtin" if tool.source_type == "builtin" else "manual",
        use_scope=tool.use_scope,
        grants=grants,
    )


@router.get("/tools/{source_type}/{tool_name}/source")
async def get_tool_source(
    source_type: ToolSourceType,
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> dict[str, str]:
    """Read one tool source when the current user has use access."""
    try:
        if source_type == "builtin":
            return {"name": tool_name, "source": _read_builtin_tool_source(tool_name)}
        tool = get_tool_resource(
            db,
            current_user=current_user,
            source_type=source_type,
            tool_name=tool_name,
        )
        return {
            "name": tool.name,
            "source": read_manual_tool_source(
                db,
                current_user=current_user,
                tool=tool,
            ),
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/tools/{source_type}/{tool_name}/source")
async def update_tool_source(
    source_type: ToolSourceType,
    tool_name: str,
    body: ToolWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> dict[str, str]:
    """Update one manual tool source when the current user has edit access."""
    if source_type == "builtin":
        raise HTTPException(status_code=403, detail="Built-in tools are read-only.")
    try:
        try:
            tool = get_tool_resource(
                db,
                current_user=current_user,
                source_type=source_type,
                tool_name=tool_name,
            )
        except FileNotFoundError:
            tool = create_manual_tool_source(
                db,
                current_user=current_user,
                tool_name=tool_name,
                source=body.source,
            )
            return {"name": tool.name, "status": "ok"}
        update_manual_tool_source(
            db,
            current_user=current_user,
            tool=tool,
            source=body.source,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": tool_name, "status": "ok"}


@router.delete("/tools/{source_type}/{tool_name}/source")
async def delete_tool_source(
    source_type: ToolSourceType,
    tool_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.TOOLS_MANAGE)),
) -> dict[str, str]:
    """Delete one manual tool source when the current user has edit access."""
    if source_type == "builtin":
        raise HTTPException(status_code=403, detail="Built-in tools are read-only.")
    try:
        tool = get_tool_resource(
            db,
            current_user=current_user,
            source_type=source_type,
            tool_name=tool_name,
        )
        delete_manual_tool(db, current_user=current_user, tool=tool)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": tool_name, "status": "deleted"}


@router.put(
    "/tools/{source_type}/{tool_name}/access", response_model=ToolAccessResponse
)
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
