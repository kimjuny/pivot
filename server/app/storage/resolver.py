"""Storage profile resolution and provider bootstrap helpers."""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from app.config import get_settings
from app.storage.providers import (
    LocalFilesystemObjectStorageProvider,
    LocalFilesystemPOSIXWorkspaceProvider,
    MountedPOSIXWorkspaceProvider,
    SeaweedFSFilerObjectStorageProvider,
    default_storage_root,
)
from app.utils.logging_config import get_logger

if TYPE_CHECKING:
    from app.storage.types import ObjectStorageProvider, POSIXWorkspaceProvider

logger = get_logger("storage_resolver")

_SUPPORTED_EXTERNAL_PROFILES = {"seaweedfs"}
_SEAWEEDFS_HEALTHCHECK_TIMEOUT_SECONDS = 2.0
_SEAWEEDFS_HEALTHCHECK_POLL_INTERVAL_SECONDS = 0.1

_SEAWEEDFS_REASON_NOT_CONFIGURED = "seaweedfs_not_configured"
_SEAWEEDFS_REASON_FILER_UNREACHABLE = "seaweedfs_filer_unreachable"
_SEAWEEDFS_REASON_POSIX_ROOT_MISSING = "seaweedfs_posix_root_missing"
_SEAWEEDFS_REASON_NAMESPACE_MISMATCH = "seaweedfs_namespace_mismatch"
_SEAWEEDFS_REASON_POSIX_IO_FAILED = "seaweedfs_posix_io_failed"


@dataclass(frozen=True)
class ResolvedStorageProfile:
    """Resolved storage profile plus the providers backing it."""

    requested_profile: str
    active_profile: str
    object_storage: ObjectStorageProvider
    posix_workspace: POSIXWorkspaceProvider
    fallback_reason: str | None = None


@dataclass(frozen=True)
class SeaweedFSReadiness:
    """Structured readiness details for one SeaweedFS external profile."""

    is_configured: bool
    filer_reachable: bool
    posix_root_exists: bool
    namespace_shared: bool
    posix_writable: bool
    reason_code: str | None = None
    reason_detail: str | None = None


def _local_storage_root() -> Path:
    """Return the currently configured local storage root."""
    settings = get_settings()
    if settings.STORAGE_LOCAL_ROOT:
        return Path(settings.STORAGE_LOCAL_ROOT).expanduser().resolve()
    return default_storage_root().resolve()


def _resolve_local_profile(*, requested_profile: str) -> ResolvedStorageProfile:
    """Return the local fallback profile for the current runtime."""
    root = _local_storage_root()
    object_storage = LocalFilesystemObjectStorageProvider(root=root)
    posix_workspace = LocalFilesystemPOSIXWorkspaceProvider(root=root)
    object_storage.healthcheck()
    posix_workspace.healthcheck()
    return ResolvedStorageProfile(
        requested_profile=requested_profile,
        active_profile="local_fs",
        object_storage=object_storage,
        posix_workspace=posix_workspace,
        fallback_reason=(
            None if requested_profile == "local_fs" else "external_profile_unavailable"
        ),
    )


def _resolve_local_auto_profile() -> ResolvedStorageProfile:
    """Return one clean `auto` resolution that simply stays on local storage."""
    local_profile = _resolve_local_profile(requested_profile="auto")
    return ResolvedStorageProfile(
        requested_profile=local_profile.requested_profile,
        active_profile=local_profile.active_profile,
        object_storage=local_profile.object_storage,
        posix_workspace=local_profile.posix_workspace,
        fallback_reason=None,
    )


def _resolve_seaweedfs_profile(
    *,
    requested_profile: str,
) -> ResolvedStorageProfile:
    """Resolve one SeaweedFS-backed profile or raise when misconfigured."""
    readiness = inspect_seaweedfs_readiness()
    if not readiness.is_configured:
        raise ValueError("SeaweedFS profile is not configured.")
    if not readiness.filer_reachable:
        raise RuntimeError(readiness.reason_detail or "SeaweedFS filer is unreachable.")
    if not readiness.posix_root_exists:
        raise FileNotFoundError(
            readiness.reason_detail or "SeaweedFS POSIX root does not exist."
        )
    if not readiness.namespace_shared:
        raise RuntimeError(
            readiness.reason_detail
            or "SeaweedFS POSIX root is not exposing the filer namespace."
        )
    if not readiness.posix_writable:
        raise RuntimeError(
            readiness.reason_detail
            or "SeaweedFS POSIX root is not reliably writable."
        )

    settings = get_settings()
    filer_endpoint = settings.STORAGE_SEAWEEDFS_FILER_ENDPOINT
    posix_root_setting = settings.STORAGE_SEAWEEDFS_POSIX_ROOT
    assert filer_endpoint is not None
    assert posix_root_setting is not None
    posix_root = Path(posix_root_setting).expanduser().resolve()
    object_storage = SeaweedFSFilerObjectStorageProvider(
        filer_endpoint=filer_endpoint,
        posix_root=posix_root,
    )
    posix_workspace = MountedPOSIXWorkspaceProvider(root=posix_root)
    object_storage.healthcheck()
    posix_workspace.healthcheck()
    _verify_seaweedfs_shared_namespace(object_storage)
    _verify_posix_root_writable(posix_root)
    return ResolvedStorageProfile(
        requested_profile=requested_profile,
        active_profile="seaweedfs",
        object_storage=object_storage,
        posix_workspace=posix_workspace,
        fallback_reason=None,
    )


