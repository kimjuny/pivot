"""Storage status APIs."""

from __future__ import annotations

from app.api.permissions import permissions
from app.security.permission_catalog import Permission
from app.services.storage_status_service import StorageStatusService
from fastapi import APIRouter, Depends
from pydantic import BaseModel

router = APIRouter()


class StorageStatusResponse(BaseModel):
    """Expose the resolved storage profile for diagnostics and UX banners."""

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


@router.get("/system/storage-status", response_model=StorageStatusResponse)
async def get_storage_status(
    current_user=Depends(permissions(Permission.STORAGE_VIEW)),
) -> StorageStatusResponse:
    """Return the active storage profile plus fallback state."""
    del current_user
    snapshot = StorageStatusService().get_status()
    return StorageStatusResponse(
        requested_profile=snapshot.requested_profile,
        active_profile=snapshot.active_profile,
        object_storage_backend=snapshot.object_storage_backend,
        posix_workspace_backend=snapshot.posix_workspace_backend,
        fallback_reason=snapshot.fallback_reason,
        backend_workspace_root=snapshot.backend_workspace_root,
        external_posix_root=snapshot.external_posix_root,
        external_host_posix_root=snapshot.external_host_posix_root,
        external_posix_root_exists=snapshot.external_posix_root_exists,
        external_filer_reachable=snapshot.external_filer_reachable,
        external_namespace_shared=snapshot.external_namespace_shared,
        external_readiness_reason=snapshot.external_readiness_reason,
    )
