"""FastAPI dependencies for system permission checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.services.permission_service import PermissionService
from fastapi import Depends

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.user import User
    from app.security.permission_catalog import Permission
    from sqlmodel import Session as DBSession


def permissions(*required_permissions: Permission) -> Callable[..., User]:
    """Return a dependency that requires every given system permission."""

    def dependency(
        current_user: User = Depends(get_current_user),
        db: DBSession = Depends(get_db),
    ) -> User:
        PermissionService(db).require_permissions(current_user, required_permissions)
        return current_user

    return dependency
