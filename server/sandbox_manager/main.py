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
from asyncio import FIRST_COMPLETED, create_task, wait
from contextlib import suppress
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
)
from podman import PodmanClient  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from websockets import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

if TYPE_CHECKING:
    from collections.abc import Sequence

    from websockets.typing import Subprotocol

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
    SANDBOX_WORKSPACE_HOST_ROOT: str | None = None
    SANDBOX_BACKEND_WORKSPACE_ROOT: str = "/app/server/workspace"
    SANDBOX_EXTERNAL_POSIX_ROOT: str | None = "/app/server/external-posix"
    SANDBOX_POOL_SCAN_INTERVAL_SECONDS: int = 30
    SANDBOX_POOL_IDLE_TTL_SECONDS: int = 900
    SANDBOX_POOL_MAX_SIZE: int = 8
    SANDBOX_MEMORY_LIMIT: str = "1g"
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_PIDS_LIMIT: int = 256


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


def _to_nano_cpus(cpu_limit: float) -> int | None:
    """Convert one fractional CPU limit into Podman-compatible nano CPUs.

    Args:
        cpu_limit: Requested CPU quota where ``1.0`` means one full core.

    Returns:
        The Podman-compatible ``nano_cpus`` integer, or None when the limit is
        not positive and should be omitted.
    """
    if cpu_limit <= 0:
        return None
    return max(1, int(cpu_limit * 1_000_000_000))


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
    containers = get_client().containers.list(all=True, filters={"name": hostname})
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


def _backend_workspace_root() -> str:
    """Return the workspace root path visible inside the backend container."""
    configured_root = get_settings().SANDBOX_BACKEND_WORKSPACE_ROOT.strip()
    if configured_root == "":
        return "/app/server/workspace"
    return configured_root.rstrip("/") or "/"


def _allowed_backend_workspace_roots() -> list[str]:
    """Return all backend-visible roots that may contain sandbox workspaces."""
    settings = get_settings()
    roots = [_backend_workspace_root()]
    external_root = (settings.SANDBOX_EXTERNAL_POSIX_ROOT or "").strip()
    if external_root:
        normalized_root = external_root.rstrip("/") or "/"
        if normalized_root not in roots:
            roots.append(normalized_root)
    return roots


