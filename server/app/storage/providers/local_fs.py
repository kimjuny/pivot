"""Local filesystem-backed storage providers."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.storage.types import (
    ObjectStorageProvider,
    POSIXWorkspaceProvider,
    StoredObject,
    WorkspaceHandle,
)


def default_storage_root() -> Path:
    """Return the current local storage root used by the fallback profile."""
    return Path(__file__).resolve().parent.parent.parent.parent / "workspace"


def _normalize_key(key: str) -> list[str]:
    """Normalize one logical storage key into safe path segments."""
    normalized_key = key.strip().replace("\\", "/")
    if normalized_key == "":
        raise ValueError("Storage key must not be empty.")
    parts = [part for part in normalized_key.split("/") if part not in {"", ".", ".."}]
    if not parts:
        raise ValueError("Storage key must contain at least one safe path segment.")
    return parts


class LocalFilesystemObjectStorageProvider(ObjectStorageProvider):
    """Store logical object keys as ordinary files under one local root."""

    backend_name = "local_fs"

    def __init__(self, root: Path) -> None:
        """Store the filesystem root used for local object persistence."""
        self._root = root

    def healthcheck(self) -> None:
        """Ensure the local storage root exists."""
        self._root.mkdir(parents=True, exist_ok=True)

    def get_bytes(self, key: str) -> bytes:
        """Return one local object's bytes."""
        return self.resolve_local_path(key).read_bytes()

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Persist one local object payload."""
        del content_type
        target_path = self.resolve_local_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return StoredObject(
            storage_backend=self.backend_name,
            object_key=key,
            size_bytes=len(data),
        )

    def delete(self, key: str) -> None:
        """Delete one local object file when present."""
        self.resolve_local_path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        """Return whether one local object file exists."""
        return self.resolve_local_path(key).exists()

    def resolve_local_path(self, key: str) -> Path:
        """Map one logical object key to its local file path."""
        return self._root.joinpath(*_normalize_key(key))


class LocalFilesystemPOSIXWorkspaceProvider(POSIXWorkspaceProvider):
    """Expose workspace trees as ordinary local directories."""

    backend_name = "local_fs"

    def __init__(self, root: Path) -> None:
        """Store the filesystem root used for local workspaces."""
        self._root = root

    def healthcheck(self) -> None:
        """Ensure the local workspace root exists."""
        self._root.mkdir(parents=True, exist_ok=True)

    def ensure_workspace(self, logical_root: str) -> WorkspaceHandle:
        """Ensure the logical workspace directory exists locally."""
        workspace_path = self._root.joinpath(*_normalize_key(logical_root))
        workspace_path.mkdir(parents=True, exist_ok=True)
        return WorkspaceHandle(logical_root=logical_root, host_path=workspace_path)

    def delete_workspace(self, logical_root: str) -> None:
        """Delete one local workspace tree."""
        workspace_path = self._root.joinpath(*_normalize_key(logical_root))
        shutil.rmtree(workspace_path, ignore_errors=True)

    def local_root(self) -> Path:
        """Return the local workspace root directory."""
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root
