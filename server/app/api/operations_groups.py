"""Operations APIs for group administration."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.schemas.base import AppBaseModel
from app.security.permission_catalog import Permission
from app.services.group_service import GroupService
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, Response

if TYPE_CHECKING:
    from app.models.access import UserGroup
    from app.models.user import User
    from sqlmodel import Session as DBSession

router = APIRouter()


class OperationsGroupResponse(AppBaseModel):
    """Group payload for Operations administration."""

    id: int
    name: str
    description: str
    created_by_user_id: int | None
    member_count: int
    created_at: str
    updated_at: str


class OperationsGroupCreate(AppBaseModel):
    """Create-group payload."""

    name: str
    description: str = ""


class OperationsGroupUpdate(AppBaseModel):
    """Update-group payload."""

    name: str | None = None
    description: str | None = None


class OperationsGroupMemberResponse(AppBaseModel):
    """One group member user."""

    id: int
    username: str
    status: str
    display_name: str | None
    email: str | None


class OperationsGroupMembersUpdate(AppBaseModel):
    """Replace group members payload."""

    user_ids: list[int]


def _serialize_group(
    group: UserGroup,
    member_counts: dict[int, int],
) -> OperationsGroupResponse:
    return OperationsGroupResponse(
        id=group.id or 0,
        name=group.name,
        description=group.description,
        created_by_user_id=group.created_by_user_id,
        member_count=member_counts.get(group.id or 0, 0),
        created_at=group.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=group.updated_at.replace(tzinfo=UTC).isoformat(),
    )


def _serialize_member(user: User) -> OperationsGroupMemberResponse:
    return OperationsGroupMemberResponse(
        id=user.id or 0,
        username=user.username,
        status=user.status,
        display_name=user.display_name,
        email=user.email,
    )


@router.get("/operations/groups", response_model=list[OperationsGroupResponse])
async def list_operations_groups(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> list[OperationsGroupResponse]:
    """List groups for Operations administration."""
    del current_user
    service = GroupService(db)
    member_counts = service.get_member_count_by_group_id()
    return [_serialize_group(group, member_counts) for group in service.list_groups()]


@router.post(
    "/operations/groups",
    response_model=OperationsGroupResponse,
    status_code=201,
)
async def create_operations_group(
    payload: OperationsGroupCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> OperationsGroupResponse:
    """Create one group."""
    try:
        group = GroupService(db).create_group(
            name=payload.name,
            description=payload.description,
            created_by_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_group(group, {})


@router.get(
    "/operations/groups/user-options",
    response_model=list[OperationsGroupMemberResponse],
)
async def list_operations_group_user_options(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> list[OperationsGroupMemberResponse]:
    """List users selectable as group members."""
    del current_user
    return [
        _serialize_member(user)
        for user in UserService(db).list_users()
        if user.status == "active"
    ]


@router.patch(
    "/operations/groups/{group_id}",
    response_model=OperationsGroupResponse,
)
async def update_operations_group(
    group_id: int,
    payload: OperationsGroupUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> OperationsGroupResponse:
    """Update one group."""
    del current_user
    try:
        group = GroupService(db).update_group(
            group_id=group_id,
            name=payload.name,
            description=payload.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return _serialize_group(group, GroupService(db).get_member_count_by_group_id())


@router.delete("/operations/groups/{group_id}", status_code=204)
async def delete_operations_group(
    group_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> Response:
    """Delete one group."""
    del current_user
    deleted = GroupService(db).delete_group(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    return Response(status_code=204)


@router.get(
    "/operations/groups/{group_id}/members",
    response_model=list[OperationsGroupMemberResponse],
)
async def list_operations_group_members(
    group_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> list[OperationsGroupMemberResponse]:
    """List members for one group."""
    del current_user
    if GroupService(db).get_group(group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return [_serialize_member(user) for user in GroupService(db).list_members(group_id)]


@router.put(
    "/operations/groups/{group_id}/members",
    response_model=list[OperationsGroupMemberResponse],
)
async def update_operations_group_members(
    group_id: int,
    payload: OperationsGroupMembersUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.GROUPS_MANAGE)),
) -> list[OperationsGroupMemberResponse]:
    """Replace members for one group."""
    del current_user
    try:
        members = GroupService(db).replace_members(
            group_id=group_id,
            user_ids=set(payload.user_ids),
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return [_serialize_member(user) for user in members]
