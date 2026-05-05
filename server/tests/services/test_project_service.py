"""Unit tests for project-backed shared workspaces."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
AccessLevel = import_module("app.models.access").AccessLevel
ResourceAccess = import_module("app.models.access").ResourceAccess
ResourceType = import_module("app.models.access").ResourceType
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider
ProjectService = import_module("app.services.project_service").ProjectService
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
WorkspaceFilePermissionError = import_module(
    "app.services.workspace_file_service"
).WorkspaceFilePermissionError
WorkspaceFileService = import_module(
    "app.services.workspace_file_service"
).WorkspaceFileService
workspace_service = import_module("app.services.workspace_service")


class _FakeExternalPOSIXProvider(LocalFilesystemPOSIXWorkspaceProvider):
    """Use one temporary host root while exposing an external backend root."""

    def __init__(self, host_root: Path, backend_root: Path) -> None:
        """Store one host root plus its backend-visible alias."""
        super().__init__(host_root)
        self._backend_root = backend_root

    def local_root(self) -> Path:
        """Return the backend-visible root instead of the host temp path."""
        return self._backend_root


class ProjectServiceTestCase(unittest.TestCase):
    """Validate project CRUD and shared-workspace ownership."""

    def setUp(self) -> None:
        """Create an isolated database and workspace root for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.provider = _FakeExternalPOSIXProvider(
            Path(self.temp_dir.name),
            Path("/app/server/external-posix"),
        )
        self.resolved_profile = type(
            "ResolvedProfile",
            (),
            {"posix_workspace": self.provider},
        )()

        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        agent = Agent(name="agent-1", llm_id=None)
        self.db.add(agent)
        self.db.add(User(username="alice", password_hash="hash", role_id=1))
        self.db.add(User(username="bob", password_hash="hash", role_id=1))
        self.db.commit()
        self.db.refresh(agent)
        self.alice = self.db.exec(select(User).where(User.username == "alice")).one()
        self.bob = self.db.exec(select(User).where(User.username == "bob")).one()
        self.agent = agent
        self.service = ProjectService(self.db)

    def tearDown(self) -> None:
        """Close the test database and dispose of temp filesystem state."""
        self.db.close()
        self.temp_dir.cleanup()

    def test_create_project_creates_shared_workspace(self) -> None:
        """Creating a project should persist both the row and the workspace path."""
        with patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=self.resolved_profile,
        ):
            project = self.service.create_project(
                agent_id=self.agent.id or 0,
                username="alice",
                name="Website refresh",
            )

        self.assertEqual(project.name, "Website refresh")
        self.assertTrue(project.workspace_id)
        project_dir = (
            Path(self.temp_dir.name)
            / "users"
            / "alice"
            / "agents"
            / str(self.agent.id or 0)
            / "projects"
            / project.project_id
            / "workspace"
        )
        self.assertTrue(project_dir.exists())

    def test_delete_project_removes_child_sessions(self) -> None:
        """Deleting a project should remove every session that points at it."""
        with patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=self.resolved_profile,
        ):
            project = self.service.create_project(
                agent_id=self.agent.id or 0,
                username="alice",
                name="Shared repo",
            )
        self.db.add(
            SessionModel(
                session_id="session-1",
                agent_id=self.agent.id or 0,
                user="alice",
                project_id=project.project_id,
                workspace_id=project.workspace_id,
                chat_history=json.dumps({"version": 1, "messages": []}),
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.db.commit()

        deleted = self.service.delete_project(project.project_id, user=self.alice)

        self.assertTrue(deleted)
        self.assertIsNone(self.service.get_project(project.project_id))
        remaining_session = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == "session-1")
        ).first()
        self.assertIsNone(remaining_session)

    def test_delete_project_uses_external_workspace_backend_path_for_sandbox(
        self,
    ) -> None:
        """Project deletion should tear down sandboxes using external workspace paths."""
        sandbox_service = Mock()
        with patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=self.resolved_profile,
        ):
            project = self.service.create_project(
                agent_id=self.agent.id or 0,
                username="alice",
                name="External repo",
            )
            workspace = workspace_service.WorkspaceService(self.db).get_workspace(
                project.workspace_id
            )
            if workspace is None:
                self.fail("Expected project workspace to exist")

            with patch(
                "app.services.project_service.get_sandbox_service",
                return_value=sandbox_service,
            ):
                deleted = self.service.delete_project(project.project_id, user=self.alice)

        self.assertTrue(deleted)
        sandbox_service.destroy.assert_called_once_with(
            username="alice",
            workspace_id=workspace.workspace_id,
            workspace_backend_path=(
                "/app/server/external-posix/users/alice/agents/"
                f"{self.agent.id or 0}/projects/{project.project_id}/workspace"
            ),
        )

    def test_project_use_grant_allows_listing_without_edit(self) -> None:
        """A use grant should make a project visible without allowing metadata edits."""
        with patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=self.resolved_profile,
        ):
            project = self.service.create_project(
                agent_id=self.agent.id or 0,
                username="alice",
                name="Shared repo",
            )

        self.service.set_project_access(
            project=project,
            use_user_ids={self.bob.id or 0},
            use_group_ids=set(),
            edit_user_ids={self.alice.id or 0},
            edit_group_ids=set(),
        )

        self.assertEqual(
            [
                visible.project_id
                for visible in self.service.list_projects(
                    user=self.bob,
                    agent_id=self.agent.id or 0,
                )
            ],
            [project.project_id],
        )
        self.assertTrue(
            self.service.has_project_access(
                user=self.bob,
                project=project,
                access_level=AccessLevel.USE,
            )
        )
        self.assertFalse(
            self.service.has_project_access(
                user=self.bob,
                project=project,
                access_level=AccessLevel.EDIT,
            )
        )

    def test_project_edit_grant_syncs_workspace_write_access(self) -> None:
        """Project edit access should mirror to the backing workspace."""
        with patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=self.resolved_profile,
        ):
            project = self.service.create_project(
                agent_id=self.agent.id or 0,
                username="alice",
                name="Shared repo",
            )

            self.service.set_project_access(
                project=project,
                use_user_ids={self.bob.id or 0},
                use_group_ids=set(),
                edit_user_ids=set(),
                edit_group_ids=set(),
            )
            file_service = WorkspaceFileService(self.db)
            with self.assertRaises(WorkspaceFilePermissionError):
                file_service.write_text_file(
                    workspace_id=project.workspace_id,
                    username="bob",
                    path="notes.md",
                    content="draft",
                )

            self.service.set_project_access(
                project=project,
                use_user_ids={self.bob.id or 0},
                use_group_ids=set(),
                edit_user_ids={self.bob.id or 0},
                edit_group_ids=set(),
            )
            file_service.write_text_file(
                workspace_id=project.workspace_id,
                username="bob",
                path="notes.md",
                content="draft",
            )

            self.assertEqual(
                file_service.read_text_file(
                    workspace_id=project.workspace_id,
                    username="bob",
                    path="notes.md",
                ),
                "draft",
            )
            workspace_grants = self.db.exec(
                select(ResourceAccess).where(
                    ResourceAccess.resource_type == ResourceType.WORKSPACE,
                    ResourceAccess.resource_id == project.workspace_id,
                    ResourceAccess.access_level == AccessLevel.EDIT,
                )
            ).all()
            self.assertIn(
                str(self.bob.id or 0),
                {grant.principal_id for grant in workspace_grants},
            )


if __name__ == "__main__":
    unittest.main()
