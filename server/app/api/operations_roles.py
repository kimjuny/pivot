"""Operations APIs for role and permission administration."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.schemas.base import AppBaseModel
from app.security.permission_catalog import Permission
from app.services.permission_service import PermissionService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

if TYPE_CHECKING:
    from app.models.access import PermissionRecord, Role
    from app.models.user import User
    from sqlmodel import Session as DBSession

router = APIRouter()


class PermissionResponse(AppBaseModel):
    """Permission catalog payload."""

    key: str
    name: str
    description: str
    category: str


class RoleResponse(AppBaseModel):
    """Role payload with permission keys."""

    id: int
    key: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]
    created_at: str
    updated_at: str


class RoleCreate(AppBaseModel):
    """Create-role payload."""

    key: str
    name: str
    description: str = ""
    permissions: list[Permission] = Field(default_factory=list)


class RoleUpdate(AppBaseModel):
    """Role metadata update payload."""

    name: str | None = None
    description: str | None = None


class RolePermissionsUpdate(AppBaseModel):
    """Replace-role-permissions payload."""

    permissions: list[Permission]


def _serialize_permission(permission: PermissionRecord) -> PermissionResponse:
    return PermissionResponse(
        key=permission.key,
        name=permission.name,
        description=permission.description,
        category=permission.category,
    )


def _serialize_role(role: Role, service: PermissionService) -> RoleResponse:
    return RoleResponse(
        id=role.id or 0,
        key=role.key,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=sorted(service.get_role_permission_keys(role.id or 0)),
        created_at=role.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=role.updated_at.replace(tzinfo=UTC).isoformat(),
    )


@router.get("/operations/permissions", response_model=list[PermissionResponse])
async def list_operations_permissions(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.ROLES_MANAGE)),
) -> list[PermissionResponse]:
    """List backend-supported permissions."""
    del current_user
    return [
        _serialize_permission(permission)
        for permission in PermissionService(db).list_permissions()
    ]


@router.get("/operations/roles", response_model=list[RoleResponse])
async def list_operations_roles(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.ROLES_MANAGE)),
) -> list[RoleResponse]:
    """List roles with their permission keys."""
    del current_user
    service = PermissionService(db)
    return [_serialize_role(role, service) for role in service.list_roles()]


@router.post("/operations/roles", response_model=RoleResponse, status_code=201)
async def create_operations_role(
    payload: RoleCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.ROLES_MANAGE)),
) -> RoleResponse:
    """Create one custom role."""
    del current_user
    service = PermissionService(db)
    try:
        role = service.create_role(
            key=payload.key,
            name=payload.name,
            description=payload.description,
            permission_keys=set(payload.permissions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_role(role, service)


@router.patch("/operations/roles/{role_id}", response_model=RoleResponse)
async def update_operations_role(
    role_id: int,
    payload: RoleUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.ROLES_MANAGE)),
) -> RoleResponse:
    """Update role metadata."""
    del current_user
    service = PermissionService(db)
    role = service.update_role(
        role_id=role_id,
        name=payload.name,
        description=payload.description,
    )
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return _serialize_role(role, service)


@router.put("/operations/roles/{role_id}/permissions", response_model=RoleResponse)
async def update_operations_role_permissions(
    role_id: int,
    payload: RolePermissionsUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.ROLES_MANAGE)),
) -> RoleResponse:
    """Replace one role's permissions."""
    del current_user
    service = PermissionService(db)
    try:
        role = service.set_role_permissions(
            role_id=role_id,
            permission_keys=set(payload.permissions),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _serialize_role(role, service)
