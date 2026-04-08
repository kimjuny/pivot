"""Canonical storage and lazy local materialization for creator-owned tools."""

from __future__ import annotations

import importlib.util
import inspect
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from app.config import Settings, get_settings
from app.orchestration.tool.metadata import ToolMetadata
from app.services.binary_storage_service import (
    BinaryStorageBackend,
    build_binary_storage_backend,
)
from app.services.local_data_paths_service import (
    local_data_root,
    local_runtime_cache_root,
)
from app.utils.logging_config import get_logger

logger = get_logger("user_tool_storage_service")
_REQUEST_TIMEOUT_SECONDS = 20
_user_tool_storage_service: UserToolStorageService | None = None


def _normalize_tool_name(tool_name: str) -> str:
    """Return one normalized tool name safe for canonical storage layout."""
    normalized = tool_name.strip()
    if normalized in {"", ".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("Tool name must be a single safe path segment.")
    return normalized


def _seaweedfs_entry_is_directory(entry: dict[str, Any]) -> bool:
    """Return whether one filer JSON entry represents a directory."""
    return entry.get("Md5") is None and int(entry.get("FileSize", 0)) == 0


class UserToolStorageService:
    """Manage canonical user tools plus lazy local materialized cache copies."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        storage_backend: BinaryStorageBackend | None = None,
    ) -> None:
        """Store configuration and canonical binary backend."""
        self.settings = settings or get_settings()
        self.storage_backend = storage_backend or build_binary_storage_backend(
            self.settings
        )

    @staticmethod
    def build_storage_key(*, username: str, tool_name: str) -> str:
        """Return the canonical storage key for one user-owned tool."""
        normalized_tool_name = _normalize_tool_name(tool_name)
        return f"users/{username}/tools/{normalized_tool_name}/tool.py"

    @staticmethod
    def local_cache_root(*, username: str) -> Path:
        """Return the local materialized cache root for one user's tools."""
        root = local_runtime_cache_root() / "users" / username / "tools"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def local_cache_path(self, *, username: str, tool_name: str) -> Path:
        """Return the local materialized cache file path for one tool."""
        normalized_tool_name = _normalize_tool_name(tool_name)
        return self.local_cache_root(username=username) / normalized_tool_name / "tool.py"

    def list_user_tools(self, username: str) -> list[dict[str, str]]:
        """List creator-owned tools by canonical storage state."""
        tools: list[dict[str, str]] = []
        for tool_name in self._list_tool_names(username=username):
            metadata = self.load_user_tool_metadata(username, tool_name)
            tools.append(
                {
                    "name": tool_name,
                    "filename": "tool.py",
                    "tool_type": (
                        metadata.tool_type if metadata is not None else "normal"
                    ),
                }
            )
        return tools

    def read_user_tool(self, username: str, tool_name: str) -> str:
        """Read one user tool from canonical storage via local materialization."""
        tool_path = self.ensure_local_tool_cache(username=username, tool_name=tool_name)
        return tool_path.read_text(encoding="utf-8")

    def write_user_tool(self, username: str, tool_name: str, source: str) -> None:
        """Persist one user tool canonically and refresh the local cache copy."""
        normalized_tool_name = _normalize_tool_name(tool_name)
        storage_key = self.build_storage_key(
            username=username,
            tool_name=normalized_tool_name,
        )
        self.storage_backend.put_bytes(
            payload=source.encode("utf-8"),
            key=storage_key,
        )
        tool_path = self.local_cache_path(
            username=username,
            tool_name=normalized_tool_name,
        )
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_text(source, encoding="utf-8")
        logger.info("Wrote tool '%s' for user '%s'", normalized_tool_name, username)

    def delete_user_tool(self, username: str, tool_name: str) -> None:
        """Delete one user tool from canonical storage and local cache."""
        normalized_tool_name = _normalize_tool_name(tool_name)
        if normalized_tool_name not in set(self._list_tool_names(username=username)):
            raise FileNotFoundError(
                f"Tool '{normalized_tool_name}' not found for user '{username}'."
            )

        self.storage_backend.delete(
            key=self.build_storage_key(
                username=username,
                tool_name=normalized_tool_name,
            )
        )
        cache_dir = self.local_cache_path(
            username=username,
            tool_name=normalized_tool_name,
        ).parent
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        logger.info("Deleted tool '%s' for user '%s'", normalized_tool_name, username)

    def load_all_user_tool_metadata(self, username: str) -> list[ToolMetadata]:
        """Load metadata for all tools visible to one user."""
        results: list[ToolMetadata] = []
        for tool_name in self._list_tool_names(username=username):
            metadata = self.load_user_tool_metadata(username, tool_name)
            if metadata is not None:
                results.append(metadata)
        return results

    def load_user_tool_metadata(
        self,
        username: str,
        tool_name: str,
    ) -> ToolMetadata | None:
        """Load metadata for one canonically stored user tool."""
        try:
            tool_path = self.ensure_local_tool_cache(
                username=username,
                tool_name=tool_name,
            )
        except FileNotFoundError:
            return None

        module_key = f"_pivot_user_tool_{username}_{_normalize_tool_name(tool_name)}"
        spec = importlib.util.spec_from_file_location(module_key, tool_path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        try:
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Failed to load tool module '%s': %s", tool_name, exc)
            return None

        for _name, obj in inspect.getmembers(module, inspect.isfunction):
            metadata = getattr(obj, "__tool_metadata__", None)
            if metadata is not None and isinstance(metadata, ToolMetadata):
                return metadata
        return None

    def ensure_local_tool_cache(self, *, username: str, tool_name: str) -> Path:
        """Ensure one tool exists as a local cache file and return its path."""
        normalized_tool_name = _normalize_tool_name(tool_name)
        tool_path = self.local_cache_path(
            username=username,
            tool_name=normalized_tool_name,
        )
        if tool_path.is_file():
            return tool_path

        try:
            payload = self.storage_backend.read_bytes(
                key=self.build_storage_key(
                    username=username,
                    tool_name=normalized_tool_name,
                )
            )
        except FileNotFoundError as err:
            raise FileNotFoundError(
                f"Tool '{normalized_tool_name}' not found for user '{username}'."
            ) from err

        tool_path.parent.mkdir(parents=True, exist_ok=True)
        tool_path.write_bytes(payload)
        return tool_path

    def _list_tool_names(self, *, username: str) -> list[str]:
        """List canonical tool names for one user."""
        backend_name = self.storage_backend.backend_name
        if backend_name == "seaweedfs":
            return self._list_tool_names_from_seaweedfs(username=username)
        if backend_name == "local_fs":
            return self._list_tool_names_from_local_storage(username=username)
        raise ValueError(f"Unsupported tool storage backend '{backend_name}'.")

    def _list_tool_names_from_local_storage(self, *, username: str) -> list[str]:
        """List tool names from local fallback storage layout."""
        root = local_data_root() / "storage" / "users" / username / "tools"
        if not root.exists():
            return []

        names: list[str] = []
        for candidate in sorted(root.iterdir()):
            tool_entry = candidate / "tool.py"
            if candidate.is_dir() and tool_entry.is_file():
                names.append(candidate.name)
        return names

    def _list_tool_names_from_seaweedfs(self, *, username: str) -> list[str]:
        """List tool names from SeaweedFS filer under the canonical user prefix."""
        tools_root = f"users/{username}/tools"
        response = requests.get(
            f"{self.settings.SEAWEEDFS_FILER_URL.rstrip('/')}/{quote(tools_root, safe='/')}/",
            headers={"Accept": "application/json"},
            params={"limit": 1000},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
        entries = payload.get("Entries", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            return []

        names: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or not _seaweedfs_entry_is_directory(entry):
                continue
            full_path = entry.get("FullPath")
            if not isinstance(full_path, str):
                continue
            names.append(Path(full_path).name)
        return sorted(set(names))


def get_user_tool_storage_service() -> UserToolStorageService:
    """Return the process-wide user tool storage service singleton."""
    global _user_tool_storage_service
    if _user_tool_storage_service is None:
        _user_tool_storage_service = UserToolStorageService()
    return _user_tool_storage_service
