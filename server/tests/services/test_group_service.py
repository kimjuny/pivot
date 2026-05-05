"""Tests for group administration service."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

access_models = import_module("app.models.access")
user_models = import_module("app.models.user")
group_service_module = import_module("app.services.group_service")
permission_service_module = import_module("app.services.permission_service")

AccessLevel = access_models.AccessLevel
PrincipalType = access_models.PrincipalType
ResourceAccess = access_models.ResourceAccess
ResourceType = access_models.ResourceType
Role = access_models.Role
User = user_models.User
GroupService = group_service_module.GroupService
PermissionService = permission_service_module.PermissionService


class GroupServiceTestCase(unittest.TestCase):
    """Verify group CRUD and membership behavior."""

    def setUp(self) -> None:
        """Create one isolated database."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()
        role = self.session.exec(select(Role).where(Role.key == "user")).one()
        self.alice = User(username="alice", password_hash="hash", role_id=role.id or 0)
        self.bob = User(username="bob", password_hash="hash", role_id=role.id or 0)
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.alice)
        self.session.refresh(self.bob)

    def tearDown(self) -> None:
        """Close the session."""
        self.session.close()

    def test_replace_members(self) -> None:
        """Replacing members should persist the exact selected set."""
        service = GroupService(self.session)
        group = service.create_group(name="Design", description="Product designers")

        members = service.replace_members(
            group_id=group.id or 0,
            user_ids={self.alice.id or 0, self.bob.id or 0},
        )
        self.assertEqual({member.username for member in members}, {"alice", "bob"})

        members = service.replace_members(
            group_id=group.id or 0,
            user_ids={self.alice.id or 0},
        )
        self.assertEqual([member.username for member in members], ["alice"])

    def test_delete_group_removes_members_and_grants(self) -> None:
        """Deleting a group should remove memberships and direct resource grants."""
        service = GroupService(self.session)
        group = service.create_group(name="Builders")
        group_id = group.id or 0
        service.replace_members(group_id=group_id, user_ids={self.alice.id or 0})
        self.session.add(
            ResourceAccess(
                resource_type=ResourceType.AGENT,
                resource_id="1",
                principal_type=PrincipalType.GROUP,
                principal_id=str(group_id),
                access_level=AccessLevel.USE,
            )
        )
        self.session.commit()

        self.assertTrue(service.delete_group(group_id))
        self.assertEqual(service.list_members(group_id), [])
        grants = self.session.exec(select(ResourceAccess)).all()
        self.assertEqual(grants, [])


if __name__ == "__main__":
    unittest.main()
