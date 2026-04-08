"""Unit tests for live session workspace file access."""

import sys
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

WorkspaceFileService = import_module(
    "app.services.workspace_file_service"
).WorkspaceFileService
SessionModel = import_module("app.models.session").Session
Workspace = import_module("app.models.workspace").Workspace
runtime_module = import_module("app.services.workspace_runtime_file_service")


class WorkspaceFileServiceTestCase(unittest.TestCase):
    """Validate session-scoped live workspace text file access."""

    def setUp(self) -> None:
        """Create an isolated in-memory database and seeded session workspace."""
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        self.db = Session(engine)
        self.service = WorkspaceFileService(self.db)
        self.db.add(
            Workspace(
                workspace_id="workspace-1",
                agent_id=7,
                user="alice",
                scope="session_private",
                session_id="session-1",
            )
        )
        self.db.add(
            SessionModel(
                session_id="session-1",
                agent_id=7,
                user="alice",
                workspace_id="workspace-1",
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        """Close the database session after each test."""
        self.db.close()

    def test_read_text_file_for_user_uses_runtime_file_service(self) -> None:
        """Reads should resolve the owned session mount spec before runtime access."""
        with patch.object(
            runtime_module.WorkspaceRuntimeFileService,
            "read_text_file",
            return_value="# Report",
        ) as mocked_read:
            file = self.service.read_text_file_for_user(
                session_id="session-1",
                username="alice",
                workspace_relative_path="outputs/report.md",
            )

        self.assertEqual(file.content, "# Report")
        mocked_read.assert_called_once()
        self.assertEqual(
            mocked_read.call_args.kwargs["workspace_relative_path"],
            "outputs/report.md",
        )

    def test_write_text_file_for_user_persists_live_content(self) -> None:
        """Writes should pass the edited text back into the runtime workspace."""
        with patch.object(
            runtime_module.WorkspaceRuntimeFileService,
            "write_text_file",
            return_value=None,
        ) as mocked_write:
            file = self.service.write_text_file_for_user(
                session_id="session-1",
                username="alice",
                workspace_relative_path=".uploads/file-1/note.md",
                content="# Updated",
            )

        self.assertEqual(file.content, "# Updated")
        mocked_write.assert_called_once()
        self.assertEqual(
            mocked_write.call_args.kwargs["workspace_relative_path"],
            ".uploads/file-1/note.md",
        )
        self.assertEqual(mocked_write.call_args.kwargs["content"], "# Updated")

    def test_read_text_file_for_user_rejects_unowned_sessions(self) -> None:
        """Session ownership checks should reject access before runtime reads."""
        with self.assertRaisesRegex(ValueError, "Session not found."):
            self.service.read_text_file_for_user(
                session_id="session-1",
                username="bob",
                workspace_relative_path="outputs/report.md",
            )
