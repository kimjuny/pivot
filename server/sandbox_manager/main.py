"""Sandbox manager service.

This service is the only component that talks to Podman. Backend calls this
service over HTTP to create, execute in, and destroy sandbox containers.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from podman import PodmanClient  # pyright: ignore[reportMissingImports]
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.sandbox_manager import seaweedfs_bridge
from server.sandbox_manager.schemas import (
    RuntimeBind,
    SandboxExecRequest,
    SandboxExecResponse,
    SandboxRequest,
    SandboxSkillMount,
    SeaweedfsRuntimeStatusResponse,
    WorkspaceRuntimeDriver,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

app = FastAPI(title="Pivot Sandbox Manager")
logger = logging.getLogger("uvicorn.error")
_pool_lock = threading.RLock()
_last_used_by_name: dict[str, float] = {}
_cleanup_started = False


class ManagerSettings(BaseSettings):
    """Runtime settings for sandbox-manager."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    SANDBOX_MANAGER_TOKEN: str = "dev-sandbox-token"
    SANDBOX_PODMAN_BASE_URL: str = "unix:///run/podman/podman.sock"
    SANDBOX_BASE_IMAGE: str = "docker.io/library/python:3.11-slim"
    SANDBOX_NETWORK_MODE: str = "bridge"
    SANDBOX_BACKEND_CONTAINER_NAME: str = "pivot-backend"
    SANDBOX_CONTAINER_PREFIX: str = "pivot-sandbox"
    SANDBOX_DEFAULT_TIMEOUT_SECONDS: int = 30
    SANDBOX_SEAWEEDFS_FILER_URL: str = "http://seaweedfs:8888"
    SANDBOX_SEAWEEDFS_MOUNT_ROOT: str = "/var/lib/pivot/seaweedfs-mnt"
    SANDBOX_SEAWEEDFS_ATTACH_STRATEGY: str = "compose_compat"
    SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT: bool = False
    SANDBOX_POOL_SCAN_INTERVAL_SECONDS: int = 30
    SANDBOX_POOL_IDLE_TTL_SECONDS: int = 86400
    SANDBOX_POOL_MAX_SIZE: int = 100



class _CompatibilityWorkspaceDriver:
    """Temporary runtime driver backed by the legacy backend-visible path mapping."""

    def __init__(self, *, backend_name: str) -> None:
        self.backend_name = backend_name

    def ensure_runtime_ready(self) -> None:
        """Compatibility drivers need no extra helper bootstrap today."""

    def ensure_workspace_ready(self, logical_path: str, mount_mode: str) -> None:
        """Ensure one compatibility workspace directory exists."""
        del mount_mode
        _ensure_workspace_compat_directory(
            _workspace_backend_compat_path_from_contract(
                storage_backend=self.backend_name,
                logical_path=logical_path,
            )
        )

    def build_workspace_bind(self, logical_path: str, mount_mode: str) -> RuntimeBind:
        """Resolve the helper-visible compatibility path for one logical workspace."""
        del mount_mode
        backend_path = _workspace_backend_compat_path_from_contract(
            storage_backend=self.backend_name,
            logical_path=logical_path,
        )
        workspace_host_dir = _resolve_host_path_from_backend_compat_path(backend_path)
        if workspace_host_dir is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not resolve host path for local workspace compatibility path "
                    f"{backend_path!r}."
                ),
            )
        return RuntimeBind(source=workspace_host_dir, destination="/workspace")

    def delete_workspace(self, logical_path: str) -> None:
        """Compatibility drivers currently do not own workspace deletion."""
        del logical_path

    def sync_workspace(self, logical_path: str, mount_mode: str) -> None:
        """Compatibility drivers keep local filesystem state as-is."""
        del logical_path, mount_mode


class LocalFilesystemWorkspaceDriver(_CompatibilityWorkspaceDriver):
    """Migration-only runtime driver for local workspace directories."""

    def __init__(self) -> None:
        super().__init__(backend_name="local_fs")