def _verify_seaweedfs_shared_namespace(
    object_storage: SeaweedFSFilerObjectStorageProvider,
) -> None:
    """Ensure SeaweedFS object and POSIX views point at the same namespace.

    Why: a plain local directory mounted into the backend container is not a
    valid external POSIX provider. The external profile is only correct when a
    filer upload becomes visible from the configured POSIX root as the same
    logical file tree.
    """
    probe_key = f".pivot-healthcheck/{uuid4()}.txt"
    probe_bytes = uuid4().hex.encode("utf-8")
    probe_path = object_storage.resolve_local_path(probe_key)
    try:
        object_storage.put_bytes(
            probe_key,
            probe_bytes,
            content_type="text/plain; charset=utf-8",
        )
        deadline = time.monotonic() + _SEAWEEDFS_HEALTHCHECK_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            try:
                if probe_path.exists():
                    return
            except OSError:
                # Why: filer uploads may appear with server-side uid/gid metadata that
                # makes byte reads unreliable across the container/FUSE boundary during
                # bootstrap, while path visibility is the actual namespace signal we
                # need here.
                pass
            time.sleep(_SEAWEEDFS_HEALTHCHECK_POLL_INTERVAL_SECONDS)
        raise RuntimeError(
            "SeaweedFS filer writes are not visible from the configured POSIX "
            "root. The current POSIX root is not exposing the same namespace, "
            "which usually means it is a plain local directory instead of a "
            "SeaweedFS mount."
        )
    finally:
        try:
            object_storage.delete(probe_key)
        except Exception:
            logger.warning("Failed to remove SeaweedFS healthcheck probe '%s'.", probe_key)


def _verify_posix_root_writable(posix_root: Path) -> None:
    """Ensure the mounted POSIX root supports direct backend file writes.

    Why: agent sandboxes ultimately edit files through plain POSIX syscalls
    under `/workspace`. If the configured mount only exposes names but fails on
    actual file writes, activating the external profile would surface runtime
    `Errno 5` failures during tool execution.
    """
    probe_dir = posix_root / ".pivot-posix-io-healthcheck"
    probe_path = probe_dir / f"{uuid4()}.txt"
    probe_bytes = uuid4().hex.encode("utf-8")
    try:
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_path.write_bytes(probe_bytes)
        if probe_path.read_bytes() != probe_bytes:
            raise RuntimeError("POSIX root returned mismatched bytes after write.")
    except Exception as exc:
        raise RuntimeError(
            "The configured SeaweedFS POSIX root is not reliably writable from "
            "the backend container."
        ) from exc
    finally:
        try:
            probe_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove POSIX IO probe '%s'.", probe_path)
        with suppress(Exception):
            probe_dir.rmdir()


