"""Tests for skill visibility through generic resource access."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
access_models = import_module("app.models.access")
skill_models = import_module("app.models.skill")
user_models = import_module("app.models.user")
access_service_module = import_module("app.services.access_service")
permission_service_module = import_module("app.services.permission_service")
skill_service_module = import_module("app.services.skill_service")

AccessLevel = access_models.AccessLevel
PrincipalType = access_models.PrincipalType
ResourceType = access_models.ResourceType
Role = access_models.Role
Skill = skill_models.Skill
User = user_models.User
AccessService = access_service_module.AccessService
PermissionService = permission_service_module.PermissionService


class SkillAccessServiceTestCase(unittest.TestCase):
    """Verify skill list/read helpers honor generic use/edit access."""

    def setUp(self) -> None:
        """Create a clean database and skill directory."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()
        user_role = self.session.exec(select(Role).where(Role.key == "user")).one()
        self.alice = User(
            username="alice",
            password_hash="hash",
            role_id=user_role.id or 0,
        )
        self.bob = User(
            username="bob",
            password_hash="hash",
            role_id=user_role.id or 0,
        )
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.alice)
        self.session.refresh(self.bob)

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.workspace_root_patch = patch.object(
            skill_service_module,
            "workspace_root",
            return_value=self.root,
        )
        self.workspace_root_patch.start()

    def tearDown(self) -> None:
        """Release resources."""
        self.workspace_root_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _create_skill(self, *, name: str, kind: str, creator_id: int) -> Skill:
        skill_dir = self.root / "users" / "alice" / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {name}\n---\nBody",
            encoding="utf-8",
        )
        now = datetime.now(UTC)
        skill = Skill(
            name=name,
            description=name,
            kind=kind,
            use_scope="all" if kind == "shared" else "selected",
            source="manual",
            creator_id=creator_id,
            location=str(skill_dir),
            filename="SKILL.md",
            md5="0" * 32,
            created_at=now,
            updated_at=now,
        )
        self.session.add(skill)
        self.session.commit()
        self.session.refresh(skill)
        return skill

    def test_shared_skill_is_visible_but_read_only_for_non_creator(self) -> None:
        """Shared skills should map to all-user use access."""
        self._create_skill(
            name="shared-skill",
            kind="shared",
            creator_id=self.alice.id or 0,
        )

        visible = skill_service_module.list_visible_skills(self.session, "bob")
        payload = skill_service_module.read_shared_skill(
            self.session,
            "bob",
            "shared-skill",
        )

        self.assertEqual([item["name"] for item in visible], ["shared-skill"])
        self.assertTrue(payload["metadata"]["read_only"])

    def test_private_skill_requires_selected_use_grant(self) -> None:
        """Private skills should only be visible through creator or grants."""
        skill = self._create_skill(
            name="private-skill",
            kind="private",
            creator_id=self.alice.id or 0,
        )

        self.assertEqual(skill_service_module.list_visible_skills(self.session, "bob"), [])

        AccessService(self.session).grant_access(
            resource_type=ResourceType.SKILL,
            resource_id=skill.id or 0,
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.USE,
        )

        visible = skill_service_module.list_visible_skills(self.session, "bob")

        self.assertEqual([item["name"] for item in visible], ["private-skill"])
        self.assertTrue(visible[0]["read_only"])

    def test_edit_grant_allows_private_skill_edit_read(self) -> None:
        """Edit grants should allow source reads through the writable endpoint."""
        skill = self._create_skill(
            name="editable-skill",
            kind="private",
            creator_id=self.alice.id or 0,
        )
        AccessService(self.session).grant_access(
            resource_type=ResourceType.SKILL,
            resource_id=skill.id or 0,
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.EDIT,
        )

        payload = skill_service_module.read_user_skill(
            self.session,
            "bob",
            "private",
            "editable-skill",
        )

        self.assertFalse(payload["metadata"]["read_only"])
        self.assertIn("Body", payload["source"])


if __name__ == "__main__":
    unittest.main()
