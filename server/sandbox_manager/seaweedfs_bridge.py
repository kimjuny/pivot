"""SeaweedFS bridge helpers used by sandbox-manager runtime drivers."""

from __future__ import annotations

import hashlib
import logging
import socket
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from fastapi import HTTPException

logger = logging.getLogger("uvicorn.error")
_SEAWEEDFS_HTTP_TIMEOUT_SECONDS = 20


def _assert_service_reachable(url: str, *, label: str) -> None:
    """Fail fast when one required TCP service is unreachable."""
    parsed = urlsplit(url)
    hostname = parsed.hostname
    port = parsed.port
    if not hostname or port is None:
        raise HTTPException(
            status_code=500,
            detail=f"{label} URL is invalid: {url!r}.",
        )

    try:
        with socket.create_connection((hostname, port), timeout=3):
            return
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{label} is unreachable at {hostname}:{port}: {exc}",
        ) from exc


def _seaweedfs_filer_object_url(filer_url: str, logical_path: str) -> str:
    """Return the filer URL for one logical object path."""
    normalized_path = logical_path.strip().strip("/")
    if not normalized_path:
        raise HTTPException(status_code=400, detail="logical_path must not be empty.")
    return f"{filer_url.rstrip('/')}/{quote(normalized_path, safe='/')}"


def _seaweedfs_filer_directory_url(filer_url: str, logical_path: str) -> str:
    """Return the filer URL for one logical directory path."""
    return _seaweedfs_filer_object_url(filer_url, logical_path) + "/"


def _seaweedfs_entry_is_directory(entry: dict[str, Any]) -> bool:
    """Return whether one filer JSON entry represents a directory."""
    return entry.get("Md5") is None and int(entry.get("FileSize", 0)) == 0


def _seaweedfs_list_directory_entries(
    *,
    filer_url: str,
    logical_path: str,
) -> list[dict[str, Any]] | None:
    """Return one directory's immediate filer entries, or None when absent."""
    response = requests.get(
        _seaweedfs_filer_directory_url(filer_url, logical_path),
        headers={"Accept": "application/json"},
        params={"limit": 1000},
        timeout=_SEAWEEDFS_HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail="SeaweedFS filer returned a non-object directory payload.",
        )
    entries = payload.get("Entries", [])
    if not isinstance(entries, list):
        raise HTTPException(
            status_code=500,
            detail="SeaweedFS filer returned an invalid directory listing.",
        )
    return [entry for entry in entries if isinstance(entry, dict)]


def _seaweedfs_directory_has_entries(*, filer_url: str, logical_path: str) -> bool:
    """Return whether one filer directory currently contains any entries."""
    entries = _seaweedfs_list_directory_entries(
        filer_url=filer_url,
        logical_path=logical_path,
    )
    return bool(entries)


def _seaweedfs_walk_file_paths(
    *,
    filer_url: str,
    logical_path: str,
) -> list[str]:
    """Return all file paths beneath one filer directory."""
    normalized_root = logical_path.strip().strip("/")
    entries = _seaweedfs_list_directory_entries(
        filer_url=filer_url,
        logical_path=normalized_root,
    )
    if entries is None:
        return []

    file_paths: list[str] = []
    for entry in entries:
        name = entry.get("FullPath")
        if not isinstance(name, str):
            continue
        if _seaweedfs_entry_is_directory(entry):
            file_paths.extend(
                _seaweedfs_walk_file_paths(filer_url=filer_url, logical_path=name)
            )
        else:
            file_paths.append(name)
    return file_paths


def _seaweedfs_walk_files(
    *,
    filer_url: str,
    logical_path: str,
) -> dict[str, dict[str, Any]]:
    """Return one mapping of remote filer file path to filer entry metadata."""
    normalized_root = logical_path.strip().strip("/")
    entries = _seaweedfs_list_directory_entries(
        filer_url=filer_url,
        logical_path=normalized_root,
    )
    if entries is None:
        return {}

    files: dict[str, dict[str, Any]] = {}
    for entry in entries:
        full_path = entry.get("FullPath")
        if not isinstance(full_path, str):
            continue
        if _seaweedfs_entry_is_directory(entry):
            files.update(_seaweedfs_walk_files(filer_url=filer_url, logical_path=full_path))
        else:
            files[full_path] = entry
    return files


