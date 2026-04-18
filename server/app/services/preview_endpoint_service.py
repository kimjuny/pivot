"""Service layer for lightweight session-scoped web preview endpoints."""

from __future__ import annotations

import posixpath
import shlex
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

from app.services.sandbox_service import get_sandbox_service
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


class PreviewEndpointError(Exception):
    """Base error for preview endpoint failures."""


class PreviewEndpointNotFoundError(PreviewEndpointError):
    """Raised when a requested preview endpoint does not exist."""


class PreviewEndpointPermissionError(PreviewEndpointError):
    """Raised when a caller does not own a requested preview endpoint."""


class PreviewEndpointValidationError(PreviewEndpointError):
    """Raised when a requested preview endpoint is invalid."""


@dataclass(frozen=True)
class PreviewEndpointRecord:
    """In-memory preview endpoint metadata."""

    preview_id: str
    username: str
    agent_id: int
    session_id: str
    workspace_id: str
    title: str
    port: int
    path: str
    created_at: datetime
    cwd: str | None = None
    start_server: str | None = None
    allowed_skills: tuple[dict[str, str], ...] = ()


_PREVIEW_ENDPOINTS: dict[str, PreviewEndpointRecord] = {}
_PREVIEW_ENDPOINTS_LOCK = RLock()


