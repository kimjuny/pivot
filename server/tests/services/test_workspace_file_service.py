"""Unit tests for workspace-local text file CRUD helpers."""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
WorkspaceService = import_module("app.services.workspace_service").WorkspaceService
access_models = import_module("app.models.access")
user_models = import_module("app.models.user")
workspace_service_module = import_module("app.services.workspace_service")
workspace_file_service_module = import_module("app.services.workspace_file_service")
access_service_module = import_module("app.services.access_service")
permission_service_module = import_module("app.services.permission_service")
WorkspaceFileService = workspace_file_service_module.WorkspaceFileService
WorkspaceFileValidationError = (
    workspace_file_service_module.WorkspaceFileValidationError
)
WorkspaceFilePermissionError = (
    workspace_file_service_module.WorkspaceFilePermissionError
)
AccessLevel = access_models.AccessLevel
PrincipalType = access_models.PrincipalType
ResourceType = access_models.ResourceType
Role = access_models.Role
User = user_models.User
AccessService = access_service_module.AccessService
PermissionService = permission_service_module.PermissionService
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider


class WorkspaceFileServiceTestCase(unittest.TestCase):
    """Verify safe workspace-local tree, read, and write operations."""

    def setUp(self) -> None:
        """Create one isolated database and workspace root."""
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        PermissionService(self.db).seed_defaults()
        user_role = self.db.exec(select(Role).where(Role.key == "user")).one()
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
        self.db.add(self.alice)
        self.db.add(self.bob)
        self.db.commit()
        self.db.refresh(self.alice)
        self.db.refresh(self.bob)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tmpdir.name) / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        resolved_profile = type(
            "ResolvedProfile",
            (),
            {
                "posix_workspace": LocalFilesystemPOSIXWorkspaceProvider(
                    self.workspace_root
                ),
            },
        )()

        self.workspace_profile_patch = patch.object(
            cast(Any, workspace_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.workspace_profile_patch.start()

    def tearDown(self) -> None:
        """Release temporary database and workspace resources."""
        self.workspace_profile_patch.stop()
        self.db.close()
        self.tmpdir.cleanup()

    def test_write_and_list_directory_for_owned_workspace(self) -> None:
        """Text file writes should materialize in direct directory listings."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-1",
        )
        service = WorkspaceFileService(self.db)

        service.write_text_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path="src/App.tsx",
            content="export const App = () => null;\n",
        )

        contents = service.read_text_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path="src/App.tsx",
        )
        root_entries = service.list_directory(
            workspace_id=workspace.workspace_id,
            username="alice",
        )
        src_entries = service.list_directory(
            workspace_id=workspace.workspace_id,
            username="alice",
            path="src",
        )

        self.assertEqual(contents, "export const App = () => null;\n")
        self.assertEqual(
            [(entry.path, entry.kind) for entry in root_entries],
            [("src", "directory")],
        )
        self.assertEqual(
            [(entry.path, entry.kind) for entry in src_entries],
            [("src/App.tsx", "file")],
        )

    def test_rejects_paths_that_escape_workspace_root(self) -> None:
        """Relative path validation should reject traversal attempts."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-2",
        )
        service = WorkspaceFileService(self.db)

        with self.assertRaises(WorkspaceFileValidationError):
            service.write_text_file(
                workspace_id=workspace.workspace_id,
                username="alice",
                path="../secrets.txt",
                content="nope",
            )

    def test_read_file_returns_image_payload_for_previewable_binary(self) -> None:
        """Common image formats should be returned as image preview payloads."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-3",
        )
        service = WorkspaceFileService(self.db)
        workspace_path = WorkspaceService(self.db).get_workspace_path(workspace)
        image_path = workspace_path / "assets" / "preview.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7ZxV0AAAAASUVORK5CYII="
        )
        image_path.write_bytes(image_bytes)

        result = service.read_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path="assets/preview.png",
        )

        self.assertEqual(result.kind, "image")
        self.assertEqual(result.mime_type, "image/png")
        self.assertEqual(
            result.data_base64, base64.b64encode(image_bytes).decode("ascii")
        )

    def test_write_and_read_binary_file(self) -> None:
        """Binary workspace writes should preserve bytes and MIME metadata."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-4",
        )
        service = WorkspaceFileService(self.db)
        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7ZxV0AAAAASUVORK5CYII="
        )

        write_result = service.write_binary_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path=".pivot/apps/canvas/assets/example.png",
            content=image_bytes,
            mime_type="image/png",
        )
        read_result = service.read_binary_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path=".pivot/apps/canvas/assets/example.png",
        )

        self.assertEqual(write_result.path, ".pivot/apps/canvas/assets/example.png")
        self.assertEqual(write_result.mime_type, "image/png")
        self.assertEqual(write_result.size_bytes, len(image_bytes))
        self.assertEqual(read_result.content, image_bytes)
        self.assertEqual(read_result.mime_type, "image/png")
        self.assertEqual(read_result.size_bytes, len(image_bytes))

    def test_workspace_use_grant_reads_but_does_not_write(self) -> None:
        """Workspace grants should distinguish use from edit access."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-5",
        )
        service = WorkspaceFileService(self.db)
        service.write_text_file(
            workspace_id=workspace.workspace_id,
            username="alice",
            path="notes.txt",
            content="hello",
        )
        AccessService(self.db).grant_access(
            resource_type=ResourceType.WORKSPACE,
            resource_id=workspace.workspace_id,
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.USE,
        )

        content = service.read_text_file(
            workspace_id=workspace.workspace_id,
            username="bob",
            path="notes.txt",
        )

        self.assertEqual(content, "hello")
        with self.assertRaises(WorkspaceFilePermissionError):
            service.write_text_file(
                workspace_id=workspace.workspace_id,
                username="bob",
                path="notes.txt",
                content="updated",
            )

        AccessService(self.db).grant_access(
            resource_type=ResourceType.WORKSPACE,
            resource_id=workspace.workspace_id,
            principal_type=PrincipalType.USER,
            principal_id=self.bob.id or 0,
            access_level=AccessLevel.EDIT,
        )

        service.write_text_file(
            workspace_id=workspace.workspace_id,
            username="bob",
            path="notes.txt",
            content="updated",
        )

        self.assertEqual(
            service.read_text_file(
                workspace_id=workspace.workspace_id,
                username="alice",
                path="notes.txt",
            ),
            "updated",
        )
