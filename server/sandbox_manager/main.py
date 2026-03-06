"""Sandbox manager service.

This service is the only component that talks to Podman. Backend calls this
service over HTTP to create, execute in, and destroy sandbox containers.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import suppress
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from podman import PodmanClient  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, BaseSettings, Field

app = FastAPI(title="Pivot Sandbox Manager")
logger = logging.getLogger("uvicorn.error")
_pool_lock = threading.RLock()
_last_used_by_name: dict[str, float] = {}
_cleanup_started = False


class ManagerSettings(BaseSettings):
    """Runtime settings for sandbox-manager."""

    SANDBOX_MANAGER_TOKEN: str = "dev-sandbox-token"
    SANDBOX_PODMAN_BASE_URL: str = "unix:///run/podman/podman.sock"
    SANDBOX_BASE_IMAGE: str = "docker.io/library/python:3.10-slim"
    SANDBOX_BACKEND_CONTAINER_NAME: str = "pivot-backend"
    SANDBOX_CONTAINER_PREFIX: str = "pivot-sandbox"
    SANDBOX_DEFAULT_TIMEOUT_SECONDS: int = 30
    SANDBOX_WORKSPACE_HOST_ROOT: str | None = None
    SANDBOX_POOL_SCAN_INTERVAL_SECONDS: int = 30
    SANDBOX_POOL_IDLE_TTL_SECONDS: int = 300
    SANDBOX_POOL_MAX_SIZE: int = 100


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


def _sandbox_name(username: str, agent_id: int) -> str:
    """Build deterministic sandbox container name."""
    prefix = get_settings().SANDBOX_CONTAINER_PREFIX
    user = username.strip() or "default"
    return f"{prefix}-{user}-{agent_id}"


def _workspace_target(username: str, agent_id: int) -> str:
    """Return backend-mounted target path for one agent workspace."""
    return f"/app/server/workspace/{username}/agents/{agent_id}"


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


def _resolve_workspace_host_root() -> str:
    """Resolve host-side root path for ``server/workspace`` from backend mounts."""
    mount_sets: list[list[dict[str, Any]]] = []
    with suppress(HTTPException):
        mount_sets.append(_get_container_mounts(_backend_container()))

    self_container = _self_container()
    if self_container is not None:
        with suppress(HTTPException):
            mount_sets.append(_get_container_mounts(self_container))

    for mounts in mount_sets:
        for mount in mounts:
            destination = _mount_destination(mount)
            source = _mount_source(mount)
            if not destination or not source:
                continue
            if destination == "/app/server/workspace":
                return source.rstrip("/")
            if destination == "/app/server":
                return f"{source.rstrip('/')}/workspace"

    settings = get_settings()
    configured = settings.SANDBOX_WORKSPACE_HOST_ROOT
    if configured:
        logger.warning(
            "Workspace host root mount auto-discovery failed; falling back to SANDBOX_WORKSPACE_HOST_ROOT=%s",
            configured,
        )
        return configured.rstrip("/")

    raise HTTPException(
        status_code=500,
        detail=(
            "Could not resolve host path for /app/server/workspace. "
            "Set SANDBOX_WORKSPACE_HOST_ROOT explicitly."
        ),
    )


def _ensure_agent_workspace_dir(username: str, agent_id: int) -> None:
    """Create agent workspace path via backend container to ensure bind source exists."""
    path_in_backend = _workspace_target(username, agent_id)
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


def _normalize_skill_names(raw_skill_names: list[str] | None) -> list[str]:
    """Sanitize and deduplicate skill names for mount resolution.

    Args:
        raw_skill_names: Raw skills list from request payload.

    Returns:
        Stable-order deduplicated skill names.
    """
    if not raw_skill_names:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw_skill_names:
        if not isinstance(value, str):
            continue
        skill_name = value.strip()
        if not skill_name or skill_name in seen:
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+", skill_name) is None:
            logger.warning("sandbox.skills skip invalid skill name: %s", value)
            continue
        seen.add(skill_name)
        normalized.append(skill_name)
    return normalized


def _resolve_skill_source_dir(username: str, skill_name: str) -> str | None:
    """Resolve host path for one allowed skill directory.

    Search order mirrors prompt skill resolution precedence:
    private -> shared -> builtin.
    """
    backend_candidates = (
        f"/app/server/workspace/{username}/skills/private/{skill_name}",
        f"/app/server/workspace/{username}/skills/shared/{skill_name}",
        f"/app/server/app/orchestration/skills/builtin/{skill_name}",
    )
    backend = _backend_container()
    for candidate in backend_candidates:
        try:
            exists_result = backend.exec_run(
                ["test", "-d", candidate],
                workdir="/",
                tty=False,
                stream=False,
                socket=False,
            )
        except Exception:
            continue

        if isinstance(exists_result, tuple) and len(exists_result) == 2:
            exists_exit_code = int(exists_result[0])
        else:
            exists_exit_code = int(getattr(exists_result, "exit_code", -1))
        if exists_exit_code != 0:
            continue

        host_path = _resolve_host_path_from_backend_path(candidate)
        if host_path is not None:
            return host_path

    return None


def _build_skill_mounts(
    username: str, skill_names: list[str]
) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Build bind-mount map for allowed skills.

    Args:
        username: Current sandbox user.
        skill_names: Sanitized skill names allowed for this agent.

    Returns:
        Tuple of ``(volumes_map, mounted_skill_name_set)``.
    """
    volumes: dict[str, dict[str, str]] = {}
    mounted_skill_names: set[str] = set()
    for skill_name in skill_names:
        source_dir = _resolve_skill_source_dir(username, skill_name)
        if source_dir is None:
            logger.warning(
                "sandbox.skills source not found; skip mount username=%s skill=%s",
                username,
                skill_name,
            )
            continue
        volumes[source_dir] = {
            "bind": f"/workspace/skills/{skill_name}",
            "mode": "ro",
        }
        mounted_skill_names.add(skill_name)
    return volumes, mounted_skill_names


