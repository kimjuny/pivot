"""Unit tests for assistant-generated task attachment persistence."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

TaskAttachmentService = import_module(
    "app.services.task_attachment_service"
).TaskAttachmentService
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider
SessionModel = import_module("app.models.session").Session
WorkspaceService = import_module("app.services.workspace_service").WorkspaceService
workspace_service = import_module("app.services.workspace_service")


class _FakeExternalPOSIXProvider(LocalFilesystemPOSIXWorkspaceProvider):
    """Use a temporary host root while exposing an external backend root."""

    def __init__(self, host_root: Path, backend_root: Path) -> None:
        """Store one host root plus its backend-visible alias."""
        super().__init__(host_root)
        self._backend_root = backend_root

    def local_root(self) -> Path:
        """Return the backend-visible root instead of the host temp path."""
        return self._backend_root


class TaskAttachmentServiceTestCase(unittest.TestCase):
    """Validate answer attachment normalization and live reference persistence."""

    def setUp(self) -> None:
        """Create an isolated database and workspace for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.host_root = Path(self.temp_dir.name) / "external-posix"
        self.profile_patch = patch.object(
            cast(Any, workspace_service),
            "get_resolved_storage_profile",
            return_value=type(
                "ResolvedProfile",
                (),
                {
                    "posix_workspace": _FakeExternalPOSIXProvider(
                        self.host_root,
                        Path("/app/server/external-posix"),
                    ),
                },
            )(),
        )
        self.profile_patch.start()

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        self.db = Session(engine)
        self.service = TaskAttachmentService(self.db)
        self.workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.workspace_path = (
            WorkspaceService(self.db).get_workspace_path(self.workspace).resolve()
        )
        self.db.add(
            SessionModel(
                session_id="session-1",
                agent_id=7,
                user="alice",
                workspace_id=self.workspace.workspace_id,
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        """Restore the original workspace root and close the test database."""
        self.db.close()
        self.profile_patch.stop()
        self.temp_dir.cleanup()

    def test_create_from_answer_paths_persists_live_workspace_references(self) -> None:
        """Valid workspace files should persist live references, not snapshots."""
        source_file = self.workspace_path / "outputs" / "report.md"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("# Report\n\nReady.", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-1",
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "markdown")
        self.assertEqual(attachments[0].workspace_relative_path, "outputs/report.md")
        self.assertEqual(attachments[0].workspace_id, self.workspace.workspace_id)
        self.assertEqual(
            self.service.resolve_live_attachment_path(attachments[0]),
            source_file,
        )

    def test_create_from_answer_paths_skips_invalid_files_but_keeps_valid_ones(
        self,
    ) -> None:
        """Invalid paths should be ignored without blocking valid live attachments."""
        valid_file = self.workspace_path / "outputs" / "diagram.txt"
        valid_file.parent.mkdir(parents=True, exist_ok=True)
        valid_file.write_text("hello", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-2",
            session_id="session-1",
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
        source_file = self.workspace_path / "outputs" / "script.js"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text("console.log('pivot')\n", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-3",
            session_id="session-1",
            paths=["/workspace/outputs/script.js"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "text")
        self.assertEqual(attachments[0].mime_type, "application/javascript")

    def test_create_from_answer_paths_marks_hidden_env_files_as_text(self) -> None:
        """Hidden plain-text config files should remain previewable in the client."""
        source_file = self.workspace_path / ".env"
        source_file.write_text("OPENAI_API_KEY=test\n", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-4",
            session_id="session-1",
            paths=["/workspace/.env"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "text")
        self.assertEqual(attachments[0].workspace_relative_path, ".env")

    def test_live_attachment_resolution_supports_workspace_uploads(self) -> None:
        """Assistant files in `.uploads` should resolve under the active workspace root."""
        uploads_dir = WorkspaceService(self.db).get_workspace_uploads_path(self.workspace)
        source_file = uploads_dir / "artifact.txt"
        source_file.write_text("hello from uploads", encoding="utf-8")

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-uploads",
            session_id="session-1",
            paths=["/workspace/.uploads/artifact.txt"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(
            attachments[0].workspace_relative_path,
            ".uploads/artifact.txt",
        )
        self.assertEqual(
            self.service.resolve_live_attachment_path(attachments[0]),
            source_file,
        )
        self.assertTrue(source_file.is_relative_to(self.workspace_path))

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