def inspect_seaweedfs_readiness() -> SeaweedFSReadiness:
    """Inspect whether SeaweedFS can currently back both object and POSIX views."""
    settings = get_settings()
    filer_endpoint = settings.STORAGE_SEAWEEDFS_FILER_ENDPOINT
    posix_root_setting = settings.STORAGE_SEAWEEDFS_POSIX_ROOT
    if not filer_endpoint or not posix_root_setting:
        return SeaweedFSReadiness(
            is_configured=False,
            filer_reachable=False,
            posix_root_exists=False,
            namespace_shared=False,
            posix_writable=False,
            reason_code=_SEAWEEDFS_REASON_NOT_CONFIGURED,
            reason_detail=(
                "SeaweedFS external storage is not configured. "
                "Set both STORAGE_SEAWEEDFS_FILER_ENDPOINT and "
                "STORAGE_SEAWEEDFS_POSIX_ROOT."
            ),
        )

    assert filer_endpoint is not None
    assert posix_root_setting is not None
    posix_root = Path(posix_root_setting).expanduser().resolve()
    posix_root_exists = posix_root.exists() and posix_root.is_dir()
    object_storage = SeaweedFSFilerObjectStorageProvider(
        filer_endpoint=filer_endpoint,
        posix_root=posix_root,
    )

    try:
        object_storage.healthcheck()
    except Exception as exc:
        return SeaweedFSReadiness(
            is_configured=True,
            filer_reachable=False,
            posix_root_exists=posix_root_exists,
            namespace_shared=False,
            posix_writable=False,
            reason_code=_SEAWEEDFS_REASON_FILER_UNREACHABLE,
            reason_detail=f"SeaweedFS filer is unreachable: {exc}",
        )

    if not posix_root_exists:
        return SeaweedFSReadiness(
            is_configured=True,
            filer_reachable=True,
            posix_root_exists=False,
            namespace_shared=False,
            posix_writable=False,
            reason_code=_SEAWEEDFS_REASON_POSIX_ROOT_MISSING,
            reason_detail=(
                "The configured SeaweedFS POSIX root does not exist or is not a "
                f"directory: {posix_root}"
            ),
        )

    try:
        _verify_seaweedfs_shared_namespace(object_storage)
    except Exception as exc:
        return SeaweedFSReadiness(
            is_configured=True,
            filer_reachable=True,
            posix_root_exists=True,
            namespace_shared=False,
            posix_writable=False,
            reason_code=_SEAWEEDFS_REASON_NAMESPACE_MISMATCH,
            reason_detail=str(exc),
        )

    try:
        _verify_posix_root_writable(posix_root)
    except Exception as exc:
        return SeaweedFSReadiness(
            is_configured=True,
            filer_reachable=True,
            posix_root_exists=True,
            namespace_shared=True,
            posix_writable=False,
            reason_code=_SEAWEEDFS_REASON_POSIX_IO_FAILED,
            reason_detail=str(exc),
        )

    return SeaweedFSReadiness(
        is_configured=True,
        filer_reachable=True,
        posix_root_exists=True,
        namespace_shared=True,
        posix_writable=True,
    )


def _resolve_auto_profile() -> ResolvedStorageProfile:
    """Prefer SeaweedFS when it is truly available, else use local_fs cleanly."""
    readiness = inspect_seaweedfs_readiness()
    if not readiness.is_configured:
        return _resolve_local_auto_profile()

    if readiness.namespace_shared and readiness.posix_writable:
        return _resolve_seaweedfs_profile(requested_profile="auto")

    settings = get_settings()
    logger.warning(
        "Storage profile 'auto' detected SeaweedFS but could not activate it. "
        "filer_endpoint=%s posix_root=%s reason=%s",
        settings.STORAGE_SEAWEEDFS_FILER_ENDPOINT,
        settings.STORAGE_SEAWEEDFS_POSIX_ROOT,
        readiness.reason_detail,
    )
    local_profile = _resolve_local_profile(requested_profile="auto")
    return ResolvedStorageProfile(
        requested_profile=local_profile.requested_profile,
        active_profile=local_profile.active_profile,
        object_storage=local_profile.object_storage,
        posix_workspace=local_profile.posix_workspace,
        fallback_reason=readiness.reason_code,
    )


@lru_cache
def get_resolved_storage_profile() -> ResolvedStorageProfile:
    """Resolve the active storage profile, falling back to `local_fs` on errors."""
    settings = get_settings()
    requested_profile = settings.STORAGE_PROFILE.strip() or "local_fs"
    if requested_profile == "auto":
        return _resolve_auto_profile()

    if requested_profile == "local_fs":
        return _resolve_local_profile(requested_profile=requested_profile)

    if requested_profile in _SUPPORTED_EXTERNAL_PROFILES:
        try:
            return _resolve_seaweedfs_profile(requested_profile=requested_profile)
        except Exception as exc:
            logger.warning(
                "Storage profile '%s' failed health checks and will fall back to "
                "local_fs. filer_endpoint=%s posix_root=%s reason=%s",
                requested_profile,
                settings.STORAGE_SEAWEEDFS_FILER_ENDPOINT,
                settings.STORAGE_SEAWEEDFS_POSIX_ROOT,
                exc,
            )
            local_profile = _resolve_local_profile(requested_profile=requested_profile)
            readiness = inspect_seaweedfs_readiness()
            return ResolvedStorageProfile(
                requested_profile=local_profile.requested_profile,
                active_profile=local_profile.active_profile,
                object_storage=local_profile.object_storage,
                posix_workspace=local_profile.posix_workspace,
                fallback_reason=(
                    readiness.reason_code
                    if readiness.is_configured
                    else local_profile.fallback_reason
                ),
            )

    logger.warning(
        "Unknown storage profile '%s'; falling back to local_fs.",
        requested_profile,
    )
    return _resolve_local_profile(requested_profile=requested_profile)
