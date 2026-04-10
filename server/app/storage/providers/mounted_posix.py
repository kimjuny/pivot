"""Mounted POSIX workspace providers for external filesystems."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from app.storage.providers.local_fs import _normalize_key
from app.storage.types import POSIXWorkspaceProvider, WorkspaceHandle

if TYPE_CHECKING:
    from pathlib import Path


class MountedPOSIXWorkspaceProvider(POSIXWorkspaceProvider):
    """Expose one pre-mounted external filesystem subtree as workspaces."""

    backend_name = "mounted_posix"

    def __init__(self, root: Path) -> None:
        """Store the host-visible mount root used for workspaces."""
        self._root = root

    def healthcheck(self) -> None:
        """Ensure the mounted POSIX root is available on the host."""
        if not self._root.exists() or not self._root.is_dir():
            raise FileNotFoundError(f"Mounted POSIX root does not exist: {self._root}")

    def ensure_workspace(self, logical_root: str) -> WorkspaceHandle:
        """Ensure one logical workspace directory exists under the mount root."""
        workspace_path = self._root.joinpath(*_normalize_key(logical_root))
        workspace_path.mkdir(parents=True, exist_ok=True)
        return WorkspaceHandle(logical_root=logical_root, host_path=workspace_path)

    def delete_workspace(self, logical_root: str) -> None:
        """Delete one logical workspace tree from the mounted filesystem."""
        workspace_path = self._root.joinpath(*_normalize_key(logical_root))
        shutil.rmtree(workspace_path, ignore_errors=True)

    def local_root(self) -> Path:
        """Return the mounted POSIX root directory."""
        return self._root
