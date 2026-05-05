"""Tests for resource-level access decisions."""

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
agent_models = import_module("app.models.agent")
user_models = import_module("app.models.user")
permission_service_module = import_module("app.services.permission_service")
user_service_module = import_module("app.services.user_service")
access_service_module = import_module("app.services.access_service")
group_service_module = import_module("app.services.group_service")

AccessLevel = access_models.AccessLevel
Agent = agent_models.Agent
PrincipalType = access_models.PrincipalType
ResourceType = access_models.ResourceType
Role = access_models.Role
User = user_models.User
PermissionService = permission_service_module.PermissionService
UserService = user_service_module.UserService
AccessService = access_service_module.AccessService
GroupService = group_service_module.GroupService


class AccessServiceTestCase(unittest.TestCase):
    """Verify agent use/edit access rules."""

    def setUp(self) -> None:
        """Create one clean in-memory database."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()
        self.admin = UserService(self.session).ensure_default_admin()
        user_role = self.session.exec(select(Role).where(Role.key == "user")).one()
        self.alice = User(
            username="alice", password_hash="hash", role_id=user_role.id or 0
        )
        self.bob = User(username="bob", password_hash="hash", role_id=user_role.id or 0)
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.alice)
        self.session.refresh(self.bob)

    def tearDown(self) -> None:
        """Close the test session."""
        self.session.close()

    def test_creator_edit_access_includes_use(self) -> None:
        """Creator edit grants should imply use access."""
        agent = Agent(name="creator-agent", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        service = AccessService(self.session)
        service.grant_creator_edit(agent=agent, user=self.alice)

        self.assertTrue(
            service.has_agent_access(
                user=self.alice,
                agent=agent,
                access_level=AccessLevel.EDIT,
            )
        )
        self.assertTrue(
            service.has_agent_access(
                user=self.alice,
                agent=agent,
                access_level=AccessLevel.USE,
            )
        )
        self.assertFalse(
            service.has_agent_access(
                user=self.bob,
                agent=agent,
                access_level=AccessLevel.USE,
            )
        )

    def test_use_scope_all_does_not_grant_edit(self) -> None:
        """All-user visibility should not grant management access."""
        agent = Agent(
            name="public-agent",
            llm_id=None,
            created_by_user_id=self.alice.id,
            use_scope="all",
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        service = AccessService(self.session)

        self.assertTrue(
            service.has_agent_access(
                user=self.bob,
                agent=agent,
                access_level=AccessLevel.USE,
            )
        )
        self.assertFalse(
            service.has_agent_access(
                user=self.bob,
                agent=agent,
                access_level=AccessLevel.EDIT,
            )
        )

    def test_set_agent_access_replaces_grants_and_keeps_creator(self) -> None:
        """Access updates should keep creator in selected use/edit grants."""
        agent = Agent(
            name="shared-agent",
            llm_id=None,
            created_by_user_id=self.alice.id,
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        alice_id = self.alice.id or 0
        bob_id = self.bob.id or 0

        service = AccessService(self.session)
        service.set_agent_access(
            agent=agent,
            use_scope="selected",
            use_user_ids={bob_id},
            use_group_ids=set(),
            edit_user_ids=set(),
            edit_group_ids=set(),
        )

        grants = service.list_resource_grants(
            resource_type=ResourceType.AGENT,
            resource_id=agent.id or 0,
        )
        use_user_ids = {
            int(grant.principal_id)
            for grant in grants
            if grant.access_level == AccessLevel.USE
            and grant.principal_type == PrincipalType.USER
        }
        edit_user_ids = {
            int(grant.principal_id)
            for grant in grants
            if grant.access_level == AccessLevel.EDIT
            and grant.principal_type == PrincipalType.USER
        }

        self.assertEqual(use_user_ids, {alice_id, bob_id})
        self.assertEqual(edit_user_ids, {alice_id})
        self.assertTrue(
            service.has_agent_access(
                user=self.bob,
                agent=agent,
                access_level=AccessLevel.USE,
            )
        )
        self.assertFalse(
            service.has_agent_access(
                user=self.bob,
                agent=agent,
                access_level=AccessLevel.EDIT,
            )
        )

    def test_admin_can_access_any_agent(self) -> None:
        """Admin should bypass resource grants."""
        agent = Agent(name="locked-agent", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)

        self.assertTrue(
            AccessService(self.session).has_agent_access(
                user=self.admin,
                agent=agent,
                access_level=AccessLevel.EDIT,
            )
        )

    def test_generic_resource_access_supports_creator_all_and_edit_implies_use(
        self,
    ) -> None:
        """Generic checks should match the use/edit semantics used by agents."""
        service = AccessService(self.session)

        self.assertTrue(
            service.has_resource_access(
                user=self.alice,
                resource_type=ResourceType.SKILL,
                resource_id="skill-1",
                access_level=AccessLevel.EDIT,
                creator_user_id=self.alice.id,
            )
        )
        self.assertTrue(
            service.has_resource_access(
                user=self.bob,
                resource_type=ResourceType.SKILL,
                resource_id="skill-1",
                access_level=AccessLevel.USE,
                use_scope="all",
            )
        )

        service.grant_access(
            resource_type=ResourceType.SKILL,
            resource_id="skill-2",
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.EDIT,
        )

        self.assertTrue(
            service.has_resource_access(
                user=self.bob,
                resource_type=ResourceType.SKILL,
                resource_id="skill-2",
                access_level=AccessLevel.USE,
            )
        )

    def test_generic_resource_access_supports_group_grants(self) -> None:
        """Group grants should apply through the generic resource access path."""
        group = GroupService(self.session).create_group(
            name="Designers",
            description="",
            created_by_user_id=self.alice.id,
        )
        GroupService(self.session).replace_members(
            group_id=group.id or 0,
            user_ids={self.bob.id or 0},
        )

        AccessService(self.session).grant_access(
            resource_type=ResourceType.TOOL,
            resource_id="tool-1",
            principal_type=PrincipalType.GROUP,
            principal_id=group.id or 0,
            access_level=AccessLevel.USE,
        )

        self.assertTrue(
            AccessService(self.session).has_resource_access(
                user=self.bob,
                resource_type=ResourceType.TOOL,
                resource_id="tool-1",
                access_level=AccessLevel.USE,
            )
        )


if __name__ == "__main__":
    unittest.main()
