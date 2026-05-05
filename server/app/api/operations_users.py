"""Operations APIs for user administration."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import Role
from app.schemas.base import AppBaseModel
from app.security.permission_catalog import Permission
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session as DBSession

router = APIRouter()


class OperationsUserResponse(AppBaseModel):
    """User payload for Operations administration."""

    id: int
    username: str
    role_id: int
    role_key: str
    status: str
    display_name: str | None
    email: str | None
    created_at: str
    updated_at: str


class OperationsUserCreate(AppBaseModel):
    """Create-user payload."""

    username: str
    password: str
    role_id: int
    display_name: str | None = None
    email: str | None = None


class OperationsUserUpdate(AppBaseModel):
    """Administrative user update payload."""

    role_id: int | None = None
    status: str | None = None
    display_name: str | None = None
    email: str | None = None


def _role_keys_by_id(db: DBSession) -> dict[int, str]:
    return {
        role.id: role.key for role in db.exec(select(Role)).all() if role.id is not None
    }


def _serialize_user(user: User, role_keys: dict[int, str]) -> OperationsUserResponse:
    return OperationsUserResponse(
        id=user.id or 0,
        username=user.username,
        role_id=user.role_id,
        role_key=role_keys.get(user.role_id, "unknown"),
        status=user.status,
        display_name=user.display_name,
        email=user.email,
        created_at=user.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=user.updated_at.replace(tzinfo=UTC).isoformat(),
    )


@router.get("/operations/users", response_model=list[OperationsUserResponse])
async def list_operations_users(
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.USERS_MANAGE)),
) -> list[OperationsUserResponse]:
    """List users for Operations administration."""
    del current_user
    role_keys = _role_keys_by_id(db)
    return [_serialize_user(user, role_keys) for user in UserService(db).list_users()]


@router.post(
    "/operations/users",
    response_model=OperationsUserResponse,
    status_code=201,
)
async def create_operations_user(
    payload: OperationsUserCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.USERS_MANAGE)),
) -> OperationsUserResponse:
    """Create one user."""
    del current_user
    try:
        user = UserService(db).create_user(
            username=payload.username,
            password=payload.password,
            role_id=payload.role_id,
            display_name=payload.display_name,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_user(user, _role_keys_by_id(db))


@router.patch("/operations/users/{user_id}", response_model=OperationsUserResponse)
async def update_operations_user(
    user_id: int,
    payload: OperationsUserUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.USERS_MANAGE)),
) -> OperationsUserResponse:
    """Update one user's role or status."""
    del current_user
    try:
        user = UserService(db).update_user(
            user_id=user_id,
            role_id=payload.role_id,
            status=payload.status,
            display_name=payload.display_name,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _serialize_user(user, _role_keys_by_id(db))
