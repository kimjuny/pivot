"""SeaweedFS-backed storage providers."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import requests
from app.storage.providers.local_fs import _normalize_key
from app.storage.types import ObjectStorageProvider, StoredObject

_HTTP_TIMEOUT_SECONDS = 5


class SeaweedFSFilerObjectStorageProvider(ObjectStorageProvider):
    """Use the SeaweedFS filer HTTP API as one object-style backend."""

    backend_name = "seaweedfs"

    def __init__(
        self,
        *,
        filer_endpoint: str,
        posix_root: Path | None = None,
    ) -> None:
        """Store the filer endpoint and optional mounted POSIX root."""
        self._filer_endpoint = filer_endpoint.rstrip("/")
        self._posix_root = posix_root

    def healthcheck(self) -> None:
        """Ensure the filer endpoint responds before the profile is activated."""
        response = requests.get(
            f"{self._filer_endpoint}/",
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

    def get_bytes(self, key: str) -> bytes:
        """Return one filer-backed payload by logical key."""
        response = requests.get(self._object_url(key), timeout=_HTTP_TIMEOUT_SECONDS)
        if response.status_code == 404:
            raise FileNotFoundError(f"Object key not found: {key}")
        response.raise_for_status()
        return response.content

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Persist one payload by uploading it through the filer API."""
        files = {
            "file": (
                Path(key).name or "blob",
                data,
                content_type or "application/octet-stream",
            )
        }
        response = requests.post(
            self._object_url(key),
            files=files,
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return StoredObject(
            storage_backend=self.backend_name,
            object_key=key,
            size_bytes=len(data),
        )

    def delete(self, key: str) -> None:
        """Delete one logical key through the filer API."""
        response = requests.delete(self._object_url(key), timeout=_HTTP_TIMEOUT_SECONDS)
        if response.status_code in {200, 202, 204, 404}:
            return
        response.raise_for_status()

    def exists(self, key: str) -> bool:
        """Return whether one filer-backed object currently exists."""
        response = requests.head(self._object_url(key), timeout=_HTTP_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def resolve_local_path(self, key: str) -> Path:
        """Return the mounted local path when SeaweedFS is also mounted on host."""
        if self._posix_root is None:
            raise ValueError("SeaweedFS provider is not configured with a POSIX root.")
        return self._posix_root.joinpath(*_normalize_key(key))

    def _object_url(self, key: str) -> str:
        """Build one filer URL from a logical storage key."""
        normalized_key = "/".join(_normalize_key(key))
        encoded_path = "/".join(
            quote(part, safe="") for part in normalized_key.split("/")
        )
        return f"{self._filer_endpoint}/{encoded_path}"
