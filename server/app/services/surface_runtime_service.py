"""Service layer for installed chat surface runtime assets."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.surface_session_service import (
    SurfaceSessionRecord,
    SurfaceSessionValidationError,
)


class SurfaceRuntimeNotFoundError(Exception):
    """Raised when an installed surface runtime asset does not exist."""


@dataclass(frozen=True)
class SurfaceRuntimeAsset:
    """One resolved installed surface runtime asset payload."""

    content: bytes
    content_type: str


class SurfaceRuntimeService:
    """Read packaged runtime assets for installed chat surface sessions."""

    def read_installed_asset(
        self,
        *,
        record: SurfaceSessionRecord,
        requested_path: str,
    ) -> SurfaceRuntimeAsset:
        """Read one installed runtime asset from the materialized extension root.

        Args:
            record: Installed surface session record that owns the runtime.
            requested_path: Runtime-relative path requested by the iframe route.

        Returns:
            Resolved runtime asset payload.

        Raises:
            SurfaceRuntimeNotFoundError: If the requested asset does not exist.
            SurfaceSessionValidationError: If the session does not expose an
                installed packaged runtime or the path escapes the package root.
        """
        if (
            record.mode != "installed"
            or record.runtime_install_root is None
            or record.runtime_entrypoint_path is None
            or record.runtime_entrypoint_parent_path is None
        ):
            raise SurfaceSessionValidationError(
                "Installed runtime assets are only available for packaged surface sessions."
            )

        entrypoint_path = Path(record.runtime_entrypoint_path).resolve()
        install_root = Path(record.runtime_install_root).resolve()
        target_path = self._resolve_target_path(
            install_root=install_root,
            entrypoint_path=entrypoint_path,
            entrypoint_parent_path=record.runtime_entrypoint_parent_path,
            requested_path=requested_path,
        )
        if not target_path.is_file():
            raise SurfaceRuntimeNotFoundError("Installed surface asset not found.")

        content_type = (
            mimetypes.guess_type(target_path.name)[0] or "application/octet-stream"
        )
        return SurfaceRuntimeAsset(
            content=target_path.read_bytes(),
            content_type=content_type,
        )

    @staticmethod
    def _resolve_target_path(
        *,
        install_root: Path,
        entrypoint_path: Path,
        entrypoint_parent_path: str,
        requested_path: str,
    ) -> Path:
        """Resolve one requested runtime path under the package root."""
        normalized_requested = requested_path.strip("/")
        normalized_parent = entrypoint_parent_path.strip("/")

        if normalized_requested in {"", normalized_parent}:
            candidate = entrypoint_path
        else:
            safe_relative = PurePosixPath(normalized_requested)
            candidate = install_root.joinpath(*safe_relative.parts).resolve()

        if candidate != install_root and install_root not in candidate.parents:
            raise SurfaceSessionValidationError(
                "Installed surface asset path escapes the package runtime root."
            )
        return candidate
