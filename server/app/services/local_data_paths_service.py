"""Centralized local data and runtime cache path helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from app.config import Settings, get_settings

_APP_DIRECTORY_NAME = "pivot"
_LOCAL_DATA_ROOT_OVERRIDE: Path | None = None
_LOCAL_CACHE_ROOT_OVERRIDE: Path | None = None


def _platform_data_base() -> Path:
    """Return the platform-appropriate base directory for local app data."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home)
    return Path.home() / ".local" / "share"


def _platform_cache_base() -> Path:
    """Return the platform-appropriate base directory for local cache data."""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home)
    return Path.home() / ".cache"


def _resolve_data_root(settings: Settings) -> Path:
    """Resolve the local persisted-data root from settings or platform defaults."""
    if _LOCAL_DATA_ROOT_OVERRIDE is not None:
        return _LOCAL_DATA_ROOT_OVERRIDE
    if settings.LOCAL_DATA_ROOT:
        return Path(settings.LOCAL_DATA_ROOT).expanduser()
    return _platform_data_base() / _APP_DIRECTORY_NAME


def _resolve_cache_root(settings: Settings) -> Path:
    """Resolve the local runtime-cache root from settings or platform defaults."""
    if _LOCAL_CACHE_ROOT_OVERRIDE is not None:
        return _LOCAL_CACHE_ROOT_OVERRIDE
    if settings.LOCAL_CACHE_ROOT:
        return Path(settings.LOCAL_CACHE_ROOT).expanduser()
    return _platform_cache_base() / _APP_DIRECTORY_NAME


def local_data_root(settings: Settings | None = None) -> Path:
    """Return the local persisted-data root for backend-side fallback storage."""
    root = _resolve_data_root(settings or get_settings())
    root.mkdir(parents=True, exist_ok=True)
    return root


def local_runtime_cache_root(settings: Settings | None = None) -> Path:
    """Return the local runtime-cache root for materialized service data."""
    root = _resolve_cache_root(settings or get_settings())
    root.mkdir(parents=True, exist_ok=True)
    return root

