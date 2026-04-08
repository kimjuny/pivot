"""Reusable binary object storage backends for persisted application assets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote

import requests
from app.config import Settings, get_settings
from app.services.local_data_paths_service import local_data_root

_REQUEST_TIMEOUT_SECONDS = 20

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class StoredBinary:
    """Metadata returned after one binary payload is persisted."""

    storage_backend: str
    storage_key: str
    content_digest: str
    size_bytes: int


class BinaryStorageBackend(Protocol):
    """Minimal object-style storage contract for persisted binary payloads."""

    backend_name: str

    def put_bytes(self, *, payload: bytes, key: str) -> StoredBinary:
        """Persist one payload under a stable storage key."""
        ...

    def read_bytes(self, *, key: str) -> bytes:
        """Return the stored bytes for one storage key."""
        ...

    def delete(self, *, key: str) -> None:
        """Delete one storage key if it exists."""
        ...


def _normalize_storage_key(key: str) -> str:
    """Return a safe object-style storage key."""
    normalized_key = key.strip().replace("\\", "/")
    if normalized_key == "":
        raise ValueError("Storage key must not be empty.")
    parts = [part for part in normalized_key.split("/") if part not in {"", ".", ".."}]
    if not parts:
        raise ValueError("Storage key must contain at least one safe path part.")
    return "/".join(parts)


class LocalFilesystemBinaryStorageBackend:
    """Persist binary payloads under the workspace-local storage root."""

    backend_name = "local_fs"

    @staticmethod
    def _storage_root() -> Path:
        root = local_data_root() / "storage"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _resolve_key_path(self, key: str) -> Path:
        return self._storage_root().joinpath(*_normalize_storage_key(key).split("/"))

    def put_bytes(self, *, payload: bytes, key: str) -> StoredBinary:
        target_path = self._resolve_key_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return StoredBinary(
            storage_backend=self.backend_name,
            storage_key=_normalize_storage_key(key),
            content_digest=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

    def read_bytes(self, *, key: str) -> bytes:
        try:
            return self._resolve_key_path(key).read_bytes()
        except FileNotFoundError as err:
            raise FileNotFoundError(_normalize_storage_key(key)) from err

    def delete(self, *, key: str) -> None:
        self._resolve_key_path(key).unlink(missing_ok=True)


class SeaweedfsFilerBinaryStorageBackend:
    """Persist binary payloads through the SeaweedFS filer HTTP interface."""

    backend_name = "seaweedfs"

    def __init__(self, *, filer_url: str) -> None:
        self._filer_url = filer_url.rstrip("/")

    def _build_url(self, key: str) -> str:
        normalized_key = _normalize_storage_key(key)
        return f"{self._filer_url}/{quote(normalized_key, safe='/')}"

    def put_bytes(self, *, payload: bytes, key: str) -> StoredBinary:
        response = requests.put(
            self._build_url(key),
            data=payload,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return StoredBinary(
            storage_backend=self.backend_name,
            storage_key=_normalize_storage_key(key),
            content_digest=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
        )

    def read_bytes(self, *, key: str) -> bytes:
        response = requests.get(
            self._build_url(key),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            raise FileNotFoundError(_normalize_storage_key(key))
        response.raise_for_status()
        return response.content

    def delete(self, *, key: str) -> None:
        response = requests.delete(
            self._build_url(key),
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code not in {200, 202, 204, 404}:
            response.raise_for_status()


def build_binary_storage_backend(
    settings: Settings | None = None,
) -> BinaryStorageBackend:
    """Build the configured binary storage backend for persisted assets."""
    active_settings = settings or get_settings()
    backend_name = active_settings.PERSISTED_STORAGE_BACKEND.strip().lower()
    if backend_name == "seaweedfs":
        return SeaweedfsFilerBinaryStorageBackend(
            filer_url=active_settings.SEAWEEDFS_FILER_URL
        )
    if backend_name == "local_fs":
        return LocalFilesystemBinaryStorageBackend()
    raise ValueError(f"Unsupported persisted storage backend '{backend_name}'.")