class SeaweedfsWorkspaceDriver(_CompatibilityWorkspaceDriver):
    """SeaweedFS runtime driver with separate local-dev and production attach modes."""

    def __init__(self) -> None:
        super().__init__(backend_name="seaweedfs")

    def ensure_runtime_ready(self) -> None:
        """Prepare helper-side state for the configured SeaweedFS attach strategy."""
        settings = get_settings()
        _assert_service_reachable(
            settings.SANDBOX_SEAWEEDFS_FILER_URL,
            label="SeaweedFS filer",
        )
        Path(settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT).mkdir(
            parents=True,
            exist_ok=True,
        )

    def ensure_workspace_ready(self, logical_path: str, mount_mode: str) -> None:
        """Prepare one logical workspace for the configured attach strategy."""
        settings = get_settings()
        strategy = self._attach_strategy(settings)
        if strategy == "compose_compat":
            super().ensure_workspace_ready(logical_path, mount_mode)
            self._prepare_runtime_directory(
                filer_url=settings.SANDBOX_SEAWEEDFS_FILER_URL,
                logical_path=logical_path,
                local_dir=self._compat_cache_dir(logical_path),
                mount_mode=mount_mode,
            )
            return

        if self._shared_mount_root_uses_native_mount(settings):
            self._shared_mount_root_dir(logical_path).mkdir(parents=True, exist_ok=True)
            return
        if self._shared_mount_root_requires_native_mount(settings):
            raise HTTPException(
                status_code=500,
                detail=(
                    "SeaweedFS shared mount root requires a native mount at "
                    f"{settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT!r}, but the mount "
                    "is not active."
                ),
            )

        self._prepare_runtime_directory(
            filer_url=settings.SANDBOX_SEAWEEDFS_FILER_URL,
            logical_path=logical_path,
            local_dir=self._shared_mount_root_dir(logical_path),
            mount_mode=mount_mode,
        )

    def build_workspace_bind(self, logical_path: str, mount_mode: str) -> RuntimeBind:
        """Return the bind source matching the configured attach strategy."""
        settings = get_settings()
        strategy = self._attach_strategy(settings)
        if strategy == "compose_compat":
            return super().build_workspace_bind(logical_path, mount_mode)

        del mount_mode
        manager_bind_source = Path(settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT) / logical_path
        host_bind_source = _resolve_host_path_from_self_container_path(
            str(manager_bind_source)
        )
        if host_bind_source is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Could not resolve host path for shared mount root "
                    f"{manager_bind_source!r}."
                ),
            )
        return RuntimeBind(source=host_bind_source, destination="/workspace")

    def sync_workspace(self, logical_path: str, mount_mode: str) -> None:
        """Flush the helper-visible runtime directory back into SeaweedFS."""
        settings = get_settings()
        strategy = self._attach_strategy(settings)
        if not _workspace_mount_mode_should_sync(mount_mode):
            del logical_path, mount_mode
            return
        if (
            strategy == "shared_mount_root"
            and self._shared_mount_root_uses_native_mount(settings)
        ):
            return

        local_dir = (
            self._compat_cache_dir(logical_path)
            if strategy == "compose_compat"
            else self._shared_mount_root_dir(logical_path)
        )
        _sync_local_workspace_to_seaweedfs(
            filer_url=settings.SANDBOX_SEAWEEDFS_FILER_URL,
            logical_path=logical_path,
            local_dir=local_dir,
        )

    @staticmethod
    def _attach_strategy(settings: ManagerSettings) -> str:
        """Normalize and validate the configured SeaweedFS attach strategy."""
        strategy = settings.SANDBOX_SEAWEEDFS_ATTACH_STRATEGY.strip().lower()
        if strategy in {"compose_compat", "shared_mount_root"}:
            return strategy
        raise HTTPException(
            status_code=500,
            detail=(
                "Unsupported SeaweedFS attach strategy "
                f"{settings.SANDBOX_SEAWEEDFS_ATTACH_STRATEGY!r}."
            ),
        )

    def _compat_cache_dir(self, logical_path: str) -> Path:
        """Return the manager-visible compose-compat cache directory path."""
        backend_path = _workspace_backend_compat_path_from_contract(
            storage_backend="seaweedfs",
            logical_path=logical_path,
        )
        return Path(backend_path)

    def _shared_mount_root_dir(self, logical_path: str) -> Path:
        """Return the helper-owned shared mount root directory for one workspace."""
        return Path(get_settings().SANDBOX_SEAWEEDFS_MOUNT_ROOT) / logical_path

    @staticmethod
    def _shared_mount_root_host_path(settings: ManagerSettings) -> str | None:
        """Return the host-visible path that backs the shared mount root."""
        return _resolve_host_path_from_self_container_path(
            settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT
        )

    @classmethod
    def _shared_mount_root_uses_native_mount(cls, settings: ManagerSettings) -> bool:
        """Return whether the configured shared root is a real mounted filesystem.

        Why: when the shared root is mounted on the Podman machine host, the
        manager container can see the mounted contents through its volume, but
        `os.path.ismount()` inside the container still reports false. The
        native-mount decision therefore needs to prefer the host-visible backing
        path and only fall back to the container path when host resolution is
        unavailable.
        """
        host_path = cls._shared_mount_root_host_path(settings)
        if host_path is not None and os.path.ismount(host_path):
            return True
        return os.path.ismount(settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT)

    @staticmethod
    def _shared_mount_root_requires_native_mount(settings: ManagerSettings) -> bool:
        """Return whether fallback bridge mode is disallowed for shared root."""
        return settings.SANDBOX_SEAWEEDFS_REQUIRE_NATIVE_MOUNT

    def _prepare_runtime_directory(
        self,
        *,
        filer_url: str,
        logical_path: str,
        local_dir: Path,
        mount_mode: str,
    ) -> None:
        """Hydrate one helper-visible runtime directory from SeaweedFS.

        Why: local development still needs a concrete helper-owned directory to
        bind into sandboxes, but that directory should live under the manager's
        shared mount root rather than inside the backend repo tree.
        """
        local_dir.mkdir(parents=True, exist_ok=True)
        has_remote_entries = _seaweedfs_directory_has_entries(
            filer_url=filer_url,
            logical_path=logical_path,
        )
        has_local_entries = any(local_dir.iterdir())

        if has_remote_entries:
            _sync_local_workspace_from_seaweedfs(
                filer_url=filer_url,
                logical_path=logical_path,
                local_dir=local_dir,
            )
            return

        if has_local_entries and _workspace_mount_mode_should_sync(mount_mode):
            _sync_local_workspace_to_seaweedfs(
                filer_url=filer_url,
                logical_path=logical_path,
                local_dir=local_dir,
            )


@lru_cache
def get_settings() -> ManagerSettings:
    """Get cached manager settings."""
    return ManagerSettings()


@lru_cache
def get_client() -> Any:
    """Get cached Podman client."""
    settings = get_settings()
    return PodmanClient(base_url=settings.SANDBOX_PODMAN_BASE_URL)


