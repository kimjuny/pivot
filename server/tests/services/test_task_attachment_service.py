"""Unit tests for assistant-generated live task attachment references."""

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

task_attachment_module = import_module("app.services.task_attachment_service")
TaskAttachmentService = task_attachment_module.TaskAttachmentService
SessionModel = import_module("app.models.session").Session
Workspace = import_module("app.models.workspace").Workspace
WorkspaceRuntimeFile = import_module(
    "app.services.workspace_runtime_file_service"
).WorkspaceRuntimeFile
workspace_service = import_module("app.services.workspace_service")


class TaskAttachmentServiceTestCase(unittest.TestCase):
    """Validate answer attachment normalization and live file references."""

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
        self.runtime_files_by_path: dict[str, tuple[str, bytes]] = {}
        self.export_patch = patch.object(
            task_attachment_module.WorkspaceRuntimeFileService,
            "export_files",
            side_effect=self._fake_export_files,
        )
        self.export_patch.start()

        self.agent_workspace = workspace_module.ensure_agent_workspace(
            "alice", 7
        ).resolve()
        session_workspace = workspace_module.session_workspace_dir(
            "alice",
            7,
            "session-1",
        ).resolve()
        self.workspace = Workspace(
            workspace_id="workspace-1",
            agent_id=7,
            user="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.db.add(self.workspace)
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
        self.agent_workspace = session_workspace

    def tearDown(self) -> None:
        """Restore the original workspace root and close the test database."""
        self.export_patch.stop()
        self.db.close()
        cast(Any, workspace_service)._WORKSPACE_ROOT = self.original_workspace_root
        self.temp_dir.cleanup()

    def _fake_export_files(
        self,
        *,
        username: str,
        mount_spec: Any,
        sandbox_paths: list[str],
        max_total_bytes: int = 0,
    ) -> list[Any]:
        """Return deterministic runtime snapshots for declared sandbox paths."""
        del username, mount_spec, max_total_bytes
        exported: list[Any] = []
        for sandbox_path in sandbox_paths:
            source = self.runtime_files_by_path.get(sandbox_path)
            if source is None:
                continue
            display_name, content_bytes = source
            exported.append(
                WorkspaceRuntimeFile(
                    sandbox_path=sandbox_path,
                    workspace_relative_path=sandbox_path.removeprefix(
                        "/workspace/"
                    ),
                    display_name=display_name,
                    content_bytes=content_bytes,
                )
            )
        return exported

    def test_create_from_answer_paths_tracks_valid_workspace_files(self) -> None:
        """Valid workspace files should be tracked as live markdown attachments."""
        self.runtime_files_by_path["/workspace/outputs/report.md"] = (
            "report.md",
            b"# Report\n\nReady.",
        )

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-1",
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "markdown")
        self.assertEqual(attachments[0].workspace_relative_path, "outputs/report.md")

    def test_create_from_answer_paths_skips_invalid_files_but_keeps_valid_ones(
        self,
    ) -> None:
        """Invalid paths should be ignored without blocking valid file references."""
        self.runtime_files_by_path["/workspace/outputs/diagram.txt"] = (
            "diagram.txt",
            b"hello",
        )

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
        self.runtime_files_by_path["/workspace/outputs/script.js"] = (
            "script.js",
            b"console.log('pivot')\n",
        )

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
        self.runtime_files_by_path["/workspace/.env"] = (
            ".env",
            b"OPENAI_API_KEY=test\n",
        )

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-4",
            session_id="session-1",
            paths=["/workspace/.env"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].render_kind, "text")
        self.assertEqual(attachments[0].workspace_relative_path, ".env")

    def test_read_attachment_bytes_exports_live_workspace_content(self) -> None:
        """Attachment reads should resolve the current live workspace file content."""
        self.runtime_files_by_path["/workspace/outputs/report.md"] = (
            "report.md",
            b"# Report\n\nReady.",
        )

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-live-read",
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        content = self.service.read_attachment_bytes(attachments[0])

        self.assertEqual(content, b"# Report\n\nReady.")

    def test_delete_by_task_id_removes_persisted_rows_only(self) -> None:
        """Deleting one task should clear metadata without treating attachments as snapshots."""
        self.runtime_files_by_path["/workspace/outputs/report.md"] = (
            "report.md",
            b"# Report\n\nReady.",
        )

        attachments = self.service.create_from_answer_paths(
            username="alice",
            task_id="task-delete",
            session_id="session-1",
            paths=["/workspace/outputs/report.md"],
        )

        deleted_count = self.service.delete_by_task_id("task-delete")

        self.assertEqual(deleted_count, 1)
        self.assertIsNone(
            self.service.get_attachment_for_user(attachments[0].attachment_id, "alice")
        )

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
