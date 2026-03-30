"""Reusable persistence service for assistant-generated task attachments."""

from __future__ import annotations

import logging
import mimetypes
import shutil
import uuid
from datetime import UTC
from pathlib import Path

from app.models.task_attachment import TaskAttachment
from app.schemas.task_attachment import TaskAttachmentListItem
from app.services.workspace_service import ensure_agent_workspace, workspace_root
from sqlmodel import Session as DBSession, col, select

logger = logging.getLogger(__name__)

_MAX_ATTACHMENTS_PER_ANSWER = 8
_TEXT_EXTENSIONS = {"md", "markdown", "txt", "text"}
_MARKDOWN_MIME_TYPES = {"text/markdown", "text/x-markdown"}


class TaskAttachmentService:
    """Persist immutable snapshots of files returned by assistant answers."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session."""
        self.db = db

    def create_from_answer_paths(
        self,
        *,
        username: str,
        agent_id: int,
        task_id: str,
        session_id: str | None,
        paths: list[str],
    ) -> list[TaskAttachment]:
        """Validate sandbox paths, snapshot files, and persist metadata.

        Args:
            username: Authenticated owner username.
            agent_id: Owning agent identifier.
            task_id: Owning task UUID.
            session_id: Owning session UUID, if present.
            paths: Sandbox-local file paths declared by the model.

        Returns:
            Persisted attachment rows ordered by the declared path list.
        """
        self.delete_by_task_id(task_id)

        normalized_paths = self._normalize_declared_paths(paths)
        if not normalized_paths:
            return []

        workspace_dir = ensure_agent_workspace(username, agent_id).resolve()
        attachments_dir = (
            workspace_root() / username / "task_attachments" / task_id
        ).resolve()
        attachments_dir.mkdir(parents=True, exist_ok=True)

        created: list[TaskAttachment] = []
        seen_relative_paths: set[str] = set()

        for sandbox_path in normalized_paths:
            host_path, workspace_relative_path = self._resolve_workspace_file(
                workspace_dir,
                sandbox_path,
            )
            if host_path is None or workspace_relative_path is None:
                continue

            if workspace_relative_path in seen_relative_paths:
                continue
            seen_relative_paths.add(workspace_relative_path)

            detected = self._detect_metadata(host_path)
            attachment_id = str(uuid.uuid4())
            snapshot_path = attachments_dir / f"{attachment_id}{detected['suffix']}"
            shutil.copy2(host_path, snapshot_path)

            attachment = TaskAttachment(
                attachment_id=attachment_id,
                task_id=task_id,
                session_id=session_id,
                agent_id=agent_id,
                user=username,
                display_name=host_path.name,
                original_name=host_path.name,
                mime_type=str(detected["mime_type"]),
                extension=str(detected["extension"]),
                size_bytes=int(host_path.stat().st_size),
                render_kind=str(detected["render_kind"]),
                sandbox_path=sandbox_path,
                workspace_relative_path=workspace_relative_path,
                storage_path=str(snapshot_path),
            )
            self.db.add(attachment)
            created.append(attachment)

        self.db.commit()
        for attachment in created:
            self.db.refresh(attachment)
        return created

    def list_by_task_ids(
        self,
        task_ids: list[str],
    ) -> dict[str, list[TaskAttachmentListItem]]:
        """Return persisted task attachments grouped by task ID."""
        normalized_task_ids = [task_id for task_id in task_ids if task_id]
        if not normalized_task_ids:
            return {}

        stmt = (
            select(TaskAttachment)
            .where(col(TaskAttachment.task_id).in_(normalized_task_ids))
            .order_by(col(TaskAttachment.created_at).asc())
        )
        rows = list(self.db.exec(stmt).all())
        grouped: dict[str, list[TaskAttachmentListItem]] = {}
        for row in rows:
            grouped.setdefault(row.task_id, []).append(self._to_list_item(row))
        return grouped

    def get_attachment_for_user(
        self,
        attachment_id: str,
        username: str,
    ) -> TaskAttachment | None:
        """Return an attachment only when it belongs to the authenticated user."""
        stmt = select(TaskAttachment).where(
            TaskAttachment.attachment_id == attachment_id,
            TaskAttachment.user == username,
        )
        return self.db.exec(stmt).first()

    def delete_by_task_id(self, task_id: str) -> int:
        """Delete all attachment snapshots belonging to one task."""
        stmt = select(TaskAttachment).where(TaskAttachment.task_id == task_id)
        rows = list(self.db.exec(stmt).all())
        for row in rows:
            self._delete_attachment(row, commit=False)
        if rows:
            self.db.commit()
        return len(rows)

    def delete_by_session_id(self, session_id: str) -> int:
        """Delete all attachment snapshots belonging to one session."""
        stmt = select(TaskAttachment).where(TaskAttachment.session_id == session_id)
        rows = list(self.db.exec(stmt).all())
        for row in rows:
            self._delete_attachment(row, commit=False)
        if rows:
            self.db.commit()
        return len(rows)

    @staticmethod
    def extract_declared_paths(answer_output: dict[str, object]) -> list[str]:
        """Normalize model-declared answer attachment paths from either spelling."""
        raw_value = answer_output.get("attachments")
        if raw_value is None:
            raw_value = answer_output.get("attatchments")
        if not isinstance(raw_value, list):
            return []

        normalized: list[str] = []
        for item in raw_value:
            if isinstance(item, str):
                stripped = item.strip()
                if stripped:
                    normalized.append(stripped)
        return normalized

    def to_event_payload(
        self,
        attachments: list[TaskAttachment],
    ) -> list[dict[str, str | int]]:
        """Serialize persisted attachments into the public event/list shape."""
        return [self._to_list_item(item).model_dump() for item in attachments]

    def _normalize_declared_paths(self, paths: list[str]) -> list[str]:
        """Normalize declared sandbox paths while preserving order."""
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in paths[:_MAX_ATTACHMENTS_PER_ANSWER]:
            candidate = raw_path.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    def _resolve_workspace_file(
        self,
        workspace_dir: Path,
        sandbox_path: str,
    ) -> tuple[Path | None, str | None]:
        """Map a sandbox-local workspace path to a host-side file path."""
        candidate = Path(sandbox_path)
        if not candidate.is_absolute():
            logger.warning("Skip non-absolute task attachment path: %s", sandbox_path)
            return None, None

        if candidate == Path("/workspace"):
            logger.warning("Skip workspace root attachment path: %s", sandbox_path)
            return None, None

        try:
            workspace_relative_path = candidate.relative_to("/workspace")
        except ValueError:
            logger.warning(
                "Skip task attachment path outside /workspace: %s",
                sandbox_path,
            )
            return None, None

        host_path = (workspace_dir / workspace_relative_path).resolve()
        if not host_path.is_relative_to(workspace_dir):
            logger.warning(
                "Skip task attachment path escaping workspace: %s",
                sandbox_path,
            )
            return None, None
        if host_path.is_symlink():
            logger.warning("Skip symlink task attachment path: %s", sandbox_path)
            return None, None
        if not host_path.exists():
            logger.warning("Skip missing task attachment path: %s", sandbox_path)
            return None, None
        if not host_path.is_file():
            logger.warning("Skip non-file task attachment path: %s", sandbox_path)
            return None, None
        return host_path, workspace_relative_path.as_posix()

    def _detect_metadata(self, host_path: Path) -> dict[str, str]:
        """Infer stable MIME, extension, and render metadata for one file."""
        extension = host_path.suffix.lower().removeprefix(".")
        guessed_mime_type, _ = mimetypes.guess_type(host_path.name)
        mime_type = guessed_mime_type or "application/octet-stream"

        if extension in {"md", "markdown"} or mime_type in _MARKDOWN_MIME_TYPES:
            render_kind = "markdown"
            mime_type = "text/markdown"
        elif extension == "pdf" or mime_type == "application/pdf":
            render_kind = "pdf"
            mime_type = "application/pdf"
        elif mime_type.startswith("image/"):
            render_kind = "image"
        elif extension in _TEXT_EXTENSIONS or mime_type.startswith("text/"):
            render_kind = "text"
        else:
            render_kind = "download"

        suffix = host_path.suffix or (f".{extension}" if extension else "")
        return {
            "extension": extension or host_path.suffix.lower().removeprefix("."),
            "mime_type": mime_type,
            "render_kind": render_kind,
            "suffix": suffix,
        }

    def _to_list_item(self, row: TaskAttachment) -> TaskAttachmentListItem:
        """Serialize one model row into the public compact schema."""
        return TaskAttachmentListItem(
            attachment_id=row.attachment_id,
            display_name=row.display_name,
            original_name=row.original_name,
            mime_type=row.mime_type,
            extension=row.extension,
            size_bytes=row.size_bytes,
            render_kind=row.render_kind,
            workspace_relative_path=row.workspace_relative_path,
            created_at=row.created_at.replace(tzinfo=UTC).isoformat(),
        )

    def _delete_attachment(
        self,
        attachment: TaskAttachment,
        *,
        commit: bool,
    ) -> None:
        """Delete one persisted attachment row and its snapshot file."""
        snapshot_path = Path(attachment.storage_path)
        if snapshot_path.exists():
            self._safe_unlink(snapshot_path)
        self.db.delete(attachment)
        if commit:
            self.db.commit()

    def _safe_unlink(self, path: Path) -> None:
        """Delete a snapshot file only when it lives under the workspace root."""
        resolved_path = path.resolve()
        workspace_path = workspace_root().resolve()
        if not resolved_path.is_relative_to(workspace_path):
            logger.warning(
                "Skip unsafe task attachment deletion outside workspace: %s",
                path,
            )
            return
        resolved_path.unlink(missing_ok=True)
