"""Workspace storage identity helpers for runtime filesystem backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.workspace import Workspace

_WORKSPACE_STORAGE_BACKEND = "seaweedfs"
_WORKSPACE_MOUNT_MODE = "live_sync"


@dataclass(frozen=True, slots=True)
class WorkspaceMountSpec:
    """Stable workspace mount contract shared with sandbox-manager."""

    workspace_id: str
    storage_backend: str
    logical_path: str
    mount_mode: str
    source_workspace_id: str | None = None


def build_workspace_logical_path(
    *,
    scope: str,
    username: str,
    agent_id: int,
    session_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Return the canonical logical storage path for one workspace.

    Args:
        scope: Workspace scope string.
        username: Workspace owner username.
        agent_id: Owning agent identifier.
        session_id: Optional session ID for private workspaces.
        project_id: Optional project ID for shared workspaces.

    Returns:
        Canonical logical path inside shared workspace storage.

    Raises:
        ValueError: If scope-specific identifiers are missing.
    """
    base = f"users/{username}/agents/{agent_id}"
    if scope == "session_private":
        if session_id is None or project_id is not None:
            raise ValueError("session_private workspaces require session_id only.")
        return f"{base}/sessions/{session_id}"
    if scope == "project_shared":
        if project_id is None or session_id is not None:
            raise ValueError("project_shared workspaces require project_id only.")
        return f"{base}/projects/{project_id}"
    raise ValueError(f"Unsupported workspace scope '{scope}'.")


class WorkspaceStorageService:
    """Build storage identity and runtime mount specs for workspaces."""

    @staticmethod
    def build_logical_path(
        *,
        scope: str,
        username: str,
        agent_id: int,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Return the canonical logical path for one workspace."""
        return build_workspace_logical_path(
            scope=scope,
            username=username,
            agent_id=agent_id,
            session_id=session_id,
            project_id=project_id,
        )

    @staticmethod
    def default_storage_backend() -> str:
        """Return the default backend name for newly provisioned workspaces."""
        return _WORKSPACE_STORAGE_BACKEND

    @staticmethod
    def default_mount_mode() -> str:
        """Return the default runtime mount mode for newly provisioned workspaces."""
        return _WORKSPACE_MOUNT_MODE

    def ensure_workspace_identity(self, workspace: Workspace) -> Workspace:
        """Populate storage identity fields when they are missing.

        Args:
            workspace: Workspace row to normalize.

        Returns:
            The same workspace row with storage fields populated in memory.
        """
        if not workspace.logical_path:
            workspace.logical_path = self.build_logical_path(
                scope=workspace.scope,
                username=workspace.user,
                agent_id=workspace.agent_id,
                session_id=workspace.session_id,
                project_id=workspace.project_id,
            )
        if not workspace.storage_backend:
            workspace.storage_backend = self.default_storage_backend()
        if not workspace.mount_mode:
            workspace.mount_mode = self.default_mount_mode()
        return workspace

    def build_mount_spec(self, workspace: Workspace) -> WorkspaceMountSpec:
        """Return the stable runtime mount spec for one workspace."""
        normalized = self.ensure_workspace_identity(workspace)
        return WorkspaceMountSpec(
            workspace_id=normalized.workspace_id,
            storage_backend=normalized.storage_backend,
            logical_path=normalized.logical_path,
            mount_mode=normalized.mount_mode,
            source_workspace_id=normalized.source_workspace_id,
        )
