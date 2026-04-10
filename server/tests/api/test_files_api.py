"""API tests for uploaded files and live task attachment content."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

FileAsset = import_module("app.models.file").FileAsset
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
auth_module = import_module("app.api.auth")
dependencies_module = import_module("app.api.dependencies")
files_api_module = import_module("app.api.files")
task_attachments_api_module = import_module("app.api.task_attachments")
file_service_module = import_module("app.services.file_service")
task_attachment_service_module = import_module("app.services.task_attachment_service")
workspace_service_module = import_module("app.services.workspace_service")
WorkspaceService = workspace_service_module.WorkspaceService
TaskAttachmentService = task_attachment_service_module.TaskAttachmentService
LocalFilesystemObjectStorageProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemObjectStorageProvider
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider


class _FakeExternalPOSIXProvider(LocalFilesystemPOSIXWorkspaceProvider):
    """Expose a temp host root while advertising an external backend root."""

    def __init__(self, host_root: Path, backend_root: Path) -> None:
        """Store one host root plus its backend-visible alias."""
        super().__init__(host_root)
        self._backend_root = backend_root

    def local_root(self) -> Path:
        """Return the backend-visible root instead of the host temp path."""
        return self._backend_root


class FilesApiTestCase(unittest.TestCase):
    """Verify file upload and live task attachment content endpoints."""

    def setUp(self) -> None:
        """Create one isolated app, database, and storage profile."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.object_root = self.root / "object-storage"
        self.object_root.mkdir(parents=True, exist_ok=True)
        self.external_host_root = self.root / "external-posix"
        self.external_host_root.mkdir(parents=True, exist_ok=True)

        resolved_profile = type(
            "ResolvedProfile",
            (),
            {
                "object_storage": LocalFilesystemObjectStorageProvider(
                    self.object_root
                ),
                "posix_workspace": _FakeExternalPOSIXProvider(
                    self.external_host_root,
                    Path("/app/server/external-posix"),
                ),
            },
        )()

        self.file_profile_patch = patch.object(
            cast(Any, file_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.workspace_profile_patch = patch.object(
            cast(Any, workspace_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.file_profile_patch.start()
        self.workspace_profile_patch.start()

        self.user = User(username="alice", password_hash="hash")
        self.session.add(self.user)
        self.session.commit()
        self.session.refresh(self.user)

        self.app = FastAPI()
        self.app.include_router(files_api_module.router, prefix="/api")
        self.app.include_router(task_attachments_api_module.router, prefix="/api")
        self.app.dependency_overrides[dependencies_module.get_db] = self._get_db
        self.app.dependency_overrides[auth_module.get_current_user] = (
            self._get_current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        """Release test resources and dependency overrides."""
        self.client.close()
        self.app.dependency_overrides.clear()
        self.file_profile_patch.stop()
        self.workspace_profile_patch.stop()
        self.session.close()
        self.tmpdir.cleanup()

    def _get_db(self):
        """Yield the shared database session used by the test app."""
        yield self.session

    def _get_current_user(self) -> Any:
        """Return the authenticated test user for protected endpoints."""
        return self.user

    @staticmethod
    def _build_png_bytes(color: str = "#3b82f6") -> bytes:
        """Create a small in-memory PNG image."""
        image = Image.new("RGB", (16, 12), color=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_upload_endpoint_persists_object_backed_file_under_external_profile(
        self,
    ) -> None:
        """Uploads should use object storage even when workspaces use external POSIX."""
        response = self.client.post(
            "/api/files/uploads",
            files={
                "file": ("diagram.png", self._build_png_bytes(), "image/png"),
            },
            data={"source": "local"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        file_id = payload["file_id"]

        stored_asset = self.session.exec(
            select(FileAsset).where(FileAsset.file_id == file_id)
        ).first()
        self.assertIsNotNone(stored_asset)
        if stored_asset is None:
            self.fail("Expected uploaded file asset to be persisted.")

        self.assertEqual(stored_asset.storage_backend, "local_fs")
        self.assertIsNotNone(stored_asset.object_key)
        object_path = self.object_root / Path(stored_asset.object_key or "")
        self.assertTrue(object_path.is_file())
        self.assertTrue(object_path.is_relative_to(self.object_root))
        self.assertFalse(object_path.is_relative_to(self.external_host_root))

        content_response = self.client.get(f"/api/files/{file_id}/content")
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response.headers["content-type"], "image/png")
        self.assertEqual(content_response.content, self._build_png_bytes())

    def test_task_attachment_content_streams_live_workspace_upload_file(self) -> None:
        """Attachment content should stream the current `.uploads` live file."""
        workspace = WorkspaceService(self.session).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.session.add(
            SessionModel(
                session_id="session-1",
                agent_id=7,
                user="alice",
                workspace_id=workspace.workspace_id,
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.session.commit()

        uploads_dir = WorkspaceService(self.session).get_workspace_uploads_path(workspace)
        live_file = uploads_dir / "report.md"
        live_file.write_text("# Live report\n\nhello", encoding="utf-8")

        attachments = TaskAttachmentService(self.session).create_from_answer_paths(
            username="alice",
            task_id="task-1",
            session_id="session-1",
            paths=["/workspace/.uploads/report.md"],
        )

        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].workspace_relative_path, ".uploads/report.md")
        self.assertTrue(live_file.is_relative_to(self.external_host_root))

        response = self.client.get(
            f"/api/task-attachments/{attachments[0].attachment_id}/content"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/markdown", response.headers["content-type"])
        self.assertIn("filename=", response.headers["content-disposition"])
        self.assertEqual(response.text, "# Live report\n\nhello")


if __name__ == "__main__":
    unittest.main()