def _prune_empty_local_directories(root_dir: Path) -> None:
    """Delete empty directories beneath one local sync root."""
    for directory in sorted(root_dir.rglob("*"), reverse=True):
        if not directory.is_dir():
            continue
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()


def _file_md5_hex(path: Path) -> str:
    """Return one local file's MD5 digest as a lowercase hex string."""
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


def _sync_local_workspace_from_seaweedfs(
    *,
    filer_url: str,
    logical_path: str,
    local_dir: Path,
) -> None:
    """Mirror one filer workspace tree into a local runtime directory."""
    normalized_root = logical_path.strip().strip("/")
    remote_files = _seaweedfs_walk_files(
        filer_url=filer_url,
        logical_path=normalized_root,
    )
    remote_relative_paths: set[Path] = set()
    for remote_file_path, entry in sorted(remote_files.items()):
        relative_path = Path(remote_file_path.removeprefix(f"{normalized_root}/"))
        remote_relative_paths.add(relative_path)
        target_path = local_dir / relative_path
        remote_md5 = entry.get("Md5")
        if (
            isinstance(remote_md5, str)
            and target_path.is_file()
            and _file_md5_hex(target_path) == remote_md5.lower()
        ):
            continue
        response = requests.get(
            _seaweedfs_filer_object_url(filer_url, remote_file_path),
            timeout=_SEAWEEDFS_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(response.content)
    for local_path in sorted(local_dir.rglob("*")):
        if not local_path.is_file():
            continue
        if local_path.relative_to(local_dir) not in remote_relative_paths:
            local_path.unlink(missing_ok=True)
    _prune_empty_local_directories(local_dir)


def _workspace_mount_mode_should_sync(mount_mode: str) -> bool:
    """Return whether one workspace mount mode should flush local changes."""
    return mount_mode.strip().lower() == "live_sync"


def _sync_local_workspace_to_seaweedfs(
    *,
    filer_url: str,
    logical_path: str,
    local_dir: Path,
) -> None:
    """Mirror one local runtime directory back into filer storage."""
    normalized_root = logical_path.strip().strip("/")
    remote_files = _seaweedfs_walk_files(
        filer_url=filer_url,
        logical_path=normalized_root,
    )

    if not local_dir.exists():
        for remote_file_path in sorted(remote_files):
            delete_response = requests.delete(
                _seaweedfs_filer_object_url(filer_url, remote_file_path),
                timeout=_SEAWEEDFS_HTTP_TIMEOUT_SECONDS,
            )
            if delete_response.status_code not in {200, 202, 204, 404}:
                delete_response.raise_for_status()
        return

    local_files: dict[str, Path] = {}
    for path in sorted(local_dir.rglob("*")):
        if path.is_symlink():
            logger.warning("sandbox.workspace skip symlink during SeaweedFS sync: %s", path)
            continue
        if not path.is_file():
            continue
        relative_path = path.relative_to(local_dir).as_posix()
        upload_path = f"{normalized_root}/{relative_path}"
        local_files[upload_path] = path
        remote_md5 = remote_files.get(upload_path, {}).get("Md5")
        if isinstance(remote_md5, str) and _file_md5_hex(path) == remote_md5.lower():
            continue
        response = requests.put(
            _seaweedfs_filer_object_url(filer_url, upload_path),
            data=path.read_bytes(),
            timeout=_SEAWEEDFS_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    for remote_file_path in sorted(remote_files):
        if remote_file_path in local_files:
            continue
        delete_response = requests.delete(
            _seaweedfs_filer_object_url(filer_url, remote_file_path),
            timeout=_SEAWEEDFS_HTTP_TIMEOUT_SECONDS,
        )
        if delete_response.status_code not in {200, 202, 204, 404}:
            delete_response.raise_for_status()
