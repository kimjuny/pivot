"""Unit tests for project-backed shared workspaces."""

import json
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
Workspace = import_module("app.models.workspace").Workspace
ProjectService = import_module("app.services.project_service").ProjectService
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
workspace_service = import_module("app.services.workspace_service")


class ProjectServiceTestCase(unittest.TestCase):
    """Validate project CRUD and shared-workspace ownership."""

    def setUp(self) -> None:
        """Create an isolated database and workspace root for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        workspace_module = cast(Any, workspace_service)
        self.original_workspace_root = workspace_module._WORKSPACE_ROOT
        workspace_module._WORKSPACE_ROOT = Path(self.temp_dir.name)

        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        agent = Agent(name="agent-1", llm_id=None)
        self.db.add(agent)
        self.db.add(User(username="alice", password_hash="hash"))
        self.db.commit()
        self.db.refresh(agent)
        self.agent = agent
        self.service = ProjectService(self.db)

    def tearDown(self) -> None:
        """Restore the original workspace root and close the test database."""
        self.db.close()
        cast(Any, workspace_service)._WORKSPACE_ROOT = self.original_workspace_root
        self.temp_dir.cleanup()

    def test_create_project_creates_shared_workspace(self) -> None:
        """Creating a project should persist both the row and workspace identity."""
        project = self.service.create_project(
            agent_id=self.agent.id or 0,
            username="alice",
            name="Website refresh",
        )

        self.assertEqual(project.name, "Website refresh")
        self.assertTrue(project.workspace_id)
        workspace = self.db.exec(
            select(Workspace).where(Workspace.workspace_id == project.workspace_id)
        ).first()
        self.assertIsNotNone(workspace)
        assert workspace is not None
        self.assertEqual(workspace.storage_backend, "seaweedfs")
        self.assertEqual(workspace.mount_mode, "live_sync")
        self.assertEqual(
            workspace.logical_path,
            f"users/alice/agents/{self.agent.id or 0}/projects/{project.project_id}",
        )

    def test_delete_project_removes_child_sessions(self) -> None:
        """Deleting a project should remove every session that points at it."""
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

        deleted = self.service.delete_project(project.project_id, username="alice")

        self.assertTrue(deleted)
        self.assertIsNone(self.service.get_project(project.project_id))
        remaining_session = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == "session-1")
        ).first()
        self.assertIsNone(remaining_session)


if __name__ == "__main__":
    unittest.main()
