"""Service helpers for exposing the active storage profile state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services.workspace_service import backend_workspace_root
from app.storage import get_resolved_storage_profile
from app.storage.resolver import inspect_seaweedfs_readiness


@dataclass(frozen=True)
class StorageStatusSnapshot:
    """Serializable snapshot of the currently resolved storage profile."""

    requested_profile: str
    active_profile: str
    object_storage_backend: str
    posix_workspace_backend: str
    fallback_reason: str | None
    backend_workspace_root: str
    external_posix_root: str | None
    external_host_posix_root: str | None
    external_posix_root_exists: bool
    external_filer_reachable: bool | None
    external_namespace_shared: bool | None
    external_readiness_reason: str | None


class StorageStatusService:
    """Read-only service that reports the resolved storage configuration."""

    def get_status(self) -> StorageStatusSnapshot:
        """Return one snapshot of the active storage runtime state."""
        profile = get_resolved_storage_profile()
        settings = get_settings()
        external_posix_root = settings.STORAGE_SEAWEEDFS_POSIX_ROOT
        external_host_posix_root = settings.STORAGE_SEAWEEDFS_HOST_POSIX_ROOT
        external_posix_root_exists = False
        if external_posix_root:
            external_posix_root_exists = Path(external_posix_root).expanduser().exists()
        readiness = inspect_seaweedfs_readiness()
        return StorageStatusSnapshot(
            requested_profile=profile.requested_profile,
            active_profile=profile.active_profile,
            object_storage_backend=profile.object_storage.backend_name,
            posix_workspace_backend=profile.posix_workspace.backend_name,
            fallback_reason=profile.fallback_reason,
            backend_workspace_root=backend_workspace_root(),
            external_posix_root=external_posix_root,
            external_host_posix_root=external_host_posix_root,
            external_posix_root_exists=external_posix_root_exists,
            external_filer_reachable=(
                readiness.filer_reachable if readiness.is_configured else None
            ),
            external_namespace_shared=(
                readiness.namespace_shared if readiness.is_configured else None
            ),
            external_readiness_reason=readiness.reason_detail,
        )
