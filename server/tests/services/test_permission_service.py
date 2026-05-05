"""Tests for role and permission services."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

access_models = import_module("app.models.access")
user_models = import_module("app.models.user")
permission_catalog = import_module("app.security.permission_catalog")
permission_service_module = import_module("app.services.permission_service")
user_service_module = import_module("app.services.user_service")

Role = access_models.Role
User = user_models.User
Permission = permission_catalog.Permission
PermissionService = permission_service_module.PermissionService
UserService = user_service_module.UserService


class PermissionServiceTestCase(unittest.TestCase):
    """Verify default role seeding and permission checks."""

    def setUp(self) -> None:
        """Create one isolated in-memory database."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()

    def tearDown(self) -> None:
        """Close the test session."""
        self.session.close()

    def test_default_admin_user_is_seeded_with_admin_role(self) -> None:
        """The default development user should be an admin."""
        user = UserService(self.session).ensure_default_admin()
        role = self.session.get(Role, user.role_id)

        self.assertEqual(user.username, "default")
        self.assertEqual(user.status, "active")
        self.assertIsNotNone(role)
        self.assertEqual(role.key if role else None, "admin")
        self.assertTrue(
            PermissionService(self.session).has_permissions(
                user,
                (Permission.ROLES_MANAGE, Permission.USERS_MANAGE),
            )
        )

    def test_builder_has_scoped_studio_permissions(self) -> None:
        """Builder should have Studio and agent permissions but not role admin."""
        builder_role = self.session.exec(
            select(Role).where(Role.key == "builder")
        ).one()
        user = User(
            username="builder",
            password_hash="hash",
            role_id=builder_role.id or 0,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)

        service = PermissionService(self.session)

        self.assertTrue(
            service.has_permissions(
                user,
                (
                    Permission.STUDIO_ACCESS,
                    Permission.AGENTS_MANAGE,
                    Permission.STORAGE_VIEW,
                ),
            )
        )
        self.assertFalse(service.has_permissions(user, (Permission.ROLES_MANAGE,)))

    def test_disabled_user_is_denied(self) -> None:
        """Disabled users should fail system permission checks."""
        user = UserService(self.session).ensure_default_admin()
        user.status = "disabled"
        self.session.add(user)
        self.session.commit()

        with self.assertRaises(HTTPException):
            PermissionService(self.session).require_permissions(
                user,
                (Permission.USERS_MANAGE,),
            )


if __name__ == "__main__":
    unittest.main()
