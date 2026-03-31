"""Unit tests for assistant-generated task attachment persistence."""

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

TaskAttachmentService = import_module(
    "app.services.task_attachment_service"
).TaskAttachmentService
workspace_service = import_module("app.services.workspace_service")


class TaskAttachmentServiceTestCase(unittest.TestCase):
    """Validate answer attachment normalization and snapshot persistence."""

    def setUp(self) -> None:
        """Create an isolated database and workspace for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        workspace_module = cast(Any, workspace_service)
        self.original_workspace_root = workspace_module._WORKSPACE_ROOT
        workspace_module._WORKSPACE_ROOT = Path(self.temp_dir.name)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        self.db = Session(engine)
        self.service = TaskAttachmentService(self.db)

        self.agent_workspace = workspace_module.ensure_agent_workspace(
            "alice", 7
        ).resolve()

    def tearDown(self) -> None:
        """Restore the original workspace root and close the test database."""
        self.db.close()
        cast(Any, workspace_service)._WORKSPACE_ROOT = self.original_workspace_root
        self.temp_dir.cleanup()

    def test_create_from_answer_paths_snapshots_valid_workspace_files(self) -> None:
        """Valid workspace files should be snapshotted and exposed as markdown attachments."""
        source_file = self.agent_workspace / "outputs" / "report.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Report\n\nReady.", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            agent_id=7,
            task_id="task-1",
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "markdown")
        self.assertEqual(attachments[0].workspace_relative_path, "outputs/report.md")
        self.assertTrue(Path(attachments[0].storage_path).exists())
        self.assertNotEqual(Path(attachments[0].storage_path), source_file)

    def test_create_from_answer_paths_skips_invalid_files_but_keeps_valid_ones(
        self,
    ) -> None:
        """Invalid paths should be ignored without blocking valid attachment snapshots."""
        valid_file = self.agent_workspace / "outputs" / "diagram.txt"
        valid_file.parent.mkdir(parents=True, exist_ok=True)
        valid_file.write_text("hello", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            agent_id=7,
            task_id="task-2",
            session_id=None,
            paths=[
                "/workspace/outputs/diagram.txt",
                "/workspace/missing.md",
                "/tmp/outside.txt",
            ],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].display_name, "diagram.txt")

    def test_create_from_answer_paths_marks_common_code_files_as_text(self) -> None:
        """Code and config files should stay previewable instead of falling back to raw download."""
        source_file = self.agent_workspace / "outputs" / "script.js"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("console.log('pivot')\n", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            agent_id=7,
            task_id="task-3",
            session_id="session-3",
            paths=["/workspace/outputs/script.js"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "text")
        self.assertEqual(attachments[0].mime_type, "application/javascript")

    def test_create_from_answer_paths_marks_hidden_env_files_as_text(self) -> None:
        """Hidden plain-text config files should remain previewable in the client."""
        source_file = self.agent_workspace / ".env"
        source_file.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            agent_id=7,
            task_id="task-4",
            session_id="session-4",
            paths=["/workspace/.env"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "text")
        self.assertEqual(attachments[0].workspace_relative_path, ".env")

    def test_extract_declared_paths_accepts_both_spellings(self) -> None:
        """Both the corrected and legacy attachment keys should normalize cleanly."""
        self.assertEqual(
            TaskAttachmentService.extract_declared_paths(
                {"attachments": ["/workspace/a.md"]}
            ),
            ["/workspace/a.md"],
        )
        self.assertEqual(
            TaskAttachmentService.extract_declared_paths(
                {"attatchments": ["/workspace/b.md"]}
            ),
            ["/workspace/b.md"],
        )