class PreviewEndpointService:
    """Create and resolve session-scoped preview endpoints."""

    def __init__(self, db: DBSession) -> None:
        """Store the active database session."""
        self.db = db

    def create_preview_endpoint(
        self,
        *,
        username: str,
        session_id: str,
        port: int,
        path: str | None = None,
        title: str | None = None,
        cwd: str | None = None,
        start_server: str | None = None,
        skills: tuple[dict[str, str], ...] | list[dict[str, str]] | None = None,
    ) -> PreviewEndpointRecord:
        """Create or update one in-memory preview endpoint for an owned chat session."""
        normalized_port = self._normalize_port(port)
        normalized_path = self._normalize_path(path)
        normalized_cwd = self._normalize_workspace_cwd(cwd)
        normalized_start_server = self._normalize_start_server(start_server)
        normalized_skills = self._normalize_skills(skills)
        chat_session, workspace = self._resolve_owned_chat_session(
            username=username,
            session_id=session_id,
        )
        normalized_title = (
            title.strip()
            if isinstance(title, str) and title.strip()
            else f"localhost:{normalized_port}"
        )
        with _PREVIEW_ENDPOINTS_LOCK:
            existing_record = next(
                (
                    candidate
                    for candidate in _PREVIEW_ENDPOINTS.values()
                    if candidate.username == username
                    and candidate.session_id == chat_session.session_id
                    and candidate.port == normalized_port
                    and candidate.path == normalized_path
                ),
                None,
            )
            if existing_record is not None:
                record = PreviewEndpointRecord(
                    preview_id=existing_record.preview_id,
                    username=existing_record.username,
                    agent_id=existing_record.agent_id,
                    session_id=existing_record.session_id,
                    workspace_id=existing_record.workspace_id,
                    title=normalized_title,
                    port=existing_record.port,
                    path=existing_record.path,
                    created_at=existing_record.created_at,
                    cwd=normalized_cwd,
                    start_server=normalized_start_server,
                    allowed_skills=normalized_skills,
                )
                _PREVIEW_ENDPOINTS[record.preview_id] = record
                return record

            record = PreviewEndpointRecord(
                preview_id=str(uuid4()),
                username=username,
                agent_id=chat_session.agent_id,
                session_id=chat_session.session_id,
                workspace_id=workspace.workspace_id,
                title=normalized_title,
                port=normalized_port,
                path=normalized_path,
                created_at=datetime.now(UTC),
                cwd=normalized_cwd,
                start_server=normalized_start_server,
                allowed_skills=normalized_skills,
            )
            _PREVIEW_ENDPOINTS[record.preview_id] = record
        return record

    def connect_preview_endpoint(
        self,
        *,
        preview_id: str,
        username: str,
        timeout_seconds: int = 60,
    ) -> PreviewEndpointRecord:
        """Ensure one preview runtime is reachable, recreating it from recipe when needed."""
        record = self.get_preview_endpoint(preview_id=preview_id, username=username)
        if record.start_server is None or record.cwd is None:
            raise PreviewEndpointValidationError(
                "This preview cannot be reconnected because no start_server recipe was recorded."
            )

        workspace = WorkspaceService(self.db).get_workspace(record.workspace_id)
        if workspace is None:
            raise PreviewEndpointNotFoundError("Workspace not found.")
        if workspace.user != username:
            raise PreviewEndpointPermissionError("Workspace is not owned by the caller.")

        workspace_backend_path = WorkspaceService(self.db).get_workspace_backend_path(
            workspace
        )
        if self._is_preview_reachable(
            record=record,
            workspace_backend_path=workspace_backend_path,
            timeout_seconds=min(timeout_seconds, 10),
        ):
            return record

        sandbox_service = get_sandbox_service()
        sandbox_service.create(
            username=record.username,
            workspace_id=record.workspace_id,
            workspace_backend_path=workspace_backend_path,
            skills=list(record.allowed_skills),
            timeout_seconds=timeout_seconds,
        )

        launch_result = sandbox_service.exec(
            username=record.username,
            workspace_id=record.workspace_id,
            workspace_backend_path=workspace_backend_path,
            cmd=["bash", "-lc", self._build_launch_command(record=record)],
            skills=list(record.allowed_skills),
            timeout_seconds=timeout_seconds,
        )
        if launch_result.exit_code != 0:
            message = launch_result.stderr.strip() or launch_result.stdout.strip()
            raise PreviewEndpointValidationError(
                f"Preview startup command failed (exit={launch_result.exit_code}): {message}"
            )

        self._wait_until_preview_reachable(
            record=record,
            workspace_backend_path=workspace_backend_path,
            timeout_seconds=timeout_seconds,
        )
        return record

    def get_preview_endpoint(
        self,
        *,
        preview_id: str,
        username: str,
    ) -> PreviewEndpointRecord:
        """Return one owned preview endpoint."""
        with _PREVIEW_ENDPOINTS_LOCK:
            record = _PREVIEW_ENDPOINTS.get(preview_id)
        if record is None:
            raise PreviewEndpointNotFoundError("Preview endpoint not found.")
        if record.username != username:
            raise PreviewEndpointPermissionError(
                "Preview endpoint is not owned by the caller."
            )
        return record

    def build_proxy_url(self, *, record: PreviewEndpointRecord) -> str:
        """Return the host-facing proxy URL for one preview endpoint."""
        base_path = f"/api/chat-previews/{record.preview_id}/proxy"
        if record.path == "/":
            return f"{base_path}/"
        return f"{base_path}/{record.path.lstrip('/')}"

    def list_preview_endpoints(
        self,
        *,
        username: str,
        session_id: str,
    ) -> list[PreviewEndpointRecord]:
        """Return all owned preview endpoints for one chat session."""
        chat_session, _workspace = self._resolve_owned_chat_session(
            username=username,
            session_id=session_id,
        )
        with _PREVIEW_ENDPOINTS_LOCK:
            records = [
                record
                for record in _PREVIEW_ENDPOINTS.values()
                if record.username == username
                and record.session_id == chat_session.session_id
            ]
        return sorted(records, key=lambda record: record.created_at)

    @staticmethod
    def clear_preview_endpoints() -> None:
        """Clear all in-memory preview endpoints for isolated tests."""
        with _PREVIEW_ENDPOINTS_LOCK:
            _PREVIEW_ENDPOINTS.clear()

    def _resolve_owned_chat_session(
        self,
        *,
        username: str,
        session_id: str,
    ):
        """Resolve one owned chat session plus its workspace."""
        chat_session = SessionService(self.db).get_session(session_id)
        if chat_session is None:
            raise PreviewEndpointNotFoundError("Chat session not found.")
        if chat_session.user != username:
            raise PreviewEndpointPermissionError(
                "Chat session is not owned by the caller."
            )
        if chat_session.workspace_id is None:
            raise PreviewEndpointValidationError(
                "Chat session does not have an attached workspace."
            )

        workspace = WorkspaceService(self.db).get_workspace(chat_session.workspace_id)
        if workspace is None:
            raise PreviewEndpointNotFoundError("Workspace not found.")
        if workspace.user != username:
            raise PreviewEndpointPermissionError(
                "Workspace is not owned by the caller."
            )
        return chat_session, workspace

    @staticmethod
    def _normalize_port(raw_port: int) -> int:
        """Validate one preview port."""
        if not isinstance(raw_port, int) or raw_port < 1 or raw_port > 65535:
            raise PreviewEndpointValidationError(
                "Preview port must be between 1 and 65535."
            )
        return raw_port

    @staticmethod
    def _normalize_path(raw_path: str | None) -> str:
        """Validate one preview request path."""
        normalized = raw_path.strip() if isinstance(raw_path, str) else ""
        if normalized == "":
            return "/"
        parsed = urlparse(normalized)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise PreviewEndpointValidationError(
                "Preview path must be a relative HTTP path without query parameters."
            )
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        return path

    @staticmethod
    def _normalize_skills(
        raw_skills: tuple[dict[str, str], ...] | list[dict[str, str]] | None,
    ) -> tuple[dict[str, str], ...]:
        """Return one stable, sanitized preview skill snapshot."""
        if not raw_skills:
            return ()

        normalized: list[dict[str, str]] = []
        seen_names: set[str] = set()
        for item in raw_skills:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("name")
            raw_location = item.get("location")
            if not isinstance(raw_name, str) or not isinstance(raw_location, str):
                continue
            skill_name = raw_name.strip()
            location = raw_location.strip()
            if not skill_name or not location or skill_name in seen_names:
                continue
            seen_names.add(skill_name)
            normalized.append(
                {
                    "name": skill_name,
                    "location": location,
                }
            )
        return tuple(normalized)

    @staticmethod
    def _normalize_workspace_cwd(raw_cwd: str | None) -> str | None:
        """Return one normalized workspace cwd for preview launch recipes."""
        if raw_cwd is None:
            return None
        normalized = raw_cwd.strip()
        if normalized == "":
            return "/workspace"
        if normalized.startswith("/"):
            full = posixpath.normpath(normalized)
        else:
            full = posixpath.normpath(posixpath.join("/workspace", normalized))
        if full == "/workspace" or full.startswith("/workspace/"):
            return full
        raise PreviewEndpointValidationError("Preview cwd must stay within /workspace.")

    @staticmethod
    def _normalize_start_server(raw_start_server: str | None) -> str | None:
        """Return one sanitized start_server command."""
        if raw_start_server is None:
            return None
        normalized = raw_start_server.strip()
        if normalized == "":
            return None
        return normalized

    @staticmethod
    def _build_launch_command(*, record: PreviewEndpointRecord) -> str:
        """Return one bash command that replays a preview launch recipe."""
        if record.cwd is None or record.start_server is None:
            raise PreviewEndpointValidationError(
                "Preview launch recipe is incomplete."
            )
        return f"cd {shlex.quote(record.cwd)} && {record.start_server}"

    def _wait_until_preview_reachable(
        self,
        *,
        record: PreviewEndpointRecord,
        workspace_backend_path: str,
        timeout_seconds: int,
    ) -> None:
        """Poll one preview target until it becomes reachable."""
        deadline = time.monotonic() + max(timeout_seconds, 1)
        while time.monotonic() < deadline:
            if self._is_preview_reachable(
                record=record,
                workspace_backend_path=workspace_backend_path,
                timeout_seconds=min(timeout_seconds, 10),
            ):
                return
            time.sleep(0.5)
        raise PreviewEndpointValidationError(
            f"Preview server on port {record.port} did not become reachable before timeout."
        )

    @staticmethod
    def _is_preview_reachable(
        *,
        record: PreviewEndpointRecord,
        workspace_backend_path: str,
        timeout_seconds: int,
    ) -> bool:
        """Probe one preview target through sandbox-manager."""
        try:
            get_sandbox_service().proxy_http(
                username=record.username,
                workspace_id=record.workspace_id,
                workspace_backend_path=workspace_backend_path,
                skills=list(record.allowed_skills),
                port=record.port,
                path=record.path,
                method="GET",
                query_string="",
                headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"},
                body=None,
                timeout_seconds=timeout_seconds,
                require_existing=True,
                allow_recreate=False,
            )
        except RuntimeError:
            return False
        return True
