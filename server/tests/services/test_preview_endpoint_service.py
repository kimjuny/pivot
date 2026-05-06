"""Unit tests for preview endpoint reconnect behavior."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
WorkspaceService = import_module("app.services.workspace_service").WorkspaceService
workspace_service_module = import_module("app.services.workspace_service")
preview_endpoint_service_module = import_module("app.services.preview_endpoint_service")
PreviewEndpointService = preview_endpoint_service_module.PreviewEndpointService
sandbox_service_module = import_module("app.services.sandbox_service")
SandboxExecResult = sandbox_service_module.SandboxExecResult
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider


class PreviewEndpointServiceTestCase(unittest.TestCase):
    """Verify reconnect uses recorded launch recipes to recreate preview runtimes."""

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
        self.user = User(username="alice", password_hash="hash", role_id=1)
        self.agent = Agent(name="preview-agent", llm_id=None, created_by_user_id=None)
        self.db.add(self.user)
        self.db.add(self.agent)
        self.db.commit()
        self.db.refresh(self.user)
        self.agent.created_by_user_id = self.user.id
        self.db.add(self.agent)
        self.db.commit()
        self.db.refresh(self.agent)

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
        PreviewEndpointService.clear_preview_endpoints()

    def tearDown(self) -> None:
        """Release temporary database and workspace resources."""
        PreviewEndpointService.clear_preview_endpoints()
        self.workspace_profile_patch.stop()
        self.db.close()
        self.tmpdir.cleanup()

    def test_connect_preview_endpoint_recreates_missing_sandbox_from_recipe(
        self,
    ) -> None:
        """Reconnect should recreate sandbox first, then replay start_server."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=self.agent.id or 0,
            username="alice",
            scope="session_private",
            session_id="session-1",
        )
        self.db.add(
            SessionModel(
                session_id="session-1",
                agent_id=self.agent.id or 0,
                user="alice",
                workspace_id=workspace.workspace_id,
            )
        )
        self.db.commit()
        service = PreviewEndpointService(self.db)
        record = service.create_preview_endpoint(
            username="alice",
            session_id="session-1",
            port=3000,
            path="/",
            title="Landing Page",
            cwd="apps/landing-page",
            start_server="bash /workspace/.pivot/previews/landing-page.sh",
            skills=({"name": "alpha", "location": "/workspace/skills/alpha"},),
        )

        sandbox_service = MagicMock()
        sandbox_service.proxy_http.side_effect = [
            RuntimeError(
                "Sandbox preview runtime is unavailable because the original sandbox container no longer exists."
            ),
            object(),
        ]
        sandbox_service.exec.return_value = SandboxExecResult(
            exit_code=0,
            stdout="ok",
            stderr="",
        )

        with patch.object(
            preview_endpoint_service_module,
            "get_sandbox_service",
            return_value=sandbox_service,
        ):
            connected = service.connect_preview_endpoint(
                preview_id=record.preview_id,
                username="alice",
                timeout_seconds=30,
            )

        self.assertEqual(connected.preview_id, record.preview_id)
        workspace_backend_path = WorkspaceService(self.db).get_workspace_backend_path(
            workspace
        )
        sandbox_service.create.assert_called_once_with(
            username="alice",
            workspace_id=workspace.workspace_id,
            workspace_backend_path=workspace_backend_path,
            skills=[{"name": "alpha", "location": "/workspace/skills/alpha"}],
            timeout_seconds=30,
        )
        sandbox_service.exec.assert_called_once_with(
            username="alice",
            workspace_id=workspace.workspace_id,
            workspace_backend_path=workspace_backend_path,
            cmd=[
                "bash",
                "-lc",
                "cd /workspace/apps/landing-page && bash /workspace/.pivot/previews/landing-page.sh",
            ],
            skills=[{"name": "alpha", "location": "/workspace/skills/alpha"}],
            timeout_seconds=30,
        )