def _ensure_workspace_dir(path_in_backend: str) -> None:
    """Create the backend-visible directory used for the primary workspace mount."""
    allowed_roots = _allowed_backend_workspace_roots()
    allowed_prefixes = [f"{root}/" for root in allowed_roots]
    if not any(path_in_backend.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(
            status_code=400,
            detail=(
                "workspace_backend_path must stay under one of: "
                f"{', '.join(allowed_roots)}."
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


def _resolve_host_path_from_backend_path(path_in_backend: str) -> str | None:
    """Resolve host-side path for a backend-container path.

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


def _format_sandbox_start_failure_detail(
    *,
    name: str,
    workspace_backend_path: str,
    exc: Exception,
) -> str:
    """Return one actionable sandbox start failure detail string."""
    message = str(exc)
    lowered_message = message.lower()

    if "statfs " in lowered_message and "no such file or directory" in lowered_message:
        return (
            f"Failed to create/start sandbox '{name}': {exc}. "
            "The resolved host workspace path is missing. This usually means "
            "the external POSIX bridge was remounted after backend or "
            "sandbox-manager started, so the runtime and Podman daemon no "
            "longer see the same workspace namespace. Re-run "
            "`scripts/fs-up.sh` or `scripts/fs-down.sh` and let them refresh "
            "backend + sandbox-manager before retrying. "
            f"workspace_backend_path={workspace_backend_path!r}"
        )

    return f"Failed to create/start sandbox '{name}': {exc}"


def _normalize_skill_mounts(
    raw_skills: Sequence[SandboxSkillMount | dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Sanitize skill mount metadata coming from backend."""
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
        raw_location = item.get("location")
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
        host_path = _resolve_host_path_from_backend_path(location)
        if host_path is None:
            logger.warning(
                "sandbox.skills host path unavailable skill=%s location=%s",
                skill_name,
                location,
            )
            continue

        seen_names.add(skill_name)
        normalized.append({"name": skill_name, "location": host_path})
    return normalized


def _build_skill_mounts(
    skill_mounts: list[dict[str, str]],
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Build bind mounts and expected source map for allowed skills."""
    volumes: dict[str, dict[str, str]] = {}
    expected_sources: dict[str, str] = {}
    for skill in skill_mounts:
        skill_name = skill["name"]
        source_dir = skill["location"]
        volumes[source_dir] = {
            "bind": f"/workspace/skills/{skill_name}",
            "mode": "ro",
        }
        expected_sources[skill_name] = source_dir
    return volumes, expected_sources


def _mounted_skill_sources(container: Any) -> dict[str, str]:
    """Read currently mounted skill source directories from a sandbox container."""
    try:
        mounts = _get_container_mounts(container)
    except HTTPException:
        return {}

    skill_sources: dict[str, str] = {}
    for mount in mounts:
        destination = _mount_destination(mount)
        source = _mount_source(mount)
        if not isinstance(destination, str):
            continue
        prefix = "/workspace/skills/"
        if not destination.startswith(prefix):
            continue
        suffix = destination[len(prefix) :]
        if "/" in suffix or not suffix or not isinstance(source, str):
            continue
        skill_sources[suffix] = source
    return skill_sources


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


def _container_ipv4_address(container: Any) -> str | None:
    """Return one IPv4 address for an existing sandbox container when available."""
    attrs = getattr(container, "attrs", None)
    if isinstance(attrs, dict):
        network_settings = attrs.get("NetworkSettings")
        if isinstance(network_settings, dict):
            direct_ip = network_settings.get("IPAddress")
            if isinstance(direct_ip, str) and direct_ip:
                return direct_ip
            networks = network_settings.get("Networks")
            if isinstance(networks, dict):
                for network in networks.values():
                    if not isinstance(network, dict):
                        continue
                    ip_address = network.get("IPAddress")
                    if isinstance(ip_address, str) and ip_address:
                        return ip_address

    inspect_func = getattr(container, "inspect", None)
    if callable(inspect_func):
        inspected = inspect_func()
        if isinstance(inspected, dict):
            network_settings = inspected.get("NetworkSettings")
            if isinstance(network_settings, dict):
                direct_ip = network_settings.get("IPAddress")
                if isinstance(direct_ip, str) and direct_ip:
                    return direct_ip
                networks = network_settings.get("Networks")
                if isinstance(networks, dict):
                    for network in networks.values():
                        if not isinstance(network, dict):
                            continue
                        ip_address = network.get("IPAddress")
                        if isinstance(ip_address, str) and ip_address:
                            return ip_address

    return None


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
    expected_skill_sources: dict[str, str],
    *,
    expected_skills_volume_name: str,
) -> tuple[bool, str]:
    """Decide whether an existing sandbox container must be recreated.

    Recreate when configuration is unsafe/legacy, skill mounts drift, or the
    base sandbox image tag now points at a newer local image:
    - working dir is not ``/workspace``
    - full project mounts (e.g. ``/app/server`` or ``/app/web``) are present
    - ``/workspace`` mount is missing
    - mounted ``/workspace/skills/*`` sources differ from expected
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

    destinations = {
        _mount_destination(m) for m in mounts if isinstance(_mount_destination(m), str)
    }

    if workdir != "/workspace":
        return True, "workdir_mismatch"
    if "/workspace" not in destinations:
        return True, "missing_workspace_mount"
    if "/workspace/skills" not in destinations:
        return True, "missing_skills_volume_mount"
    if "/app/server" in destinations or "/app/web" in destinations:
        return True, "unsafe_project_mount"
    container_skills_volume_name = _container_skills_volume_name(container)
    if container_skills_volume_name != expected_skills_volume_name:
        return True, "skills_volume_mismatch"
    mounted_skills = _mounted_skill_sources(container)
    if mounted_skills != expected_skill_sources:
        return True, "skill_mount_mismatch"
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
    workspace_backend_path: str,
    skills: Sequence[SandboxSkillMount | dict[str, Any]] | None = None,
    *,
    require_existing: bool = False,
    allow_recreate: bool = True,
) -> Any:
    """Create or start a reusable sidecar sandbox container."""
    op_started = time.perf_counter()
    settings = get_settings()
    name = _sandbox_name(username, workspace_id)
    skills_volume_name = _ensure_skills_volume(username, workspace_id)
    _ensure_workspace_dir(workspace_backend_path)
    normalized_skills = _normalize_skill_mounts(skills)
    skill_volumes, expected_skill_sources = _build_skill_mounts(normalized_skills)

    existing = _find_container(name)
    if existing is not None and require_existing and not allow_recreate:
        should_recreate, recreate_reason = (False, "existing_container_reuse")
    elif existing is not None:
        should_recreate, recreate_reason = _should_recreate_container(
            existing,
            expected_skill_sources,
            expected_skills_volume_name=skills_volume_name,
        )
    else:
        should_recreate, recreate_reason = (False, "no_container")

    if existing is None and require_existing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Sandbox preview runtime is unavailable because the original "
                "sandbox container no longer exists. Restart the preview from the agent."
            ),
        )

    if existing is not None and should_recreate:
        if not allow_recreate:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Sandbox preview runtime configuration no longer matches the "
                    f"existing sandbox ({recreate_reason}). Restart the preview "
                    "from the agent instead of recreating the container automatically."
                ),
            )
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
                if not allow_recreate:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Sandbox preview runtime cannot be reused because the "
                            "existing sandbox has an invalid workdir. Restart the "
                            "preview from the agent."
                        ),
                    ) from exc
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
                # Reuse the original backend payload so skill locations are still
                # backend paths (``/app/server/...``). Passing normalized host paths
                # back through ``_normalize_skill_mounts`` would strip every skill.
                return _ensure_sandbox(
                    username,
                    workspace_id,
                    workspace_backend_path,
                    skills,
                    require_existing=require_existing,
                    allow_recreate=allow_recreate,
                )
            if "already running" not in message:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to start sandbox '{name}': {exc}",
                ) from exc
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

    workspace_host_dir = _resolve_host_path_from_backend_path(workspace_backend_path)
    if workspace_host_dir is None:
        raise HTTPException(
            status_code=500,
            detail=(
                "Could not resolve host path for workspace_backend_path "
                f"{workspace_backend_path!r}."
            ),
        )
    volumes = {workspace_host_dir: {"bind": "/workspace", "mode": "rw"}}
    volumes[skills_volume_name] = {"bind": "/workspace/skills", "mode": "rw"}
    volumes.update(skill_volumes)
    setup_cmd = "sleep infinity"
    base_image_id = _resolve_image_id(settings.SANDBOX_BASE_IMAGE)
    nano_cpus = _to_nano_cpus(settings.SANDBOX_CPU_LIMIT)
    labels = {
        "pivot.sandbox.base_image_ref": settings.SANDBOX_BASE_IMAGE,
        "pivot.sandbox.network_mode": settings.SANDBOX_NETWORK_MODE,
        "pivot.sandbox.skills_volume_name": skills_volume_name,
        "pivot.sandbox.workspace_backend_path": workspace_backend_path,
        "pivot.sandbox.workspace_id": workspace_id,
    }
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
            mem_limit=settings.SANDBOX_MEMORY_LIMIT,
            nano_cpus=nano_cpus,
            pids_limit=settings.SANDBOX_PIDS_LIMIT,
            # Mount only the current agent workspace; never mount full project tree.
            volumes=volumes,
            environment={"PYTHONUNBUFFERED": "1"},
            labels=labels,
        )
        create_ms = int((time.perf_counter() - create_started) * 1000)
        start_started = time.perf_counter()
        container.start()
        start_ms = int((time.perf_counter() - start_started) * 1000)
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
            detail=_format_sandbox_start_failure_detail(
                name=name,
                workspace_backend_path=workspace_backend_path,
                exc=exc,
            ),
        ) from exc


class SandboxSkillMount(BaseModel):
    """One skill mount entry sent by backend."""

    name: str = Field(min_length=1)
    location: str = Field(min_length=1)


class SandboxRequest(BaseModel):
    """Request payload for create/destroy operations."""

    username: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    workspace_backend_path: str = Field(min_length=1)
    skills: list[SandboxSkillMount] = Field(default_factory=list)


class SandboxExecRequest(SandboxRequest):
    """Request payload for command execution."""

    cmd: list[str] = Field(min_length=1)


class SandboxExecResponse(BaseModel):
    """Response payload for command execution."""

    exit_code: int
    stdout: str
    stderr: str
    container_name: str


class SandboxHttpProxyRequest(SandboxRequest):
    """Request payload for proxying one HTTP request into a sandbox."""

    port: int = Field(ge=1, le=65535)
    path: str = Field(default="/", min_length=1)
    method: str = Field(default="GET", min_length=1)
    query_string: str = Field(default="")
    headers: dict[str, str] = Field(default_factory=dict)
    body_base64: str | None = None
    require_existing: bool = False
    allow_recreate: bool = True


class SandboxWebSocketProxyInit(SandboxRequest):
    """Initialization payload for one sandbox preview websocket tunnel."""

    port: int
    path: str = "/"
    query_string: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    subprotocol: str | None = None
    require_existing: bool = False
    allow_recreate: bool = True


def _cleanup_pool_once() -> None:
    """Run one cleanup pass for idle and over-capacity sandbox containers."""
    settings = get_settings()
    now = time.time()

    with _pool_lock:
        snapshot = sorted(_last_used_by_name.items(), key=lambda item: item[1])

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


def _extract_upstream_proxy_headers(headers: dict[str, Any]) -> dict[str, str]:
    """Forward only safe upstream headers to the backend proxy response."""
    allowed_headers = {
        "cache-control",
        "content-language",
        "content-type",
        "etag",
        "last-modified",
        "location",
        "vary",
    }
    response_headers: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in allowed_headers and isinstance(value, str):
            response_headers[key] = value
    return response_headers


def _normalize_preview_path(path: str) -> str:
    """Return one normalized HTTP path for sandbox preview requests."""
    normalized = path.strip() or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _decode_proxy_body(body_base64: str | None) -> bytes | None:
    """Decode an optional proxy body payload."""
    if body_base64 is None or body_base64 == "":
        return None
    try:
        return base64.b64decode(body_base64)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid proxy request body encoding: {exc}",
        ) from exc


def _build_preview_target_url(*, container: Any, port: int, path: str, query_string: str) -> str:
    """Build one concrete upstream preview URL for a sandbox container."""
    container_ip = _container_ipv4_address(container)
    if not container_ip:
        raise HTTPException(
            status_code=500,
            detail="Sandbox container does not have a reachable IPv4 address.",
        )
    upstream_url = f"http://{container_ip}:{port}{_normalize_preview_path(path)}"
    if query_string:
        return f"{upstream_url}?{query_string}"
    return upstream_url


def _build_preview_target_ws_url(
    *,
    container: Any,
    port: int,
    path: str,
    query_string: str,
) -> str:
    """Build one concrete upstream preview websocket URL for a sandbox."""
    container_ip = _container_ipv4_address(container)
    if not container_ip:
        raise HTTPException(
            status_code=500,
            detail="Sandbox container does not have a reachable IPv4 address.",
        )
    upstream_url = f"ws://{container_ip}:{port}{_normalize_preview_path(path)}"
    if query_string:
        return f"{upstream_url}?{query_string}"
    return upstream_url


def _filter_proxy_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop hop-by-hop headers before forwarding one preview request."""
    blocked_headers = {
        "authorization",
        "connection",
        "content-length",
        "host",
        "transfer-encoding",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in blocked_headers
    }


def _build_preview_unreachable_detail(*, port: int, reason: object) -> str:
    """Explain how preview targets must listen inside one sandbox container."""
    return (
        "Sandbox preview target is unreachable: "
        f"{reason}. Ensure the preview server is running and listening on "
        f"0.0.0.0:{port} inside the sandbox, not only on localhost/127.0.0.1."
    )


async def _forward_browser_messages(*, websocket: WebSocket, upstream: Any) -> None:
    """Forward backend websocket frames into the upstream preview socket."""
    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break
            if text := message.get("text"):
                await upstream.send(text)
            elif (data := message.get("bytes")) is not None:
                await upstream.send(data)
    except Exception:
        return


async def _forward_upstream_ws_messages(*, websocket: WebSocket, upstream: Any) -> None:
    """Forward upstream preview websocket frames back to the backend."""
    try:
        async for message in upstream:
            if isinstance(message, bytes):
                await websocket.send_bytes(message)
            else:
                await websocket.send_text(message)
    except Exception:
        return


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health check endpoint for compose readiness checks."""
    get_client().ping()
    return {"status": "ok"}


@app.post("/sandboxes/create", dependencies=[Depends(_require_token)])
def create_sandbox(payload: SandboxRequest) -> dict[str, str]:
    """Create sandbox container for one workspace (idempotent)."""
    container = _ensure_sandbox(
        payload.username,
        payload.workspace_id,
        payload.workspace_backend_path,
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
    try:
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
        payload.workspace_backend_path,
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
                payload.workspace_backend_path,
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


@app.post("/sandboxes/http-proxy", dependencies=[Depends(_require_token)])
def proxy_http_in_sandbox(payload: SandboxHttpProxyRequest) -> Response:
    """Proxy one HTTP request through the sandbox container network."""
    try:
        container = _ensure_sandbox(
            payload.username,
            payload.workspace_id,
            payload.workspace_backend_path,
            payload.skills,
            require_existing=payload.require_existing,
            allow_recreate=payload.allow_recreate,
        )
    except HTTPException as err:
        raise err
    method = payload.method.strip().upper() or "GET"
    if method not in {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}:
        raise HTTPException(status_code=400, detail="Unsupported preview HTTP method.")

    target_url = _build_preview_target_url(
        container=container,
        port=payload.port,
        path=payload.path,
        query_string=payload.query_string,
    )
    proxy_body = _decode_proxy_body(payload.body_base64)
    request_headers = _filter_proxy_request_headers(payload.headers)
    upstream_request = UrlRequest(
        target_url,
        data=proxy_body,
        headers=request_headers,
        method=method,
    )

    try:
        with urlopen(upstream_request) as upstream_response:
            upstream_body = upstream_response.read()
            response_headers = _extract_upstream_proxy_headers(
                dict(upstream_response.headers.items())
            )
            return Response(
                content=upstream_body,
                status_code=upstream_response.getcode(),
                headers=response_headers,
                media_type=response_headers.get("Content-Type"),
            )
    except HTTPError as err:
        response_headers = _extract_upstream_proxy_headers(dict(err.headers.items()))
        return Response(
            content=err.read(),
            status_code=err.code,
            headers=response_headers,
            media_type=response_headers.get("Content-Type"),
        )
    except URLError as err:
        raise HTTPException(
            status_code=502,
            detail=_build_preview_unreachable_detail(
                port=payload.port,
                reason=err.reason,
            ),
        ) from err


@app.websocket("/sandboxes/ws-proxy")
async def proxy_websocket_in_sandbox(websocket: WebSocket) -> None:
    """Tunnel one preview websocket through sandbox-manager into a sandbox."""
    if websocket.headers.get("x-sandbox-token") != get_settings().SANDBOX_MANAGER_TOKEN:
        await websocket.close(code=1008, reason="Invalid sandbox token.")
        return

    await websocket.accept()

    try:
        payload = SandboxWebSocketProxyInit.model_validate_json(
            await websocket.receive_text()
        )
    except Exception as err:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "detail": f"Invalid websocket proxy init payload: {err}",
                }
            )
        )
        await websocket.close(code=1003, reason="Invalid websocket proxy init.")
        return

    try:
        container = _ensure_sandbox(
            payload.username,
            payload.workspace_id,
            payload.workspace_backend_path,
            payload.skills,
            require_existing=payload.require_existing,
            allow_recreate=payload.allow_recreate,
        )
    except HTTPException as err:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "detail": str(err.detail),
                }
            )
        )
        await websocket.close(code=1011, reason=str(err.detail)[:120])
        return
    target_url = _build_preview_target_ws_url(
        container=container,
        port=payload.port,
        path=payload.path,
        query_string=payload.query_string,
    )
    request_headers = _filter_proxy_request_headers(payload.headers)

    try:
        if payload.subprotocol:
            upstream_connection = websocket_connect(
                target_url,
                additional_headers=request_headers,
                subprotocols=[cast("Subprotocol", payload.subprotocol)],
            )
        elif request_headers:
            upstream_connection = websocket_connect(
                target_url,
                additional_headers=request_headers,
            )
        else:
            upstream_connection = websocket_connect(target_url)

        async with upstream_connection as upstream:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "ready",
                        "accepted_subprotocol": upstream.subprotocol,
                    }
                )
            )
            client_to_upstream = create_task(
                _forward_browser_messages(websocket=websocket, upstream=upstream)
            )
            upstream_to_client = create_task(
                _forward_upstream_ws_messages(websocket=websocket, upstream=upstream)
            )
            done, pending = await wait(
                {client_to_upstream, upstream_to_client},
                return_when=FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except ConnectionClosed:
        await websocket.close()
    except OSError as err:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "detail": _build_preview_unreachable_detail(
                        port=payload.port,
                        reason=err,
                    ),
                }
            )
        )
        await websocket.close(
            code=1011,
            reason="Sandbox preview websocket target is unreachable.",
        )
