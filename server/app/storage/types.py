"""Storage provider interfaces and shared value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    """Metadata returned after one object payload is persisted."""

    storage_backend: str
    object_key: str
    size_bytes: int


@dataclass(frozen=True)
class WorkspaceHandle:
    """Provider-resolved workspace directory visible to sandbox-manager."""

    logical_root: str
    host_path: Path
    sandbox_path: str = "/workspace"


class ObjectStorageProvider(Protocol):
    """Blob-style storage contract used by Pivot services."""

    backend_name: str

    def healthcheck(self) -> None:
        """Raise when the provider is not healthy enough to use."""
        ...

    def get_bytes(self, key: str) -> bytes:
        """Return the raw bytes stored under one logical key."""
        ...

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Persist one raw byte payload under the provided logical key."""
        ...

    def delete(self, key: str) -> None:
        """Delete one logical key when present."""
        ...

    def exists(self, key: str) -> bool:
        """Return whether one logical key currently exists."""
        ...

    def resolve_local_path(self, key: str) -> Path:
        """Return a host-local path only when the provider supports one."""
        ...


class POSIXWorkspaceProvider(Protocol):
    """Directory-tree contract used to provide sandbox workspaces."""

    backend_name: str

    def healthcheck(self) -> None:
        """Raise when the provider is not healthy enough to use."""
        ...

    def ensure_workspace(self, logical_root: str) -> WorkspaceHandle:
        """Ensure the logical workspace exists and return its host path."""
        ...

    def delete_workspace(self, logical_root: str) -> None:
        """Delete one logical workspace tree when present."""
        ...

    def local_root(self) -> Path:
        """Return the local root directory when the provider is path-backed."""
        ...