def _mounted_skill_names(container: Any) -> set[str]:
    """Read currently mounted skill names from a sandbox container."""
    try:
        mounts = _get_container_mounts(container)
    except HTTPException:
        return set()

    skill_names: set[str] = set()
    for mount in mounts:
        destination = _mount_destination(mount)
        if not isinstance(destination, str):
            continue
        prefix = "/workspace/skills/"
        if not destination.startswith(prefix):
            continue
        suffix = destination[len(prefix) :]
        if "/" in suffix or not suffix:
            continue
        skill_names.add(suffix)
    return skill_names


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


def _remove_container_fast(container: Any, *, reason: str) -> int:
    """Remove container with fast path, avoiding long graceful-stop timeout."""
    started = time.perf_counter()
    with suppress(Exception):
        container.kill()
    container.remove(force=True)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info("sandbox.remove reason=%s remove_ms=%d", reason, elapsed_ms)
    return elapsed_ms


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


def _should_recreate_container(
    container: Any, expected_skill_names: set[str]
) -> tuple[bool, str]:
    """Decide whether an existing sandbox container must be recreated.

    Recreate when configuration is unsafe/legacy or skill mounts drift:
    - working dir is not ``/workspace``
    - full project mounts (e.g. ``/app/server`` or ``/app/web``) are present
    - ``/workspace`` mount is missing
    - mounted ``/workspace/skills/*`` set differs from expected
    """
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
    if "/app/server" in destinations or "/app/web" in destinations:
        return True, "unsafe_project_mount"
    mounted_skills = _mounted_skill_names(container)
    if mounted_skills != expected_skill_names:
        return True, "skill_mount_mismatch"
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
    username: str, agent_id: int, skills: list[str] | None = None
) -> Any:
    """Create or start a reusable sidecar sandbox container."""
    op_started = time.perf_counter()
    settings = get_settings()
    name = _sandbox_name(username, agent_id)
    _ensure_agent_workspace_dir(username, agent_id)
    normalized_skills = _normalize_skill_names(skills)
    skill_volumes, expected_skill_names = _build_skill_mounts(
        username, normalized_skills
    )

    existing = _find_container(name)
    if existing is not None:
        should_recreate, recreate_reason = _should_recreate_container(
            existing, expected_skill_names
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
            "sandbox.recreate_remove name=%s username=%s agent_id=%d reason=%s",
            name,
            username,
            agent_id,
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
                return _ensure_sandbox(username, agent_id, normalized_skills)
            if "already running" not in message:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to start sandbox '{name}': {exc}",
                ) from exc
        _touch_container(name)
        logger.info(
            "sandbox.ensure name=%s username=%s agent_id=%d mode=reuse start_ms=%d total_ms=%d",
            name,
            username,
            agent_id,
            int((time.perf_counter() - start_started) * 1000),
            int((time.perf_counter() - op_started) * 1000),
        )
        return existing

    workspace_host_root = _resolve_workspace_host_root()
    workspace_host_dir = (
        f"{workspace_host_root.rstrip('/')}/{username}/agents/{agent_id}"
    )
    volumes = {workspace_host_dir: {"bind": "/workspace", "mode": "rw"}}
    volumes.update(skill_volumes)
    setup_cmd = "sleep infinity"
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
            # Mount only the current agent workspace; never mount full project tree.
            volumes=volumes,
            environment={"PYTHONUNBUFFERED": "1"},
        )
        create_ms = int((time.perf_counter() - create_started) * 1000)
        start_started = time.perf_counter()
        container.start()
        start_ms = int((time.perf_counter() - start_started) * 1000)
        logger.info(
            "sandbox.ensure name=%s username=%s agent_id=%d mode=create create_ms=%d start_ms=%d total_ms=%d",
            name,
            username,
            agent_id,
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


class SandboxRequest(BaseModel):
    """Request payload for create/destroy operations."""

    username: str = Field(min_length=1)
    agent_id: int
    skills: list[str] = Field(default_factory=list)


class SandboxExecRequest(SandboxRequest):
    """Request payload for command execution."""

    cmd: list[str] = Field(min_length=1)


class SandboxExecResponse(BaseModel):
    """Response payload for command execution."""

    exit_code: int
    stdout: str
    stderr: str
    container_name: str


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
            _remove_container_fast(container, reason="pool_idle_ttl")
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
            _remove_container_fast(container, reason="pool_lru_overflow")
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


@app.post("/sandboxes/create", dependencies=[Depends(_require_token)])
def create_sandbox(payload: SandboxRequest) -> dict[str, str]:
    """Create sandbox container for one user+agent pair (idempotent)."""
    container = _ensure_sandbox(payload.username, payload.agent_id, payload.skills)
    return {
        "container_name": _sandbox_name(payload.username, payload.agent_id),
        "container_id": container.id,
    }


@app.post("/sandboxes/destroy", dependencies=[Depends(_require_token)])
def destroy_sandbox(payload: SandboxRequest) -> dict[str, str]:
    """Stop and remove sandbox container for one user+agent pair."""
    started = time.perf_counter()
    name = _sandbox_name(payload.username, payload.agent_id)
    container = _find_container(name)
    if container is None:
        with _pool_lock:
            _last_used_by_name.pop(name, None)
        logger.info(
            "sandbox.destroy name=%s username=%s agent_id=%d status=not_found total_ms=%d",
            name,
            payload.username,
            payload.agent_id,
            int((time.perf_counter() - started) * 1000),
        )
        return {"status": "not_found", "container_name": name}
    try:
        _remove_container_fast(container, reason="destroy_api")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to destroy sandbox {name}: {exc}",
        ) from exc
    with _pool_lock:
        _last_used_by_name.pop(name, None)
    logger.info(
        "sandbox.destroy name=%s username=%s agent_id=%d status=destroyed total_ms=%d",
        name,
        payload.username,
        payload.agent_id,
        int((time.perf_counter() - started) * 1000),
    )
    return {"status": "destroyed", "container_name": name}


@app.post("/sandboxes/exec", dependencies=[Depends(_require_token)])
def exec_in_sandbox(payload: SandboxExecRequest) -> SandboxExecResponse:
    """Exec one command in sandbox and return stdout/stderr + exit code."""
    started = time.perf_counter()
    ensure_started = time.perf_counter()
    container = _ensure_sandbox(payload.username, payload.agent_id, payload.skills)
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
                "username=%s agent_id=%d err=%s",
                payload.username,
                payload.agent_id,
                message,
            )
            with suppress(Exception):
                _remove_container_fast(container, reason="recreate:exec_runtime_error")
            container = _ensure_sandbox(
                payload.username,
                payload.agent_id,
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
        "sandbox.exec name=%s username=%s agent_id=%d exit_code=%d ensure_ms=%d exec_ms=%d total_ms=%d",
        _sandbox_name(payload.username, payload.agent_id),
        payload.username,
        payload.agent_id,
        exit_code,
        ensure_ms,
        exec_ms,
        total_ms,
    )

    return SandboxExecResponse(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        container_name=_sandbox_name(payload.username, payload.agent_id),
    )
