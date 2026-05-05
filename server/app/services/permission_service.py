"""Services for role, permission, and system-permission checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.access import PermissionRecord, Role, RolePermission
from app.security.permission_catalog import (
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSION_METADATA,
    Permission,
)
from fastapi import HTTPException, status
from sqlmodel import col, select

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session as DBSession


class PermissionService:
    """CRUD-style service for permissions and role bindings."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def seed_defaults(self) -> None:
        """Create the built-in permission catalog and default roles."""
        permission_by_key = self._seed_permissions()
        self._seed_roles(permission_by_key)

    def _seed_permissions(self) -> dict[str, PermissionRecord]:
        permission_by_key: dict[str, PermissionRecord] = {
            permission.key: permission
            for permission in self.db.exec(select(PermissionRecord)).all()
        }
        for permission in Permission:
            metadata = PERMISSION_METADATA[permission]
            record = permission_by_key.get(permission.value)
            if record is None:
                record = PermissionRecord(
                    key=permission.value,
                    name=metadata["name"],
                    description=metadata["description"],
                    category=metadata["category"],
                    is_system=True,
                )
            else:
                record.name = metadata["name"]
                record.description = metadata["description"]
                record.category = metadata["category"]
                record.is_system = True
            self.db.add(record)
            permission_by_key[permission.value] = record
        self.db.commit()
        for record in permission_by_key.values():
            self.db.refresh(record)
        return permission_by_key

    def _seed_roles(self, permission_by_key: dict[str, PermissionRecord]) -> None:
        role_metadata = {
            "user": ("User", "Client-only user."),
            "builder": ("Builder", "Studio builder with scoped resource access."),
            "admin": ("Admin", "System administrator."),
        }
        role_by_key = {role.key: role for role in self.db.exec(select(Role)).all()}
        for role_key, (name, description) in role_metadata.items():
            role = role_by_key.get(role_key)
            if role is None:
                role = Role(
                    key=role_key,
                    name=name,
                    description=description,
                    is_system=True,
                )
            else:
                role.name = name
                role.description = description
                role.is_system = True
                role.updated_at = datetime.now(UTC)
            self.db.add(role)
            role_by_key[role_key] = role
        self.db.commit()
        for role in role_by_key.values():
            self.db.refresh(role)

        for role_key, permissions in DEFAULT_ROLE_PERMISSIONS.items():
            role = role_by_key[role_key]
            if role.id is None:
                continue
            existing = self.db.exec(
                select(RolePermission).where(RolePermission.role_id == role.id)
            ).all()
            for row in existing:
                self.db.delete(row)
            for permission in permissions:
                permission_record = permission_by_key[permission.value]
                if permission_record.id is None:
                    continue
                self.db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission_record.id,
                    )
                )
        self.db.commit()

    def get_role_by_key(self, role_key: str) -> Role | None:
        """Return one role by stable key."""
        return self.db.exec(select(Role).where(Role.key == role_key)).first()

    def get_required_role(self, role_id: int) -> Role:
        """Return one role by id or raise."""
        role = self.db.get(Role, role_id)
        if role is None:
            raise ValueError("Role not found")
        return role

    def list_permissions(self) -> list[PermissionRecord]:
        """List all backend-supported permissions."""
        statement = select(PermissionRecord).order_by(
            col(PermissionRecord.category),
            col(PermissionRecord.key),
        )
        return list(self.db.exec(statement).all())

    def list_roles(self) -> list[Role]:
        """List all roles."""
        statement = select(Role).order_by(col(Role.is_system).desc(), col(Role.key))
        return list(self.db.exec(statement).all())

    def create_role(
        self,
        *,
        key: str,
        name: str,
        description: str = "",
        permission_keys: set[Permission] | None = None,
    ) -> Role:
        """Create one custom role."""
        existing = self.get_role_by_key(key)
        if existing is not None:
            raise ValueError("Role key already exists")
        role = Role(
            key=key,
            name=name,
            description=description,
            is_system=False,
        )
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        if permission_keys is not None and role.id is not None:
            self.set_role_permissions(role_id=role.id, permission_keys=permission_keys)
            self.db.refresh(role)
        return role

    def update_role(
        self,
        *,
        role_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> Role | None:
        """Update editable role metadata."""
        role = self.db.get(Role, role_id)
        if role is None:
            return None
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        role.updated_at = datetime.now(UTC)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def get_role_permission_keys(self, role_id: int) -> set[str]:
        """Return permission keys assigned to one role."""
        permission_ids = [
            row.permission_id
            for row in self.db.exec(
                select(RolePermission).where(RolePermission.role_id == role_id)
            ).all()
        ]
        if not permission_ids:
            return set()

        statement = select(PermissionRecord.key).where(
            col(PermissionRecord.id).in_(permission_ids)
        )
        return set(self.db.exec(statement).all())

    def get_user_permission_keys(self, user: User) -> set[str]:
        """Return effective permission keys for one user."""
        role = self.db.get(Role, user.role_id)
        if role is None:
            return set()
        if role.key == "admin":
            return {permission.value for permission in Permission}
        return self.get_role_permission_keys(role.id or 0)

    def set_role_permissions(
        self,
        *,
        role_id: int,
        permission_keys: set[Permission],
    ) -> Role:
        """Replace a role's permission bindings."""
        role = self.get_required_role(role_id)
        if role.key == "admin":
            permission_keys = set(Permission)

        existing = self.db.exec(
            select(RolePermission).where(RolePermission.role_id == role_id)
        ).all()
        for row in existing:
            self.db.delete(row)

        permission_records = {
            record.key: record
            for record in self.db.exec(select(PermissionRecord)).all()
            if record.id is not None
        }
        for permission in permission_keys:
            record = permission_records[permission.value]
            if record.id is not None:
                self.db.add(RolePermission(role_id=role_id, permission_id=record.id))

        role.updated_at = datetime.now(UTC)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def has_permissions(
        self,
        user: User,
        required_permissions: tuple[Permission, ...],
    ) -> bool:
        """Return whether a user has every requested system permission."""
        if user.status != "active":
            return False
        role = self.db.get(Role, user.role_id)
        if role is None:
            return False
        if role.key == "admin":
            return True
        permission_keys = self.get_role_permission_keys(role.id or 0)
        return all(
            permission.value in permission_keys for permission in required_permissions
        )

    def require_permissions(
        self,
        user: User,
        required_permissions: tuple[Permission, ...],
    ) -> None:
        """Raise 403 unless the user has every requested system permission."""
        if self.has_permissions(user, required_permissions):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )
