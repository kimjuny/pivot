"""Service layer for lightweight chat surface sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

from app.models.extension import AgentExtensionBinding, ExtensionInstallation
from app.services.extension_service import ExtensionService
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession

_DEFAULT_SURFACE_CAPABILITIES = ["workspace.read", "workspace.write"]


class SurfaceSessionError(Exception):
    """Base error for chat surface session failures."""


class SurfaceSessionNotFoundError(SurfaceSessionError):
    """Raised when a requested surface session does not exist."""


class SurfaceSessionPermissionError(SurfaceSessionError):
    """Raised when a caller does not own a requested surface session."""


class SurfaceSessionValidationError(SurfaceSessionError):
    """Raised when a requested chat surface session is invalid."""


@dataclass(frozen=True)
class SurfaceSessionRecord:
    """In-memory chat surface session metadata."""

    surface_session_id: str
    mode: str
    surface_key: str
    display_name: str
    username: str
    agent_id: int
    session_id: str
    workspace_id: str
    dev_server_url: str | None
    package_id: str | None
    extension_installation_id: int | None
    runtime_install_root: str | None
    runtime_entrypoint_path: str | None
    runtime_entrypoint_parent_path: str | None
    created_at: datetime


_SURFACE_SESSIONS: dict[str, SurfaceSessionRecord] = {}
_SURFACE_SESSIONS_LOCK = RLock()


class SurfaceSessionService:
    """Create and resolve chat surface sessions for the current operator."""

    def __init__(self, db: DBSession) -> None:
        """Store the active database session.

        Args:
            db: Active database session.
        """
        self.db = db

    def create_dev_surface_session(
        self,
        *,
        username: str,
        session_id: str,
        surface_key: str,
        dev_server_url: str,
        display_name: str | None = None,
    ) -> SurfaceSessionRecord:
        """Create one in-memory development surface session.

        Args:
            username: Authenticated operator username.
            session_id: Chat session that owns the workspace.
            surface_key: Stable development surface key.
            dev_server_url: Author-local development runtime URL. This may be a
                server origin or a concrete entry HTML path.
            display_name: Optional operator-facing surface label.

        Returns:
            New surface session record.

        Raises:
            SurfaceSessionNotFoundError: If the chat session or workspace is missing.
            SurfaceSessionPermissionError: If the chat session is not owned.
            SurfaceSessionValidationError: If the request is invalid.
        """
        normalized_surface_key = surface_key.strip()
        if not normalized_surface_key:
            raise SurfaceSessionValidationError("Surface key is required.")

        normalized_dev_server_url = self._normalize_dev_server_url(dev_server_url)
        chat_session, workspace = self._resolve_owned_chat_session(
            username=username,
            session_id=session_id,
        )

        now = datetime.now(UTC)
        record = SurfaceSessionRecord(
            surface_session_id=str(uuid4()),
            mode="dev",
            surface_key=normalized_surface_key,
            display_name=display_name.strip()
            if isinstance(display_name, str) and display_name.strip()
            else normalized_surface_key,
            username=username,
            agent_id=chat_session.agent_id,
            session_id=chat_session.session_id,
            workspace_id=workspace.workspace_id,
            dev_server_url=normalized_dev_server_url,
            package_id=None,
            extension_installation_id=None,
            runtime_install_root=None,
            runtime_entrypoint_path=None,
            runtime_entrypoint_parent_path=None,
            created_at=now,
        )

        with _SURFACE_SESSIONS_LOCK:
            _SURFACE_SESSIONS[record.surface_session_id] = record

        return record

    def create_installed_surface_session(
        self,
        *,
        username: str,
        session_id: str,
        extension_installation_id: int,
        surface_key: str,
    ) -> SurfaceSessionRecord:
        """Create one in-memory installed surface session.

        Args:
            username: Authenticated operator username.
            session_id: Chat session that owns the workspace.
            extension_installation_id: Installed extension version bound to the
                current agent.
            surface_key: Stable surface key declared by the installed extension.

        Returns:
            New installed surface session record.

        Raises:
            SurfaceSessionNotFoundError: If the chat session or extension is missing.
            SurfaceSessionPermissionError: If the caller does not own the session.
            SurfaceSessionValidationError: If the installation does not expose the
                requested chat surface.
        """
        normalized_surface_key = surface_key.strip()
        if not normalized_surface_key:
            raise SurfaceSessionValidationError("Surface key is required.")

        chat_session, workspace = self._resolve_owned_chat_session(
            username=username,
            session_id=session_id,
        )

        statement = (
            select(AgentExtensionBinding, ExtensionInstallation)
            .join(
                ExtensionInstallation,
                col(AgentExtensionBinding.extension_installation_id)
                == col(ExtensionInstallation.id),
            )
            .where(AgentExtensionBinding.agent_id == chat_session.agent_id)
            .where(
                AgentExtensionBinding.extension_installation_id
                == extension_installation_id
            )
            .where(col(AgentExtensionBinding.enabled) == True)  # noqa: E712
            .where(col(ExtensionInstallation.status) == "active")
        )
        binding_row = self.db.exec(statement).first()
        if binding_row is None:
            raise SurfaceSessionNotFoundError(
                "Installed surface extension is not enabled for this agent."
            )

        _, installation = binding_row
        runtime_entry = ExtensionService(self.db).build_installation_runtime_entry(
            installation=installation
        )
        installed_surface = next(
            (
                surface
                for surface in runtime_entry.get("chat_surfaces", [])
                if isinstance(surface, dict)
                and str(surface.get("key", "")).strip() == normalized_surface_key
            ),
            None,
        )
        if installed_surface is None:
            raise SurfaceSessionValidationError(
                "Installed extension does not expose the requested chat surface."
            )

        source_path = str(installed_surface.get("source_path", "")).strip()
        if source_path == "":
            raise SurfaceSessionValidationError(
                "Installed chat surface is missing a runtime entrypoint."
            )

        entrypoint_path = Path(source_path).resolve()
        install_root = Path(str(runtime_entry["install_root"])).resolve()
        if entrypoint_path != install_root and install_root not in entrypoint_path.parents:
            raise SurfaceSessionValidationError(
                "Installed chat surface entrypoint is outside the materialized extension."
            )

        now = datetime.now(UTC)
        record = SurfaceSessionRecord(
            surface_session_id=str(uuid4()),
            mode="installed",
            surface_key=normalized_surface_key,
            display_name=str(installed_surface.get("display_name", normalized_surface_key)),
            username=username,
            agent_id=chat_session.agent_id,
            session_id=chat_session.session_id,
            workspace_id=workspace.workspace_id,
            dev_server_url=None,
            package_id=installation.package_id,
            extension_installation_id=installation.id,
            runtime_install_root=str(install_root),
            runtime_entrypoint_path=str(entrypoint_path),
            runtime_entrypoint_parent_path=str(
                entrypoint_path.parent.relative_to(install_root).as_posix()
            ),
            created_at=now,
        )

        with _SURFACE_SESSIONS_LOCK:
            _SURFACE_SESSIONS[record.surface_session_id] = record

        return record

    def get_surface_session(
        self,
        *,
        surface_session_id: str,
        username: str,
    ) -> SurfaceSessionRecord:
        """Return one owned surface session record.

        Args:
            surface_session_id: Public surface session identifier.
            username: Authenticated operator username.

        Returns:
            Matching surface session record.

        Raises:
            SurfaceSessionNotFoundError: If the record does not exist.
            SurfaceSessionPermissionError: If the record belongs to another user.
        """
        with _SURFACE_SESSIONS_LOCK:
            record = _SURFACE_SESSIONS.get(surface_session_id)
        if record is None:
            raise SurfaceSessionNotFoundError("Surface session not found.")
        if record.username != username:
            raise SurfaceSessionPermissionError(
                "Surface session is not owned by the caller."
            )
        return record

    def build_bootstrap(
        self,
        *,
        record: SurfaceSessionRecord,
    ) -> dict[str, object]:
        """Build the minimum runtime bootstrap payload for one surface session.

        Args:
            record: Surface session record to serialize.

        Returns:
            Bootstrap payload consumed by the host runtime.
        """
        session_path = self._build_session_base_path(record=record)
        files_base_url = f"{session_path}/files"
        workspace = WorkspaceService(self.db).get_workspace(record.workspace_id)
        if workspace is None:
            raise SurfaceSessionNotFoundError("Workspace not found.")
        payload: dict[str, object] = {
            "surface_session_id": record.surface_session_id,
            "mode": record.mode,
            "surface_key": record.surface_key,
            "display_name": record.display_name,
            "agent_id": record.agent_id,
            "session_id": record.session_id,
            "workspace_id": record.workspace_id,
            "workspace_logical_root": WorkspaceService(
                self.db
            ).get_workspace_logical_root(workspace),
            "capabilities": list(_DEFAULT_SURFACE_CAPABILITIES),
            "files_api": {
                "tree_url": f"{files_base_url}/tree",
                "content_url": f"{files_base_url}/content",
            },
        }
        if record.mode == "dev" and record.dev_server_url is not None:
            payload["dev_server_url"] = record.dev_server_url
        if (
            record.mode == "installed"
            and record.package_id is not None
            and record.extension_installation_id is not None
        ):
            payload["package_id"] = record.package_id
            payload["extension_installation_id"] = record.extension_installation_id
            payload["runtime_url"] = self.build_installed_runtime_url(record=record)
        return payload

    @staticmethod
    def clear_dev_surface_sessions() -> None:
        """Clear all in-memory surface sessions for isolated tests."""
        with _SURFACE_SESSIONS_LOCK:
            _SURFACE_SESSIONS.clear()

    def build_installed_runtime_url(self, *, record: SurfaceSessionRecord) -> str:
        """Return the host-facing iframe runtime URL for one installed surface."""
        if record.mode != "installed":
            raise SurfaceSessionValidationError(
                "Only installed surface sessions expose a packaged runtime URL."
            )

        runtime_base_path = (
            f"/api/chat-surfaces/installed-sessions/{record.surface_session_id}/runtime"
        )
        parent_path = (record.runtime_entrypoint_parent_path or "").strip("/")
        if parent_path:
            return f"{runtime_base_path}/{parent_path}/"
        return f"{runtime_base_path}/"

    def _build_session_base_path(self, *, record: SurfaceSessionRecord) -> str:
        """Return the API path prefix scoped to one surface session."""
        if record.mode == "installed":
            return f"/api/chat-surfaces/installed-sessions/{record.surface_session_id}"
        return f"/api/chat-surfaces/dev-sessions/{record.surface_session_id}"

    def _resolve_owned_chat_session(
        self,
        *,
        username: str,
        session_id: str,
    ):
        """Resolve one owned chat session plus its workspace.

        Args:
            username: Authenticated operator username.
            session_id: Chat session identifier to resolve.

        Returns:
            Tuple of ``(chat_session, workspace)``.

        Raises:
            SurfaceSessionNotFoundError: If the chat session or workspace is missing.
            SurfaceSessionPermissionError: If the chat session is not owned.
            SurfaceSessionValidationError: If the session does not have a workspace.
        """
        chat_session = SessionService(self.db).get_session(session_id)
        if chat_session is None:
            raise SurfaceSessionNotFoundError("Chat session not found.")
        if chat_session.user != username:
            raise SurfaceSessionPermissionError(
                "Chat session is not owned by the caller."
            )
        if chat_session.workspace_id is None:
            raise SurfaceSessionValidationError(
                "Chat session does not have an attached workspace."
            )

        workspace = WorkspaceService(self.db).get_workspace(chat_session.workspace_id)
        if workspace is None:
            raise SurfaceSessionNotFoundError("Workspace not found.")
        if workspace.user != username:
            raise SurfaceSessionPermissionError(
                "Workspace is not owned by the caller."
            )

        return chat_session, workspace

    @staticmethod
    def _normalize_dev_server_url(raw_url: str) -> str:
        """Validate one author-local development runtime URL.

        Args:
            raw_url: Caller-provided development runtime URL.

        Returns:
            Normalized development runtime URL.

        Raises:
            SurfaceSessionValidationError: If the URL is invalid or not local.
        """
        normalized = raw_url.strip()
        if not normalized:
            raise SurfaceSessionValidationError("Development server URL is required.")

        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"}:
            raise SurfaceSessionValidationError(
                "Development server URL must use http or https."
            )
        if parsed.hostname is None:
            raise SurfaceSessionValidationError(
                "Development server URL must include a hostname."
            )
        if not _is_local_hostname(parsed.hostname):
            raise SurfaceSessionValidationError(
                "Development server URL must point to localhost."
            )
        if parsed.port is None:
            raise SurfaceSessionValidationError(
                "Development server URL must include an explicit port."
            )

        return normalized.rstrip("/")


def _is_local_hostname(hostname: str) -> bool:
    """Return whether one hostname is loopback-only.

    Args:
        hostname: Parsed hostname string.

    Returns:
        ``True`` when the hostname is ``localhost`` or a loopback IP address.
    """
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False
