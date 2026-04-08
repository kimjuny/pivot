"""Reusable persistence service for assistant-generated live file references."""

from __future__ import annotations

import mimetypes
import uuid
from datetime import UTC
from pathlib import Path

from app.models.session import Session as SessionModel
from app.models.task_attachment import TaskAttachment
from app.schemas.task_attachment import TaskAttachmentListItem
from app.services.workspace_runtime_file_service import WorkspaceRuntimeFileService
from app.services.workspace_service import WorkspaceService
from app.services.workspace_storage_service import WorkspaceStorageService
from sqlmodel import Session as DBSession, col, select

_MAX_ATTACHMENTS_PER_ANSWER = 8
_TEXT_EXTENSIONS = {
    "bat",
    "c",
    "cc",
    "cfg",
    "conf",
    "cpp",
    "css",
    "csv",
    "env",
    "go",
    "h",
    "hpp",
    "htm",
    "html",
    "ini",
    "java",
    "js",
    "json",
    "jsonl",
    "jsx",
    "log",
    "lua",
    "md",
    "markdown",
    "py",
    "rb",
    "rs",
    "scss",
    "sh",
    "sql",
    "svg",
    "text",
    "toml",
    "ts",
    "tsx",
    "txt",
    "xml",
    "yaml",
    "yml",
    "zsh",
}
_TEXT_FILENAMES = {"dockerfile", "makefile", ".env"}
_MARKDOWN_MIME_TYPES = {"text/markdown", "text/x-markdown"}
_TEXT_MIME_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/json",
    "application/sql",
    "application/toml",
    "application/x-httpd-php",
    "application/x-python-code",
    "application/x-sh",
    "application/x-shellscript",
    "application/x-yaml",
}


class TaskAttachmentService:
    """Persist live workspace file references returned by assistant answers."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session."""
        self.db = db

    def create_from_answer_paths(
        self,
        *,
        username: str,
        task_id: str,
        session_id: str | None,
        paths: list[str],
    ) -> list[TaskAttachment]:
        """Validate sandbox paths, resolve live files, and persist metadata.

        Args:
            username: Authenticated owner username.
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
        if session_id is None:
            return []

        session_row = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == session_id)
        ).first()
        if session_row is None or session_row.workspace_id is None:
            return []

        workspace = WorkspaceService(self.db).get_workspace(session_row.workspace_id)
        if workspace is None:
            return []

        mount_spec = WorkspaceStorageService().build_mount_spec(workspace)
        exported_files = WorkspaceRuntimeFileService().export_files(
            username=username,
            mount_spec=mount_spec,
            sandbox_paths=normalized_paths,
        )

        created: list[TaskAttachment] = []
        seen_relative_paths: set[str] = set()

        for exported_file in exported_files:
            sandbox_path = exported_file.sandbox_path
            workspace_relative_path = exported_file.workspace_relative_path
            if workspace_relative_path in seen_relative_paths:
                continue
            seen_relative_paths.add(workspace_relative_path)

            detected = self._detect_metadata(exported_file.display_name)
            attachment_id = str(uuid.uuid4())

            attachment = TaskAttachment(
                attachment_id=attachment_id,
                task_id=task_id,
                session_id=session_id,
                agent_id=session_row.agent_id,
                user=username,
                display_name=exported_file.display_name,
                original_name=exported_file.display_name,
                mime_type=str(detected["mime_type"]),
                extension=str(detected["extension"]),
                size_bytes=len(exported_file.content_bytes),
                render_kind=str(detected["render_kind"]),
                sandbox_path=sandbox_path,
                workspace_relative_path=workspace_relative_path,
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

    def read_attachment_bytes(self, attachment: TaskAttachment) -> bytes:
        """Return the current workspace bytes for one live attachment reference."""
        mount_spec = self._build_mount_spec_for_attachment(attachment)
        exported_files = WorkspaceRuntimeFileService().export_files(
            username=attachment.user,
            mount_spec=mount_spec,
            sandbox_paths=[attachment.sandbox_path],
        )
        if not exported_files:
            raise FileNotFoundError(attachment.sandbox_path)
        return exported_files[0].content_bytes

    def delete_by_task_id(self, task_id: str) -> int:
        """Delete all persisted attachment references belonging to one task."""
        stmt = select(TaskAttachment).where(TaskAttachment.task_id == task_id)
        rows = list(self.db.exec(stmt).all())
        for row in rows:
            self._delete_attachment(row, commit=False)
        if rows:
            self.db.commit()
        return len(rows)

    def delete_by_session_id(self, session_id: str) -> int:
        """Delete all persisted attachment references belonging to one session."""
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
        """Serialize persisted live file references into the public event/list shape."""
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

    def _detect_metadata(self, filename: str) -> dict[str, str]:
        """Infer stable MIME, extension, and render metadata for one file."""
        candidate = Path(filename)
        extension = candidate.suffix.lower().removeprefix(".")
        normalized_filename = candidate.name.lower()
        guessed_mime_type, _ = mimetypes.guess_type(candidate.name)
        mime_type = guessed_mime_type or "application/octet-stream"

        if extension in {"md", "markdown"} or mime_type in _MARKDOWN_MIME_TYPES:
            render_kind = "markdown"
            mime_type = "text/markdown"
        elif extension == "pdf" or mime_type == "application/pdf":
            render_kind = "pdf"
            mime_type = "application/pdf"
        elif mime_type.startswith("image/"):
            render_kind = "image"
        elif (
            extension in _TEXT_EXTENSIONS
            or normalized_filename in _TEXT_FILENAMES
            or mime_type.startswith("text/")
            or mime_type in _TEXT_MIME_TYPES
        ):
            render_kind = "text"
        else:
            render_kind = "download"

        return {
            "extension": extension or candidate.suffix.lower().removeprefix("."),
            "mime_type": mime_type,
            "render_kind": render_kind,
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
        """Delete one persisted attachment row."""
        self.db.delete(attachment)
        if commit:
            self.db.commit()

    def _build_mount_spec_for_attachment(
        self,
        attachment: TaskAttachment,
    ):
        """Resolve the workspace mount spec for one live attachment reference."""
        if attachment.session_id is None:
            raise FileNotFoundError("Task attachment is missing session context.")

        session_row = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == attachment.session_id)
        ).first()
        if session_row is None or session_row.workspace_id is None:
            raise FileNotFoundError("Task attachment workspace is unavailable.")

        workspace = WorkspaceService(self.db).get_workspace(session_row.workspace_id)
        if workspace is None:
            raise FileNotFoundError("Task attachment workspace is unavailable.")
        return WorkspaceStorageService().build_mount_spec(workspace)
