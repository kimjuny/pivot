"""Storage abstraction entrypoints for Pivot services."""

from app.storage.resolver import ResolvedStorageProfile, get_resolved_storage_profile
from app.storage.types import (
    ObjectStorageProvider,
    POSIXWorkspaceProvider,
    StoredObject,
    WorkspaceHandle,
)

__all__ = [
    "ObjectStorageProvider",
    "POSIXWorkspaceProvider",
    "ResolvedStorageProfile",
    "StoredObject",
    "WorkspaceHandle",
    "get_resolved_storage_profile",
]