@app.middleware("http")
async def log_request_timing(request: Request, call_next: Any) -> Any:
    """Log one line per request with response status and elapsed milliseconds."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        client = request.client
        client_addr = f"{client.host}:{client.port}" if client else "-"
        logger.exception(
            '%s - "%s %s HTTP/%s" 500 - %dms',
            client_addr,
            request.method,
            request.url.path,
            request.scope.get("http_version", "1.1"),
            elapsed_ms,
        )
        raise

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    client = request.client
    client_addr = f"{client.host}:{client.port}" if client else "-"
    logger.info(
        '%s - "%s %s HTTP/%s" %d - %dms',
        client_addr,
        request.method,
        request.url.path,
        request.scope.get("http_version", "1.1"),
        response.status_code,
        elapsed_ms,
    )
    return response


def _require_token(x_sandbox_token: str | None = Header(default=None)) -> None:
    """Require static shared token for backend-to-manager calls."""
    settings = get_settings()
    if x_sandbox_token != settings.SANDBOX_MANAGER_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid sandbox token.")


def _sandbox_name(username: str, workspace_id: str) -> str:
    """Build deterministic sandbox container name."""
    prefix = get_settings().SANDBOX_CONTAINER_PREFIX
    user = username.strip() or "default"
    workspace = workspace_id.strip() or "default"
    return f"{prefix}-{user}-{workspace}"


def _skills_volume_name(username: str, workspace_id: str) -> str:
    """Build deterministic named-volume identifier for sandbox-local skills."""
    return f"{_sandbox_name(username, workspace_id)}-skills"


_assert_service_reachable = seaweedfs_bridge._assert_service_reachable
_seaweedfs_directory_has_entries = seaweedfs_bridge._seaweedfs_directory_has_entries
_seaweedfs_walk_file_paths = seaweedfs_bridge._seaweedfs_walk_file_paths
_seaweedfs_walk_files = seaweedfs_bridge._seaweedfs_walk_files
_sync_local_workspace_from_seaweedfs = (
    seaweedfs_bridge._sync_local_workspace_from_seaweedfs
)
_workspace_mount_mode_should_sync = seaweedfs_bridge._workspace_mount_mode_should_sync
_sync_local_workspace_to_seaweedfs = (
    seaweedfs_bridge._sync_local_workspace_to_seaweedfs
)


def _backend_container() -> Any:
    """Return the backend container configured for workspace source discovery."""
    settings = get_settings()
    containers = get_client().containers.list(
        all=True,
        filters={"name": settings.SANDBOX_BACKEND_CONTAINER_NAME},
    )
    if not containers:
        raise HTTPException(
            status_code=500,
            detail=(
                "Backend container not found for sandbox-manager: "
                f"{settings.SANDBOX_BACKEND_CONTAINER_NAME}"
            ),
        )
    return containers[0]


def _self_container() -> Any | None:
    """Return sandbox-manager container itself, if discoverable."""
    hostname = os.getenv("HOSTNAME")
    if not hostname:
        return None
    client = get_client()
    try:
        return client.containers.get(hostname)
    except Exception:
        containers = client.containers.list(all=True, filters={"name": hostname})
        return containers[0] if containers else None


def _get_container_mounts(container: Any) -> list[dict[str, Any]]:
    """Safely read mount list from Podman container inspect data."""
    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        mounts = attrs.get("Mounts", [])
        if isinstance(mounts, list):
            attr_mounts = [m for m in mounts if isinstance(m, dict)]
            if attr_mounts:
                return attr_mounts

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            mounts = inspected.get("Mounts", [])
            if isinstance(mounts, list):
                return [m for m in mounts if isinstance(m, dict)]

    raise HTTPException(
        status_code=500,
        detail="Failed to inspect backend container mounts.",
    )


def _mount_destination(mount: dict[str, Any]) -> str | None:
    """Read destination path from mount entry across engine variants."""
    for key in ("Destination", "destination", "Target", "target"):
        value = mount.get(key)
        if isinstance(value, str):
            return value
    return None


def _mount_source(mount: dict[str, Any]) -> str | None:
    """Read source path from mount entry across engine variants."""
    for key in ("Source", "source", "Src", "src"):
        value = mount.get(key)
        if isinstance(value, str):
            return value
    return None


def _ensure_workspace_compat_directory(path_in_backend: str) -> None:
    """Create the backend-visible local compatibility directory for one workspace."""
    if not path_in_backend.startswith("/app/server/workspace/"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Local workspace compatibility path must stay under "
                "/app/server/workspace."
            ),
        )

    backend = _backend_container()
    try:
        exec_result = backend.exec_run(
            ["mkdir", "-p", path_in_backend],
            workdir="/",
            tty=False,
            stream=False,
            socket=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to prepare backend workspace dir: {exc}",
        ) from exc

    if isinstance(exec_result, tuple) and len(exec_result) == 2:
        exit_code = int(exec_result[0])
    else:
        exit_code = int(getattr(exec_result, "exit_code", -1))

    if exit_code != 0:
        raise HTTPException(
            status_code=500,
            detail=(
                "Backend workspace directory creation failed "
                f"(exit_code={exit_code})"
            ),
        )


def _workspace_backend_compat_path_from_contract(
    *,
    storage_backend: str,
    logical_path: str,
) -> str:
    """Map one workspace mount contract to the backend-local compatibility path."""
    normalized_backend = storage_backend.strip().lower()
    normalized_logical_path = logical_path.strip().strip("/")
    if normalized_logical_path == "":
        raise HTTPException(status_code=400, detail="logical_path must not be empty.")
    if normalized_backend not in {"local_fs", "seaweedfs"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported workspace storage_backend '{storage_backend}'.",
        )
    return f"/app/server/workspace/{normalized_logical_path}"


@lru_cache(maxsize=4)
def _workspace_runtime_driver(storage_backend: str) -> WorkspaceRuntimeDriver:
    """Return the runtime driver for one workspace storage backend."""
    normalized_backend = storage_backend.strip().lower()
    if normalized_backend == "local_fs":
        return LocalFilesystemWorkspaceDriver()
    if normalized_backend == "seaweedfs":
        return SeaweedfsWorkspaceDriver()
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported workspace storage_backend '{storage_backend}'.",
    )


def _resolve_host_path_from_backend_compat_path(path_in_backend: str) -> str | None:
    """Resolve host-side path for a backend-local compatibility path.

    Args:
        path_in_backend: Absolute path as seen from the backend container.

    Returns:
        Host-side absolute path if mount mapping exists; otherwise ``None``.
    """
    if not path_in_backend.startswith("/"):
        return None

    mount_sets: list[list[dict[str, Any]]] = []
    with suppress(HTTPException):
        mount_sets.append(_get_container_mounts(_backend_container()))

    self_container = _self_container()
    if self_container is not None:
        with suppress(HTTPException):
            mount_sets.append(_get_container_mounts(self_container))

    best_match: tuple[int, str] | None = None
    for mounts in mount_sets:
        for mount in mounts:
            destination = _mount_destination(mount)
            source = _mount_source(mount)
            if not destination or not source:
                continue
            normalized_destination = destination.rstrip("/") or "/"
            if path_in_backend == normalized_destination or path_in_backend.startswith(
                f"{normalized_destination}/"
            ):
                score = len(normalized_destination)
            else:
                continue
            if best_match is None or score > best_match[0]:
                best_match = (score, source.rstrip("/"))

    if best_match is None:
        return None

    matched_destination_len, matched_source = best_match
    matched_destination = path_in_backend[:matched_destination_len]
    suffix = path_in_backend[len(matched_destination) :].lstrip("/")
    if suffix:
        return f"{matched_source}/{suffix}"
    return matched_source


def _resolve_host_path_from_self_container_path(path_in_manager: str) -> str | None:
    """Resolve one sandbox-manager-local path to the Podman host-visible path.

    Args:
        path_in_manager: Absolute path as seen inside the sandbox-manager
            container.

    Returns:
        Host-visible absolute path if the sandbox-manager mount mapping can be
        resolved; otherwise ``None``.
    """
    if not path_in_manager.startswith("/"):
        return None

    self_container = _self_container()
    if self_container is None:
        return None

    with suppress(HTTPException):
        mounts = _get_container_mounts(self_container)
        best_match: tuple[int, str] | None = None
        for mount in mounts:
            destination = _mount_destination(mount)
            source = _mount_source(mount)
            if not destination or not source:
                continue
            normalized_destination = destination.rstrip("/") or "/"
            if (
                path_in_manager == normalized_destination
                or path_in_manager.startswith(f"{normalized_destination}/")
            ):
                score = len(normalized_destination)
            else:
                continue
            if best_match is None or score > best_match[0]:
                best_match = (score, source.rstrip("/"))

        if best_match is None:
            return None

        matched_destination_len, matched_source = best_match
        matched_destination = path_in_manager[:matched_destination_len]
        suffix = path_in_manager[len(matched_destination) :].lstrip("/")
        if suffix:
            return f"{matched_source}/{suffix}"
        return matched_source

    return None


def _normalize_skill_mounts(
    raw_skills: Sequence[SandboxSkillMount | dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Sanitize canonical skill materialization metadata from backend."""
    if not raw_skills:
        return []

    normalized: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for item in raw_skills:
        if isinstance(item, SandboxSkillMount):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        raw_name = item.get("name")
        raw_location = item.get("canonical_location")
        if not isinstance(raw_name, str) or not isinstance(raw_location, str):
            continue

        skill_name = raw_name.strip()
        location = raw_location.strip()
        if not skill_name or skill_name in seen_names:
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+", skill_name) is None:
            logger.warning("sandbox.skills skip invalid skill name: %s", raw_name)
            continue
        if not location.startswith("/app/server/"):
            logger.warning(
                "sandbox.skills skip unsafe location skill=%s location=%s",
                skill_name,
                location,
            )
            continue

        seen_names.add(skill_name)
        normalized.append({"name": skill_name, "canonical_location": location})
    return normalized


