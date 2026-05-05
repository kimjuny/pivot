"""API tests for Studio skill selector access."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
access_models = import_module("app.models.access")
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
permission_catalog_module = import_module("app.security.permission_catalog")
permission_service_module = import_module("app.services.permission_service")
skill_api_module = import_module("app.api.skills")
skill_models = import_module("app.models.skill")
skill_service_module = import_module("app.services.skill_service")
user_models = import_module("app.models.user")
access_service_module = import_module("app.services.access_service")

AccessLevel = access_models.AccessLevel
AccessService = access_service_module.AccessService
Permission = permission_catalog_module.Permission
PermissionService = permission_service_module.PermissionService
PrincipalType = access_models.PrincipalType
ResourceType = access_models.ResourceType
Skill = skill_models.Skill
User = user_models.User

if TYPE_CHECKING:
    from collections.abc import Generator


class SkillUsableApiTestCase(unittest.TestCase):
    """Verify agent skill selectors use resource use grants."""

    def setUp(self) -> None:
        """Create one isolated test app and database."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        permission_service = PermissionService(self.session)
        permission_service.seed_defaults()
        agent_role = permission_service.create_role(
            key="agent-manager",
            name="Agent Manager",
            permission_keys={Permission.AGENTS_MANAGE},
        )
        self.alice = User(
            username="alice",
            password_hash="hash",
            role_id=agent_role.id or 0,
        )
        self.bob = User(
            username="bob",
            password_hash="hash",
            role_id=agent_role.id or 0,
        )
        self.session.add(self.alice)
        self.session.add(self.bob)
        self.session.commit()
        self.session.refresh(self.alice)
        self.session.refresh(self.bob)
        self.current_user = self.bob

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.workspace_root_patch = patch.object(
            skill_service_module,
            "workspace_root",
            return_value=self.root,
        )
        self.workspace_root_patch.start()

        self.app = FastAPI()
        self.app.include_router(skill_api_module.router)
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release app and database resources."""
        self.client.close()
        self.app.dependency_overrides.clear()
        self.workspace_root_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _get_db(self) -> Generator[Session, None, None]:
        """Yield the shared database session for the test API app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the active user configured by each test."""
        return self.current_user

    def _create_private_skill(self) -> Skill:
        skill_dir = self.root / "users" / "alice" / "skills" / "private-research"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: private-research\n"
            "description: Private research workflow\n"
            "---\n\n"
            "# private-research\n",
            encoding="utf-8",
        )
        now = datetime.now(UTC)
        skill = Skill(
            name="private-research",
            description="Private research workflow",
            kind="private",
            use_scope="selected",
            source="manual",
            creator_id=self.alice.id,
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

    def test_agent_manager_can_select_private_skill_with_use_grant(self) -> None:
        """Use-only private skills should appear in the agent skill selector."""
        skill = self._create_private_skill()
        AccessService(self.session).grant_access(
            resource_type=ResourceType.SKILL,
            resource_id=skill.id or 0,
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.USE,
        )

        response = self.client.get("/skills/usable")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["name"] for item in payload], ["private-research"])
        self.assertEqual(payload[0]["kind"], "private")
        self.assertTrue(payload[0]["read_only"])

        response = self.client.get("/skills/private")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
