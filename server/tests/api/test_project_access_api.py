"""API tests for project-level use/edit access."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
access_models = import_module("app.models.access")
agent_models = import_module("app.models.agent")
user_models = import_module("app.models.user")
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
projects_api_module = import_module("app.api.projects")
permission_service_module = import_module("app.services.permission_service")
project_service_module = import_module("app.services.project_service")
workspace_service_module = import_module("app.services.workspace_service")
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider

AccessLevel = access_models.AccessLevel
Agent = agent_models.Agent
PermissionService = permission_service_module.PermissionService
ProjectService = project_service_module.ProjectService
ResourceAccess = access_models.ResourceAccess
ResourceType = access_models.ResourceType
Role = access_models.Role
User = user_models.User

if TYPE_CHECKING:
    from collections.abc import Generator


class ProjectAccessApiTestCase(unittest.TestCase):
    """Verify project sharing API behavior."""

    def setUp(self) -> None:
        """Create one isolated test app, database, and workspace root."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        PermissionService(self.session).seed_defaults()

        self.tmpdir = tempfile.TemporaryDirectory()
        resolved_profile = type(
            "ResolvedProfile",
            (),
            {
                "posix_workspace": LocalFilesystemPOSIXWorkspaceProvider(
                    Path(self.tmpdir.name)
                ),
            },
        )()
        self.workspace_profile_patch = patch.object(
            cast(Any, workspace_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.workspace_profile_patch.start()

        user_role = self.session.exec(select(Role).where(Role.key == "user")).one()
        self.owner = User(
            username="owner",
            password_hash="hash",
            role_id=user_role.id or 0,
        )
        self.collaborator = User(
            username="collaborator",
            password_hash="hash",
            role_id=user_role.id or 0,
        )
        self.agent = Agent(name="Shared Agent", llm_id=None, use_scope="all")
        self.session.add(self.owner)
        self.session.add(self.collaborator)
        self.session.add(self.agent)
        self.session.commit()
        self.session.refresh(self.owner)
        self.session.refresh(self.collaborator)
        self.session.refresh(self.agent)

        self.project = ProjectService(self.session).create_project(
            agent_id=self.agent.id or 0,
            username=self.owner.username,
            name="Launch",
        )
        self.current_user = self.owner

        self.app = FastAPI()
        self.app.include_router(projects_api_module.router)
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release app, database, and temporary workspace resources."""
        self.client.close()
        self.app.dependency_overrides.clear()
        self.workspace_profile_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _get_db(self) -> Generator[Session, None, None]:
        """Yield the shared database session for the test API app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the active user configured by each test."""
        return self.current_user

    def test_use_grant_lists_project_without_edit_actions(self) -> None:
        """Use-only collaborators should see the project but remain read-only."""
        response = self.client.put(
            f"/projects/{self.project.project_id}/access",
            json={
                "use_user_ids": [self.collaborator.id],
                "use_group_ids": [],
                "edit_user_ids": [],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.owner.id, response.json()["edit_user_ids"])

        self.current_user = self.collaborator
        response = self.client.get(f"/projects?agent_id={self.agent.id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["projects"][0]["project_id"], self.project.project_id)
        self.assertFalse(payload["projects"][0]["can_edit"])

        response = self.client.patch(
            f"/projects/{self.project.project_id}",
            json={"name": "Blocked"},
        )
        self.assertEqual(response.status_code, 403)

    def test_edit_grant_allows_project_update_and_syncs_workspace(self) -> None:
        """Edit grants should allow metadata updates and mirror workspace access."""
        response = self.client.put(
            f"/projects/{self.project.project_id}/access",
            json={
                "use_user_ids": [self.collaborator.id],
                "use_group_ids": [],
                "edit_user_ids": [self.collaborator.id],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.collaborator.id, response.json()["edit_user_ids"])

        workspace_edit_grant = self.session.exec(
            select(ResourceAccess).where(
                ResourceAccess.resource_type == ResourceType.WORKSPACE,
                ResourceAccess.resource_id == self.project.workspace_id,
                ResourceAccess.access_level == AccessLevel.EDIT,
                ResourceAccess.principal_id == str(self.collaborator.id),
            )
        ).first()
        self.assertIsNotNone(workspace_edit_grant)

        self.current_user = self.collaborator
        response = self.client.patch(
            f"/projects/{self.project.project_id}",
            json={"name": "Launch v2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Launch v2")
        self.assertTrue(response.json()["can_edit"])

    def test_access_editor_requires_project_edit(self) -> None:
        """Use-only collaborators should not open or save access settings."""
        response = self.client.put(
            f"/projects/{self.project.project_id}/access",
            json={
                "use_user_ids": [self.collaborator.id],
                "use_group_ids": [],
                "edit_user_ids": [],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200)

        self.current_user = self.collaborator
        response = self.client.get(f"/projects/{self.project.project_id}/access")
        self.assertEqual(response.status_code, 403)

        response = self.client.put(
            f"/projects/{self.project.project_id}/access",
            json={
                "use_user_ids": [],
                "use_group_ids": [],
                "edit_user_ids": [self.collaborator.id],
                "edit_group_ids": [],
            },
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