def _decode_bytes(value: Any) -> str:
    """Decode Podman API output into a UTF-8 string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _find_container(name: str) -> Any | None:
    """Return existing container by exact name when present."""
    client = get_client()
    containers = client.containers.list(all=True, filters={"name": name})
    return containers[0] if containers else None


def _touch_container(name: str) -> None:
    """Update last-used timestamp for one sandbox container."""
    with _pool_lock:
        _last_used_by_name[name] = time.time()


def _remove_container_fast(
    container: Any, *, reason: str, remove_skills_volume: bool = False
) -> int:
    """Remove container with fast path, avoiding long graceful-stop timeout."""
    started = time.perf_counter()
    volume_name = _container_skills_volume_name(container)
    with suppress(Exception):
        container.kill()
    container.remove(force=True)
    if remove_skills_volume and volume_name:
        _remove_skills_volume(volume_name)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("sandbox.remove reason=%s remove_ms=%d", reason, elapsed_ms)
    return elapsed_ms


def _ensure_skills_volume(username: str, workspace_id: str) -> str:
    """Create the sandbox-local named volume used for ``/workspace/skills``."""
    volume_name = _skills_volume_name(username, workspace_id)
    client = get_client()
    try:
        client.volumes.get(volume_name)
    except Exception:
        client.volumes.create(
            name=volume_name,
            labels={
                "pivot.sandbox.username": username,
                "pivot.sandbox.workspace_id": workspace_id,
                "pivot.sandbox.kind": "skills",
            },
        )
    return volume_name


def _remove_skills_volume(volume_name: str) -> None:
    """Delete one sandbox-local skills volume when it is no longer needed."""
    try:
        volume = get_client().volumes.get(volume_name)
        try:
            volume.remove(force=True)
        except TypeError:
            volume.remove()
    except Exception as exc:
        logger.warning(
            "sandbox.volume remove failed volume=%s err=%s", volume_name, exc
        )


def _container_working_dir(container: Any) -> str:
    """Read configured working directory from container inspect data."""
    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        config = attrs.get("Config")
        if isinstance(config, dict):
            workdir = config.get("WorkingDir")
            if isinstance(workdir, str):
                return workdir

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            config = inspected.get("Config")
            if isinstance(config, dict):
                workdir = config.get("WorkingDir")
                if isinstance(workdir, str):
                    return workdir

    return ""


def _container_labels(container: Any) -> dict[str, str]:
    """Read container labels from inspect data across engine variants."""
    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        config = attrs.get("Config")
        if isinstance(config, dict):
            labels = config.get("Labels")
            if isinstance(labels, dict):
                return {
                    str(key): str(value)
                    for key, value in labels.items()
                    if isinstance(key, str)
                }

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            config = inspected.get("Config")
            if isinstance(config, dict):
                labels = config.get("Labels")
                if isinstance(labels, dict):
                    return {
                        str(key): str(value)
                        for key, value in labels.items()
                        if isinstance(key, str)
                    }

    return {}


def _container_image_ref(container: Any) -> str | None:
    """Read configured image reference from container inspect data."""
    labels = _container_labels(container)
    labeled_ref = labels.get("pivot.sandbox.base_image_ref")
    if labeled_ref:
        return labeled_ref

    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        config = attrs.get("Config")
        if isinstance(config, dict):
            image = config.get("Image")
            if isinstance(image, str):
                return image
        image_name = attrs.get("ImageName")
        if isinstance(image_name, str):
            return image_name

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            config = inspected.get("Config")
            if isinstance(config, dict):
                image = config.get("Image")
                if isinstance(image, str):
                    return image
            image_name = inspected.get("ImageName")
            if isinstance(image_name, str):
                return image_name

    return None


def _container_image_id(container: Any) -> str | None:
    """Read the concrete image ID used by an existing container."""
    labels = _container_labels(container)
    labeled_id = labels.get("pivot.sandbox.base_image_id")
    if labeled_id:
        return labeled_id

    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        image_id = attrs.get("Image")
        if isinstance(image_id, str):
            return image_id

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            image_id = inspected.get("Image")
            if isinstance(image_id, str):
                return image_id

    image = getattr(container, "image", None)
    image_id = getattr(image, "id", None)
    if isinstance(image_id, str):
        return image_id
    return None


def _container_network_mode(container: Any) -> str | None:
    """Read configured network mode from an existing sandbox container."""
    labels = _container_labels(container)
    labeled_mode = labels.get("pivot.sandbox.network_mode")
    if labeled_mode:
        return labeled_mode

    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        host_config = attrs.get("HostConfig")
        if isinstance(host_config, dict):
            network_mode = host_config.get("NetworkMode")
            if isinstance(network_mode, str):
                return network_mode

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            host_config = inspected.get("HostConfig")
            if isinstance(host_config, dict):
                network_mode = host_config.get("NetworkMode")
                if isinstance(network_mode, str):
                    return network_mode

    return None


def _container_skills_volume_name(container: Any) -> str | None:
    """Read the configured sandbox-local skills volume name from labels."""
    labels = _container_labels(container)
    volume_name = labels.get("pivot.sandbox.skills_volume_name")
    if isinstance(volume_name, str) and volume_name:
        return volume_name
    return None


def _container_workspace_contract(container: Any) -> tuple[str, str, str] | None:
    """Read workspace storage contract labels from an existing sandbox."""
    labels = _container_labels(container)
    storage_backend = labels.get("pivot.sandbox.workspace_storage_backend")
    logical_path = labels.get("pivot.sandbox.workspace_logical_path")
    mount_mode = labels.get("pivot.sandbox.workspace_mount_mode")
    if not (
        isinstance(storage_backend, str)
        and storage_backend
        and isinstance(logical_path, str)
        and logical_path
        and isinstance(mount_mode, str)
        and mount_mode
    ):
        return None
    return storage_backend, logical_path, mount_mode


def _resolve_image_id(image_ref: str) -> str | None:
    """Resolve the current local image ID for a configured image reference."""
    try:
        image = get_client().images.get(image_ref)
    except Exception as exc:
        logger.warning(
            "sandbox.image resolve failed image=%s err=%s",
            image_ref,
            exc,
        )
        return None

    image_id = getattr(image, "id", None)
    if isinstance(image_id, str):
        return image_id

    attrs = getattr(image, "attrs", None)
    if isinstance(attrs, dict):
        for key in ("Id", "ID"):
            value = attrs.get(key)
            if isinstance(value, str):
                return value
    return None


def _should_recreate_container(
    container: Any,
    *,
    expected_skills_volume_name: str,
    expected_workspace_mount_source: str,
) -> tuple[bool, str]:
    """Decide whether an existing sandbox container must be recreated.

    Recreate when configuration is unsafe/legacy, skill mounts drift, or the
    base sandbox image tag now points at a newer local image:
    - working dir is not ``/workspace``
    - full project mounts (e.g. ``/app/server`` or ``/app/web``) are present
    - ``/workspace`` mount is missing
    - legacy bind mounts exist under ``/workspace/skills/*``
    - current container image differs from ``SANDBOX_BASE_IMAGE``
    - current container network mode differs from ``SANDBOX_NETWORK_MODE``
    """
    settings = get_settings()
    workdir = _container_working_dir(container)
    try:
        mounts = _get_container_mounts(container)
    except HTTPException:
        # Do not force recreate on inspect compatibility issues.
        return False, "inspect_unavailable"

    mounts_by_destination = {
        destination: mount
        for mount in mounts
        if isinstance((destination := _mount_destination(mount)), str)
    }
    destinations = set(mounts_by_destination)

    if workdir != "/workspace":
        return True, "workdir_mismatch"
    if "/workspace" not in destinations:
        return True, "missing_workspace_mount"
    workspace_mount_source = _mount_source(mounts_by_destination["/workspace"])
    if workspace_mount_source != expected_workspace_mount_source:
        return True, "workspace_mount_source_mismatch"
    if "/workspace/skills" not in destinations:
        return True, "missing_skills_volume_mount"
    if any(
        isinstance(destination, str)
        and destination.startswith("/workspace/skills/")
        and destination != "/workspace/skills"
        for destination in destinations
    ):
        return True, "legacy_skill_bind_mount"
    if "/app/server" in destinations or "/app/web" in destinations:
        return True, "unsafe_project_mount"
    container_skills_volume_name = _container_skills_volume_name(container)
    if container_skills_volume_name != expected_skills_volume_name:
        return True, "skills_volume_mismatch"
    configured_image_ref = settings.SANDBOX_BASE_IMAGE
    container_image_ref = _container_image_ref(container)
    if container_image_ref and container_image_ref != configured_image_ref:
        return True, "base_image_ref_mismatch"
    configured_image_id = _resolve_image_id(configured_image_ref)
    container_image_id = _container_image_id(container)
    if (
        configured_image_id is not None
        and container_image_id is not None
        and configured_image_id != container_image_id
    ):
        return True, "base_image_id_mismatch"
    configured_network_mode = settings.SANDBOX_NETWORK_MODE
    container_network_mode = _container_network_mode(container)
    if container_network_mode != configured_network_mode:
        return True, "network_mode_mismatch"
    return False, "ok"


def _exec_json_in_container(
    container: Any,
    *,
    cmd: list[str],
    workdir: str = "/",
    error_prefix: str,
) -> dict[str, Any]:
    """Run one command in a container and parse a JSON-object stdout payload."""
    try:
        exec_result = container.exec_run(
            cmd,
            workdir=workdir,
            demux=True,
            tty=False,
            stream=False,
            socket=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{error_prefix}: {exc}") from exc

    if isinstance(exec_result, tuple) and len(exec_result) == 2:
        exit_code = int(exec_result[0])
        stdout_bytes, stderr_bytes = exec_result[1]
    else:
        exit_code = int(getattr(exec_result, "exit_code", -1))
        output = getattr(exec_result, "output", (b"", b""))
        if isinstance(output, tuple):
            stdout_bytes, stderr_bytes = output
        else:
            stdout_bytes, stderr_bytes = output, b""

    stdout = _decode_bytes(stdout_bytes)
    stderr = _decode_bytes(stderr_bytes)
    if exit_code != 0:
        message = stderr.strip() or stdout.strip() or f"exit_code={exit_code}"
        raise HTTPException(status_code=500, detail=f"{error_prefix}: {message}")
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{error_prefix}: invalid JSON payload.",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail=f"{error_prefix}: expected a JSON object payload.",
        )
    return payload


def _list_runtime_skill_names(container: Any) -> set[str]:
    """List top-level editable skill directories currently present in sandbox."""
    script = """
import json
import pathlib

root = pathlib.Path("/workspace/skills")
names = []
if root.exists():
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and not candidate.is_symlink():
            names.append(candidate.name)
print(json.dumps({"names": names}))
""".strip()
    payload = _exec_json_in_container(
        container,
        cmd=["python3", "-c", script],
        error_prefix="Failed to inspect runtime skills",
    )
    raw_names = payload.get("names")
    if not isinstance(raw_names, list):
        raise HTTPException(
            status_code=500,
            detail="Failed to inspect runtime skills: invalid names payload.",
        )
    names: set[str] = set()
    for item in raw_names:
        if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", item):
            names.add(item)
    return names


def _remove_runtime_skills(container: Any, skill_names: set[str]) -> None:
    """Delete stale editable runtime skills from the sandbox-local draft root."""
    if not skill_names:
        return

    payload = json.dumps({"skill_names": sorted(skill_names)}, separators=(",", ":"))
    script = """
import json
import pathlib
import shutil
import sys

payload = json.loads(sys.argv[1])
root = pathlib.Path("/workspace/skills")
for name in payload["skill_names"]:
    if "/" in name or name in {"", ".", ".."}:
        raise SystemExit("Invalid skill name.")
    target = root / name
    if target.is_symlink():
        raise SystemExit("Runtime skill draft cannot be a symlink.")
    if target.exists():
        shutil.rmtree(target)
print("{}")
""".strip()
    _exec_json_in_container(
        container,
        cmd=["python3", "-c", script, payload],
        error_prefix="Failed to remove stale runtime skills",
    )


def _export_backend_skill_archive(*, skill_name: str, backend_location: str) -> bytes:
    """Archive one canonical skill directory by reading it inside backend."""
    script = """
import base64
import io
import json
import pathlib
import sys
import tarfile

skill_name = sys.argv[1]
root = pathlib.Path(sys.argv[2])
if not root.exists() or not root.is_dir():
    raise SystemExit("Canonical skill directory does not exist.")

archive = io.BytesIO()
with tarfile.open(fileobj=archive, mode="w") as tf:
    root_info = tarfile.TarInfo(name=skill_name)
    root_info.type = tarfile.DIRTYPE
    root_info.mode = 0o755
    tf.addfile(root_info)
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("Canonical skill directory cannot contain symlinks.")
        relative = path.relative_to(root).as_posix()
        arcname = f"{skill_name}/{relative}"
        if path.is_dir():
            info = tarfile.TarInfo(name=arcname)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tf.addfile(info)
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        info = tarfile.TarInfo(name=arcname)
        info.size = len(data)
        info.mode = 0o644
        tf.addfile(info, io.BytesIO(data))

print(
    json.dumps(
        {
            "archive_b64": base64.b64encode(archive.getvalue()).decode("ascii"),
        }
    )
)
""".strip()
    payload = _exec_json_in_container(
        _backend_container(),
        cmd=["python3", "-c", script, skill_name, backend_location],
        error_prefix=f"Failed to export canonical skill '{skill_name}'",
    )
    archive_b64 = payload.get("archive_b64")
    if not isinstance(archive_b64, str):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export canonical skill '{skill_name}': missing archive.",
        )
    try:
        return base64.b64decode(archive_b64.encode("ascii"), validate=True)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to export canonical skill '{skill_name}': invalid archive.",
        ) from exc


def _copy_skill_archive_into_container(
    *,
    container: Any,
    skill_name: str,
    archive_bytes: bytes,
) -> None:
    """Extract one canonical skill archive into ``/workspace/skills``."""
    try:
        copied = container.put_archive("/workspace/skills", archive_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to materialize skill '{skill_name}': {exc}",
        ) from exc
    if copied is False:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to materialize skill '{skill_name}': archive rejected.",
        )


def _materialize_runtime_skills(
    *,
    container: Any,
    skills: list[dict[str, str]],
) -> None:
    """Synchronize sandbox-local editable skill drafts for the current allowlist."""
    allowed_by_name = {skill["name"]: skill["canonical_location"] for skill in skills}
    existing_names = _list_runtime_skill_names(container)
    stale_names = existing_names - set(allowed_by_name)
    if stale_names:
        _remove_runtime_skills(container, stale_names)

    missing_names = sorted(set(allowed_by_name) - existing_names)
    for skill_name in missing_names:
        archive_bytes = _export_backend_skill_archive(
            skill_name=skill_name,
            backend_location=allowed_by_name[skill_name],
        )
        _copy_skill_archive_into_container(
            container=container,
            skill_name=skill_name,
            archive_bytes=archive_bytes,
        )


def _is_broken_exec_environment_error(message: str) -> bool:
    """Whether sandbox exec error indicates a broken container runtime state."""
    lowered = message.lower()
    return (
        "getcwd: operation not permitted" in lowered
        or "oci permission denied" in lowered
        or "connection reset by peer" in lowered
    )


def _ensure_sandbox(
    username: str,
    workspace_id: str,
    storage_backend: str,
    logical_path: str,
    mount_mode: str,
    source_workspace_id: str | None = None,
    skills: Sequence[SandboxSkillMount | dict[str, Any]] | None = None,
) -> Any:
    """Create or start a reusable sidecar sandbox container."""
    op_started = time.perf_counter()
    settings = get_settings()
    name = _sandbox_name(username, workspace_id)
    skills_volume_name = _ensure_skills_volume(username, workspace_id)
    workspace_driver = _workspace_runtime_driver(storage_backend)
    workspace_driver.ensure_runtime_ready()
    workspace_driver.ensure_workspace_ready(logical_path, mount_mode)
    normalized_skills = _normalize_skill_mounts(skills)

    existing = _find_container(name)
    workspace_bind = workspace_driver.build_workspace_bind(logical_path, mount_mode)
    if existing is not None:
        should_recreate, recreate_reason = _should_recreate_container(
            existing,
            expected_skills_volume_name=skills_volume_name,
            expected_workspace_mount_source=workspace_bind.source,
        )
    else:
        should_recreate, recreate_reason = (False, "no_container")

    if existing is not None and should_recreate:
        try:
            _remove_container_fast(existing, reason=f"recreate:{recreate_reason}")
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove legacy sandbox '{name}': {exc}",
            ) from exc
        logger.info(
            "sandbox.recreate_remove name=%s username=%s workspace_id=%s reason=%s",
            name,
            username,
            workspace_id,
            recreate_reason,
        )
        existing = None

    if existing is not None:
        start_started = time.perf_counter()
        try:
            existing.start()
        except Exception as exc:
            # Idempotent start: when container is already running we keep using it.
            message = str(exc).lower()
            if 'workdir "/workspace" does not exist' in message:
                # Backward compatibility: old containers were created with an
                # invalid workdir and can never be started again.
                try:
                    _remove_container_fast(existing, reason="recreate:broken_workdir")
                except Exception as remove_exc:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            f"Failed to recover broken sandbox '{name}'. "
                            f"start_error={exc}; remove_error={remove_exc}"
                        ),
                    ) from remove_exc
                # Reuse the original backend payload so canonical skill locations stay
                # backend-visible (``/app/server/...``) for runtime materialization.
                return _ensure_sandbox(
                    username,
                    workspace_id,
                    storage_backend,
                    logical_path,
                    mount_mode,
                    source_workspace_id,
                    skills,
                )
            if "already running" not in message:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to start sandbox '{name}': {exc}",
                ) from exc
        _materialize_runtime_skills(container=existing, skills=normalized_skills)
        _touch_container(name)
        logger.info(
            "sandbox.ensure name=%s username=%s workspace_id=%s mode=reuse start_ms=%d total_ms=%d",
            name,
            username,
            workspace_id,
            int((time.perf_counter() - start_started) * 1000),
            int((time.perf_counter() - op_started) * 1000),
        )
        return existing

    volumes = {
        workspace_bind.source: {
            "bind": workspace_bind.destination,
            "mode": workspace_bind.mode,
        }
    }
    volumes[skills_volume_name] = {"bind": "/workspace/skills", "mode": "rw"}
    setup_cmd = "sleep infinity"
    base_image_id = _resolve_image_id(settings.SANDBOX_BASE_IMAGE)
    labels = {
        "pivot.sandbox.base_image_ref": settings.SANDBOX_BASE_IMAGE,
        "pivot.sandbox.network_mode": settings.SANDBOX_NETWORK_MODE,
        "pivot.sandbox.skills_volume_name": skills_volume_name,
        "pivot.sandbox.workspace_storage_backend": storage_backend,
        "pivot.sandbox.workspace_logical_path": logical_path,
        "pivot.sandbox.workspace_mount_mode": mount_mode,
        "pivot.sandbox.workspace_id": workspace_id,
    }
    if source_workspace_id is not None:
        labels["pivot.sandbox.source_workspace_id"] = source_workspace_id
    if base_image_id is not None:
        labels["pivot.sandbox.base_image_id"] = base_image_id
    create_started = time.perf_counter()
    try:
        container = get_client().containers.create(
            image=settings.SANDBOX_BASE_IMAGE,
            name=name,
            command=["sh", "-lc", setup_cmd],
            detach=True,
            privileged=False,
            tty=False,
            stdin_open=False,
            working_dir="/workspace",
            network_mode=settings.SANDBOX_NETWORK_MODE,
            # Mount only the current agent workspace; never mount full project tree.
            volumes=volumes,
            environment={"PYTHONUNBUFFERED": "1"},
            labels=labels,
        )
        create_ms = int((time.perf_counter() - create_started) * 1000)
        start_started = time.perf_counter()
        container.start()
        start_ms = int((time.perf_counter() - start_started) * 1000)
        _materialize_runtime_skills(container=container, skills=normalized_skills)
        logger.info(
            "sandbox.ensure name=%s username=%s workspace_id=%s mode=create create_ms=%d start_ms=%d total_ms=%d",
            name,
            username,
            workspace_id,
            create_ms,
            start_ms,
            int((time.perf_counter() - op_started) * 1000),
        )
        _touch_container(name)
        return container
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create/start sandbox '{name}': {exc}",
        ) from exc

def _cleanup_pool_once() -> None:
    """Run one cleanup pass for idle and over-capacity sandbox containers."""
    settings = get_settings()
    now = time.time()

    with _pool_lock:
        snapshot = sorted(_last_used_by_name.items(), key=lambda item: item[1])

    # Proactively evict warm sandboxes that no longer match current runtime config.
    for name, _last_used in snapshot:
        container = _find_container(name)
        if container is None:
            with _pool_lock:
                _last_used_by_name.pop(name, None)
            continue
        workspace_contract = _container_workspace_contract(container)
        skills_volume_name = _container_skills_volume_name(container)
        if workspace_contract is None or skills_volume_name is None:
            continue
        storage_backend, logical_path, mount_mode = workspace_contract
        try:
            workspace_driver = _workspace_runtime_driver(storage_backend)
            workspace_bind = workspace_driver.build_workspace_bind(
                logical_path,
                mount_mode,
            )
            should_recreate, recreate_reason = _should_recreate_container(
                container,
                expected_skills_volume_name=skills_volume_name,
                expected_workspace_mount_source=workspace_bind.source,
            )
        except HTTPException as exc:
            logger.warning(
                "sandbox.pool compatibility check failed name=%s err=%s",
                name,
                exc.detail,
            )
            continue
        if not should_recreate:
            continue
        try:
            _remove_container_fast(
                container,
                reason=f"pool_compatibility:{recreate_reason}",
                remove_skills_volume=True,
            )
        except Exception as exc:
            logger.warning(
                "sandbox.pool compatibility remove failed name=%s err=%s",
                name,
                exc,
            )
            continue
        with _pool_lock:
            _last_used_by_name.pop(name, None)
        logger.info(
            "sandbox.pool cleanup=compatibility name=%s reason=%s",
            name,
            recreate_reason,
        )

    # Idle timeout cleanup
    for name, last_used in snapshot:
        idle_seconds = now - last_used
        if idle_seconds < settings.SANDBOX_POOL_IDLE_TTL_SECONDS:
            continue
        container = _find_container(name)
        if container is None:
            with _pool_lock:
                _last_used_by_name.pop(name, None)
            continue
        try:
            _remove_container_fast(
                container,
                reason="pool_idle_ttl",
                remove_skills_volume=True,
            )
        except Exception as exc:
            logger.warning(
                "sandbox.pool cleanup idle remove failed name=%s err=%s", name, exc
            )
            continue
        with _pool_lock:
            _last_used_by_name.pop(name, None)
        logger.info(
            "sandbox.pool cleanup=idle name=%s idle_s=%d",
            name,
            int(idle_seconds),
        )

    # Max-size LRU cleanup (oldest first)
    with _pool_lock:
        live_items = sorted(_last_used_by_name.items(), key=lambda item: item[1])
    overflow = len(live_items) - settings.SANDBOX_POOL_MAX_SIZE
    if overflow <= 0:
        return

    for name, _last_used in live_items[:overflow]:
        container = _find_container(name)
        if container is None:
            with _pool_lock:
                _last_used_by_name.pop(name, None)
            continue
        try:
            _remove_container_fast(
                container,
                reason="pool_lru_overflow",
                remove_skills_volume=True,
            )
        except Exception as exc:
            logger.warning(
                "sandbox.pool cleanup lru remove failed name=%s err=%s", name, exc
            )
            continue
        with _pool_lock:
            _last_used_by_name.pop(name, None)
        logger.info("sandbox.pool cleanup=lru name=%s", name)


def _cleanup_loop() -> None:
    """Background loop for periodic pool cleanup."""
    interval = max(1, get_settings().SANDBOX_POOL_SCAN_INTERVAL_SECONDS)
    while True:
        try:
            _cleanup_pool_once()
        except Exception as exc:
            logger.warning("sandbox.pool cleanup pass failed: %s", exc)
        time.sleep(interval)


@app.on_event("startup")
def startup_pool_cleanup() -> None:
    """Start background pool cleanup thread once per process."""
    global _cleanup_started
    if _cleanup_started:
        return
    thread = threading.Thread(
        target=_cleanup_loop, daemon=True, name="sandbox-pool-cleaner"
    )
    thread.start()
    _cleanup_started = True
    logger.info(
        "sandbox.pool started scan_interval_s=%d idle_ttl_s=%d max_size=%d",
        get_settings().SANDBOX_POOL_SCAN_INTERVAL_SECONDS,
        get_settings().SANDBOX_POOL_IDLE_TTL_SECONDS,
        get_settings().SANDBOX_POOL_MAX_SIZE,
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health check endpoint for compose readiness checks."""
    get_client().ping()
    return {"status": "ok"}


def _seaweedfs_runtime_status() -> SeaweedfsRuntimeStatusResponse:
    """Return current manager-side SeaweedFS runtime attachment state."""
    settings = get_settings()
    driver = SeaweedfsWorkspaceDriver()
    attach_strategy = driver._attach_strategy(settings)
    mount_root = settings.SANDBOX_SEAWEEDFS_MOUNT_ROOT
    native_mount_active = False
    mount_root_host_path: str | None = None

    if attach_strategy == "shared_mount_root":
        native_mount_active = driver._shared_mount_root_uses_native_mount(settings)
        mount_root_host_path = _resolve_host_path_from_self_container_path(mount_root)

    filer_reachable = True
    try:
        _assert_service_reachable(
            settings.SANDBOX_SEAWEEDFS_FILER_URL,
            label="SeaweedFS filer",
        )
    except HTTPException:
        filer_reachable = False

    return SeaweedfsRuntimeStatusResponse(
        attach_strategy=attach_strategy,
        native_mount_required=driver._shared_mount_root_requires_native_mount(settings),
        filer_url=settings.SANDBOX_SEAWEEDFS_FILER_URL,
        filer_reachable=filer_reachable,
        mount_root=mount_root,
        mount_root_host_path=mount_root_host_path,
        native_mount_active=native_mount_active,
        fallback_bridge_active=attach_strategy == "compose_compat"
        or not native_mount_active,
    )


@app.get(
    "/runtime/seaweedfs/status",
    dependencies=[Depends(_require_token)],
    response_model=SeaweedfsRuntimeStatusResponse,
)
def seaweedfs_runtime_status() -> SeaweedfsRuntimeStatusResponse:
    """Expose current SeaweedFS runtime attach state for local debugging."""
    return _seaweedfs_runtime_status()


@app.post("/sandboxes/create", dependencies=[Depends(_require_token)])
def create_sandbox(payload: SandboxRequest) -> dict[str, str]:
    """Create sandbox container for one workspace (idempotent)."""
    container = _ensure_sandbox(
        payload.username,
        payload.workspace_id,
        payload.storage_backend,
        payload.logical_path,
        payload.mount_mode,
        payload.source_workspace_id,
        payload.skills,
    )
    return {
        "container_name": _sandbox_name(payload.username, payload.workspace_id),
        "container_id": container.id,
    }


@app.post("/sandboxes/destroy", dependencies=[Depends(_require_token)])
def destroy_sandbox(payload: SandboxRequest) -> dict[str, str]:
    """Stop and remove sandbox container for one workspace."""
    started = time.perf_counter()
    name = _sandbox_name(payload.username, payload.workspace_id)
    container = _find_container(name)
    if container is None:
        with _pool_lock:
            _last_used_by_name.pop(name, None)
        logger.info(
            "sandbox.destroy name=%s username=%s workspace_id=%s status=not_found total_ms=%d",
            name,
            payload.username,
            payload.workspace_id,
            int((time.perf_counter() - started) * 1000),
        )
        return {"status": "not_found", "container_name": name}
    workspace_driver = _workspace_runtime_driver(payload.storage_backend)
    try:
        workspace_driver.sync_workspace(payload.logical_path, payload.mount_mode)
        _remove_container_fast(
            container,
            reason="destroy_api",
            remove_skills_volume=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to destroy sandbox {name}: {exc}",
        ) from exc
    with _pool_lock:
        _last_used_by_name.pop(name, None)
    logger.info(
        "sandbox.destroy name=%s username=%s workspace_id=%s status=destroyed total_ms=%d",
        name,
        payload.username,
        payload.workspace_id,
        int((time.perf_counter() - started) * 1000),
    )
    return {"status": "destroyed", "container_name": name}


@app.post("/sandboxes/exec", dependencies=[Depends(_require_token)])
def exec_in_sandbox(payload: SandboxExecRequest) -> SandboxExecResponse:
    """Exec one command in sandbox and return stdout/stderr + exit code."""
    started = time.perf_counter()
    ensure_started = time.perf_counter()
    container = _ensure_sandbox(
        payload.username,
        payload.workspace_id,
        payload.storage_backend,
        payload.logical_path,
        payload.mount_mode,
        payload.source_workspace_id,
        payload.skills,
    )
    ensure_ms = int((time.perf_counter() - ensure_started) * 1000)

    def _exec_once(target_container: Any) -> Any:
        return target_container.exec_run(
            payload.cmd,
            workdir="/workspace",
            demux=True,
            tty=False,
            stream=False,
            socket=False,
        )

    exec_started = time.perf_counter()
    try:
        exec_result = _exec_once(container)
    except Exception as exc:
        message = str(exc)
        if _is_broken_exec_environment_error(message):
            logger.warning(
                "sandbox.exec detected broken runtime state; recreating container "
                "username=%s workspace_id=%s err=%s",
                payload.username,
                payload.workspace_id,
                message,
            )
            with suppress(Exception):
                _remove_container_fast(container, reason="recreate:exec_runtime_error")
            container = _ensure_sandbox(
                payload.username,
                payload.workspace_id,
                payload.storage_backend,
                payload.logical_path,
                payload.mount_mode,
                payload.source_workspace_id,
                payload.skills,
            )
            try:
                exec_result = _exec_once(container)
            except Exception as retry_exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"Sandbox exec failed after recreate: {retry_exc}",
                ) from retry_exc
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Sandbox exec failed: {exc}",
            ) from exc
    exec_ms = int((time.perf_counter() - exec_started) * 1000)

    # podman-py may return either:
    # 1) an object with ``exit_code``/``output`` attributes, or
    # 2) a tuple ``(exit_code, output)``.
    if isinstance(exec_result, tuple) and len(exec_result) == 2:
        exit_code = int(exec_result[0])
        output = exec_result[1]
    else:
        exit_code = int(getattr(exec_result, "exit_code", -1))
        output = getattr(exec_result, "output", (b"", b""))

    stdout: str
    stderr: str
    if isinstance(output, tuple) and len(output) == 2:
        stdout = _decode_bytes(output[0])
        stderr = _decode_bytes(output[1])
    else:
        stdout = _decode_bytes(output)
        stderr = ""

    workspace_driver = _workspace_runtime_driver(payload.storage_backend)
    workspace_driver.sync_workspace(payload.logical_path, payload.mount_mode)

    total_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "sandbox.exec name=%s username=%s workspace_id=%s exit_code=%d ensure_ms=%d exec_ms=%d total_ms=%d",
        _sandbox_name(payload.username, payload.workspace_id),
        payload.username,
        payload.workspace_id,
        exit_code,
        ensure_ms,
        exec_ms,
        total_ms,
    )

    return SandboxExecResponse(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        container_name=_sandbox_name(payload.username, payload.workspace_id),
    )
