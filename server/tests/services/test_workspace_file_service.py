"""Unit tests for workspace-local text file CRUD helpers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
WorkspaceService = import_module("app.services.workspace_service").WorkspaceService
workspace_service_module = import_module("app.services.workspace_service")
workspace_file_service_module = import_module("app.services.workspace_file_service")
WorkspaceFileService = workspace_file_service_module.WorkspaceFileService
WorkspaceFileValidationError = (
    workspace_file_service_module.WorkspaceFileValidationError
)
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

    def test_write_and_list_tree_for_owned_workspace(self) -> None:
        """Text file writes should materialize in the workspace tree listing."""
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
        entries = service.list_tree(
            workspace_id=workspace.workspace_id,
            username="alice",
        )

        self.assertEqual(contents, "export const App = () => null;\n")
        self.assertEqual(
            [(entry.path, entry.kind) for entry in entries],
            [("src", "directory"), ("src/App.tsx", "file")],
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
