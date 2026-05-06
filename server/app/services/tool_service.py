"""Service layer for tool auth metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from app.models.access import AccessLevel, PrincipalType, ResourceType
from app.models.tool import ToolResource
from app.models.user import User
from app.orchestration.tool import get_tool_manager
from app.services.access_service import AccessService
from app.services.workspace_service import (
    delete_user_tool,
    list_user_tools,
    load_user_tool_metadata,
    read_user_tool,
    write_user_tool,
)
from sqlmodel import select

if TYPE_CHECKING:
    from sqlmodel import Session

ToolSourceType = Literal["builtin", "manual"]


def builtin_tool_key(tool_name: str) -> str:
    """Return the stable resource key for one built-in tool."""
    return f"builtin:{tool_name}"


def manual_tool_key(user_id: int, tool_name: str) -> str:
    """Return the stable resource key for one user-created tool."""
    return f"user:{user_id}:{tool_name}"


def _get_by_key(db: Session, key: str) -> ToolResource | None:
    return db.exec(select(ToolResource).where(ToolResource.key == key)).first()


def _get_by_name(
    db: Session,
    *,
    source_type: ToolSourceType,
    tool_name: str,
) -> ToolResource | None:
    return db.exec(
        select(ToolResource).where(
            ToolResource.source_type == source_type,
            ToolResource.name == tool_name,
        )
    ).first()


def ensure_builtin_tool_resource(db: Session, tool_name: str) -> ToolResource:
    """Ensure auth metadata exists for one built-in tool."""
    if get_tool_manager().get_tool(tool_name) is None:
        raise FileNotFoundError(f"Built-in tool '{tool_name}' not found.")

    key = builtin_tool_key(tool_name)
    tool = _get_by_key(db, key)
    if tool is None:
        tool = ToolResource(
            key=key,
            name=tool_name,
            source_type="builtin",
            creator_id=None,
            use_scope="all",
        )
    else:
        tool.name = tool_name
        tool.source_type = "builtin"
        tool.creator_id = None
        tool.use_scope = "all"
        tool.updated_at = datetime.now(UTC)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return tool


def ensure_manual_tool_resource(
    db: Session,
    *,
    owner: User,
    tool_name: str,
) -> ToolResource:
    """Ensure auth metadata exists for one user-created tool."""
    if owner.id is None:
        raise ValueError("Tool owner must be persisted.")
    read_user_tool(owner.username, tool_name)

    key = manual_tool_key(owner.id, tool_name)
    tool = _get_by_key(db, key)
    existing_by_name = _get_by_name(db, source_type="manual", tool_name=tool_name)
    if (
        existing_by_name is not None
        and existing_by_name.key != key
        and existing_by_name.creator_id != owner.id
    ):
        raise ValueError(f"Tool '{tool_name}' already exists.")
    if tool is None:
        tool = ToolResource(
            key=key,
            name=tool_name,
            source_type="manual",
            creator_id=owner.id,
            use_scope="all",
        )
    else:
        tool.name = tool_name
        tool.source_type = "manual"
        tool.creator_id = owner.id
        tool.updated_at = datetime.now(UTC)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    AccessService(db).grant_access(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
        principal_type=PrincipalType.USER,
        principal_id=owner.id,
        access_level=AccessLevel.EDIT,
    )
    return tool


def get_tool_resource(
    db: Session,
    *,
    current_user: User,
    source_type: ToolSourceType,
    tool_name: str,
) -> ToolResource:
    """Return auth metadata for one tool visible in the management UI."""
    if source_type == "builtin":
        return ensure_builtin_tool_resource(db, tool_name)
    tool = _get_by_name(db, source_type="manual", tool_name=tool_name)
    if tool is not None:
        return tool
    return ensure_manual_tool_resource(db, owner=current_user, tool_name=tool_name)


def require_tool_access(
    db: Session,
    *,
    current_user: User,
    tool: ToolResource,
    access_level: AccessLevel,
) -> None:
    """Raise unless the current user has the requested tool access."""
    if tool.source_type == "builtin":
        if access_level == AccessLevel.USE:
            return
        raise PermissionError("Built-in tools are read-only.")
    AccessService(db).require_resource_access(
        user=current_user,
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
        access_level=access_level,
        creator_user_id=tool.creator_id,
        use_scope=tool.use_scope,
    )


def _manual_tool_owner(db: Session, tool: ToolResource) -> User:
    if tool.creator_id is None:
        raise ValueError("Manual tools require a creator.")
    owner = db.get(User, tool.creator_id)
    if owner is None:
        raise ValueError("Tool creator not found.")
    return owner


def read_manual_tool_source(
    db: Session,
    *,
    current_user: User,
    tool: ToolResource,
) -> str:
    """Read one manual tool source when the current user has use access."""
    require_tool_access(
        db,
        current_user=current_user,
        tool=tool,
        access_level=AccessLevel.USE,
    )
    owner = _manual_tool_owner(db, tool)
    return read_user_tool(owner.username, tool.name)


def update_manual_tool_source(
    db: Session,
    *,
    current_user: User,
    tool: ToolResource,
    source: str,
) -> None:
    """Update one manual tool source when the current user has edit access."""
    require_tool_access(
        db,
        current_user=current_user,
        tool=tool,
        access_level=AccessLevel.EDIT,
    )
    owner = _manual_tool_owner(db, tool)
    write_user_tool(owner.username, tool.name, source)
    tool.updated_at = datetime.now(UTC)
    db.add(tool)
    db.commit()
    db.refresh(tool)


def create_manual_tool_source(
    db: Session,
    *,
    current_user: User,
    tool_name: str,
    source: str,
) -> ToolResource:
    """Create one manual tool source and initialize auth metadata."""
    write_user_tool(current_user.username, tool_name, source)
    return ensure_manual_tool_resource(db, owner=current_user, tool_name=tool_name)


def delete_manual_tool(
    db: Session,
    *,
    current_user: User,
    tool: ToolResource,
) -> None:
    """Delete one manual tool source and auth metadata with edit access."""
    require_tool_access(
        db,
        current_user=current_user,
        tool=tool,
        access_level=AccessLevel.EDIT,
    )
    owner = _manual_tool_owner(db, tool)
    delete_user_tool(owner.username, tool.name)
    AccessService(db)._delete_resource_grants_in_session(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
    )
    db.delete(tool)
    db.commit()


def set_tool_access(
    db: Session,
    *,
    tool: ToolResource,
    use_scope: str,
    use_user_ids: set[int],
    use_group_ids: set[int],
    edit_user_ids: set[int],
    edit_group_ids: set[int],
) -> None:
    """Replace use/edit access for one user-created tool."""
    if tool.source_type == "builtin":
        raise ValueError("Built-in tools are usable by everyone and cannot be edited.")
    if tool.creator_id is None:
        raise ValueError("Manual tools require a creator.")
    if use_scope not in {"all", "selected"}:
        raise ValueError("use_scope must be 'all' or 'selected'.")

    edit_user_ids = set(edit_user_ids)
    edit_user_ids.add(tool.creator_id)
    if use_scope == "selected":
        use_user_ids = set(use_user_ids)
        use_user_ids.add(tool.creator_id)

    tool.use_scope = use_scope
    tool.updated_at = datetime.now(UTC)
    db.add(tool)

    access_service = AccessService(db)
    access_service._replace_resource_grants_in_session(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
        access_level=AccessLevel.USE,
        user_ids=use_user_ids if use_scope == "selected" else set(),
        group_ids=use_group_ids if use_scope == "selected" else set(),
    )
    access_service._replace_resource_grants_in_session(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
        access_level=AccessLevel.EDIT,
        user_ids=edit_user_ids,
        group_ids=edit_group_ids,
    )
    db.commit()
    db.refresh(tool)


def delete_manual_tool_resource(
    db: Session,
    *,
    owner: User,
    tool_name: str,
) -> None:
    """Delete auth metadata for one user-created tool."""
    if owner.id is None:
        return
    key = manual_tool_key(owner.id, tool_name)
    tool = _get_by_key(db, key)
    if tool is None:
        return
    AccessService(db)._delete_resource_grants_in_session(
        resource_type=ResourceType.TOOL,
        resource_id=tool.key,
    )
    db.delete(tool)
    db.commit()


def list_usable_tools(db: Session, *, current_user: User) -> list[dict[str, object]]:
    """List tools the current Studio user can select for agents."""
    access_service = AccessService(db)
    rows: list[dict[str, object]] = []

    for entry in list_user_tools(current_user.username):
        tool_name = entry.get("name")
        if isinstance(tool_name, str):
            ensure_manual_tool_resource(db, owner=current_user, tool_name=tool_name)

    for metadata in get_tool_manager().list_tools():
        ensure_builtin_tool_resource(db, metadata.name)
        rows.append(
            {
                "name": metadata.name,
                "description": metadata.description,
                "parameters": metadata.parameters,
                "tool_type": metadata.tool_type,
                "source_type": "builtin",
                "read_only": True,
                "creator_id": None,
            }
        )

    statement = select(ToolResource).where(ToolResource.source_type == "manual")
    for tool in db.exec(statement).all():
        if not access_service.has_resource_access(
            user=current_user,
            resource_type=ResourceType.TOOL,
            resource_id=tool.key,
            access_level=AccessLevel.USE,
            creator_user_id=tool.creator_id,
            use_scope=tool.use_scope,
        ):
            continue
        if tool.creator_id is None:
            continue
        owner = db.get(User, tool.creator_id)
        if owner is None:
            continue
        metadata = load_user_tool_metadata(owner.username, tool.name)
        can_edit = access_service.has_resource_access(
            user=current_user,
            resource_type=ResourceType.TOOL,
            resource_id=tool.key,
            access_level=AccessLevel.EDIT,
            creator_user_id=tool.creator_id,
            use_scope=tool.use_scope,
        )
        rows.append(
            {
                "name": tool.name,
                "description": metadata.description if metadata is not None else "",
                "parameters": metadata.parameters if metadata is not None else {},
                "tool_type": metadata.tool_type if metadata is not None else "normal",
                "source_type": "manual",
                "read_only": not can_edit,
                "creator_id": tool.creator_id,
            }
        )

    return sorted(rows, key=lambda row: str(row["name"]))
