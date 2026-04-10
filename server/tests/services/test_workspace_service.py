"""Unit tests for workspace path resolution helpers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

WorkspaceHandle = import_module("app.storage.types").WorkspaceHandle
Workspace = import_module("app.models.workspace").Workspace
workspace_service = import_module("app.services.workspace_service")


class _FakeExternalPOSIXProvider:
    """Minimal provider stub for testing external workspace layout helpers."""

    def __init__(self, host_root: Path, backend_root: Path) -> None:
        """Store one host root plus its backend-visible alias."""
        self._host_root = host_root
        self._backend_root = backend_root

    def ensure_workspace(self, logical_root: str) -> Any:
        """Create one logical workspace under the host root."""
        workspace_path = self._host_root.joinpath(*logical_root.split("/"))
        workspace_path.mkdir(parents=True, exist_ok=True)
        return WorkspaceHandle(logical_root=logical_root, host_path=workspace_path)

    def local_root(self) -> Path:
        """Return the backend-visible root directory."""
        return self._backend_root


class WorkspaceServiceBackendPathTestCase(unittest.TestCase):
    """Validate backend-visible workspace path derivation."""

    def test_workspace_backend_path_uses_active_provider_root(self) -> None:
        """Backend path generation should follow the active provider root."""
        module = cast(Any, workspace_service)
        service = module.WorkspaceService(db=None)
        workspace = Workspace(
            workspace_id="workspace-1",
            agent_id=9,
            user="alice",
            scope="session_private",
            session_id="session-1",
        )

        with patch.object(
            module,
            "get_resolved_storage_profile",
            return_value=type(
                "ResolvedProfile",
                (),
                {
                    "posix_workspace": type(
                        "PosixWorkspace",
                        (),
                        {"local_root": lambda self: Path("/srv/pivot-workspaces")},
                    )(),
                },
            )(),
        ):
            backend_path = service.get_workspace_backend_path(workspace)

        self.assertEqual(
            backend_path,
            "/srv/pivot-workspaces/users/alice/agents/9/sessions/session-1/workspace",
        )

    def test_workspace_backend_path_supports_external_posix_root(self) -> None:
        """External POSIX providers should drive backend-visible workspace roots."""
        module = cast(Any, workspace_service)
        service = module.WorkspaceService(db=None)
        workspace = Workspace(
            workspace_id="workspace-2",
            agent_id=12,
            user="bob",
            scope="project_shared",
            project_id="project-9",
        )

        with patch.object(
            module,
            "get_resolved_storage_profile",
            return_value=type(
                "ResolvedProfile",
                (),
                {
                    "posix_workspace": type(
                        "PosixWorkspace",
                        (),
                        {"local_root": lambda self: Path("/app/server/external-posix")},
                    )(),
                },
            )(),
        ):
            backend_path = service.get_workspace_backend_path(workspace)

        self.assertEqual(
            backend_path,
            "/app/server/external-posix/users/bob/agents/12/projects/project-9/workspace",
        )

    def test_workspace_uploads_dir_stays_inside_external_workspace_root(self) -> None:
        """Runtime uploads should live under the active workspace root."""
        module = cast(Any, workspace_service)
        service = module.WorkspaceService(db=None)
        workspace = Workspace(
            workspace_id="workspace-3",
            agent_id=3,
            user="carol",
            scope="session_private",
            session_id="session-uploads",
        )

        with tempfile.TemporaryDirectory() as temp_root:
            resolved_profile = type(
                "ResolvedProfile",
                (),
                {
                    "posix_workspace": _FakeExternalPOSIXProvider(
                        Path(temp_root),
                        Path("/app/server/external-posix"),
                    ),
                },
            )()
            with patch.object(
                module,
                "get_resolved_storage_profile",
                return_value=resolved_profile,
            ):
                uploads_path = service.get_workspace_uploads_path(workspace)

        self.assertEqual(
            uploads_path,
            Path(temp_root)
            / "users"
            / "carol"
            / "agents"
            / "3"
            / "sessions"
            / "session-uploads"
            / "workspace"
            / ".uploads",
        )
