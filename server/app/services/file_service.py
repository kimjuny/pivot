"""Reusable service for validating, storing, attaching, and pruning files."""

from __future__ import annotations

import base64
import io
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.file import FileAsset
from app.schemas.file import FileAssetListItem
from app.services.workspace_service import workspace_root
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session as DBSession, col, select

logger = logging.getLogger(__name__)

_ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


@dataclass(frozen=True, slots=True)
class VerifiedImageUpload:
    """Validated image metadata derived from Pillow inspection."""

    file_bytes: bytes
    format: str
    extension: str
    mime_type: str
    size_bytes: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class PreparedImageAttachment:
    """Prepared multimodal payload and metadata for one stored image."""

    file_id: str
    original_name: str
    mime_type: str
    width: int
    height: int
    content_block: dict[str, Any]


class FileService:
    """Provide generic file lifecycle operations for user workspaces."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session."""
        self.db = db
        self.settings = get_settings()

    @staticmethod
    def user_files_dir(username: str) -> Path:
        """Return the workspace directory used for raw user files."""
        files_dir = workspace_root() / username / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        return files_dir

    def verify_image_upload(
        self,
        filename: str,
        file_bytes: bytes,
    ) -> VerifiedImageUpload:
        """Validate the uploaded image with Pillow and config-driven limits.

        Args:
            filename: Original filename received from client.
            file_bytes: Raw uploaded bytes.

        Returns:
            Verified image metadata for storage.

        Raises:
            ValueError: If the upload is empty, too large, or not a supported image.
        """
        size_bytes = len(file_bytes)
        if size_bytes == 0:
            raise ValueError("Uploaded image is empty.")

        max_filesize = int(self.settings.MAX_FILESIZE)
        if size_bytes > max_filesize:
            raise ValueError(
                f"Image exceeds the {max_filesize // (1024 * 1024)}MB upload limit."
            )

        try:
            with Image.open(io.BytesIO(file_bytes)) as image:
                image.verify()
            with Image.open(io.BytesIO(file_bytes)) as inspected_image:
                image_format = (inspected_image.format or "").upper()
                width, height = inspected_image.size
        except (OSError, UnidentifiedImageError) as err:
            raise ValueError("Uploaded file is not a valid image.") from err

        format_config = _ALLOWED_FORMATS.get(image_format)
        if format_config is None:
            allowed = ", ".join(ext.lower() for ext in ["JPG", "JPEG", "PNG", "WEBP"])
            raise ValueError(f"Unsupported image format. Allowed formats: {allowed}.")

        extension, mime_type = format_config
        original_name = filename.strip()
        if not original_name:
            original_name = f"upload.{extension}"

        return VerifiedImageUpload(
            file_bytes=file_bytes,
            format=image_format,
            extension=extension,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
        )

    def store_uploaded_image(
        self,
        username: str,
        filename: str,
        source: str,
        file_bytes: bytes,
    ) -> FileAsset:
        """Verify and persist an uploaded image on disk and in database."""
        verified = self.verify_image_upload(filename, file_bytes)
        now = datetime.now(timezone.utc)
        file_id = str(uuid.uuid4())
        stored_name = f"{file_id}.{verified.extension}"
        storage_path = self.user_files_dir(username) / stored_name
        storage_path.write_bytes(verified.file_bytes)

        file_asset = FileAsset(
            file_id=file_id,
            user=username,
            source=source,
            original_name=filename or stored_name,
            stored_name=stored_name,
            storage_path=str(storage_path),
            mime_type=verified.mime_type,
            format=verified.format,
            extension=verified.extension,
            size_bytes=verified.size_bytes,
            width=verified.width,
            height=verified.height,
            expires_at=now + timedelta(minutes=int(self.settings.FILE_EXPIRE_MINUTES)),
            created_at=now,
            updated_at=now,
        )
        self.db.add(file_asset)
        self.db.commit()
        self.db.refresh(file_asset)
        return file_asset

    def get_file_for_user(self, file_id: str, username: str) -> FileAsset | None:
        """Return a file only when it belongs to the current user."""
        stmt = select(FileAsset).where(
            FileAsset.file_id == file_id,
            FileAsset.user == username,
        )
        return self.db.exec(stmt).first()

    def get_file_by_id(self, file_id: str) -> FileAsset | None:
        """Return a file by public ID without applying ownership rules."""
        stmt = select(FileAsset).where(FileAsset.file_id == file_id)
        return self.db.exec(stmt).first()

    def delete_file_for_user(self, file_id: str, username: str) -> bool:
        """Delete one uploaded file owned by the current user.

        Why: queue-level removal should be reversible only before the file is
        attached to a conversation; deleting attached files would corrupt history.
        """
        file_asset = self.get_file_for_user(file_id, username)
        if file_asset is None:
            return False
        if file_asset.session_id is not None or file_asset.task_id is not None:
            raise ValueError("Files already used in a conversation cannot be removed.")

        self._delete_asset(file_asset)
        self.db.commit()
        return True

    def attach_files_to_task(
        self,
        file_ids: list[str],
        username: str,
        session_id: str | None,
        task_id: str,
    ) -> list[FileAsset]:
        """Bind uploaded files to the current task right before send."""
        attached_files: list[FileAsset] = []
        seen_ids: set[str] = set()
        now = datetime.now(timezone.utc)

        for file_id in file_ids:
            normalized_id = file_id.strip()
            if not normalized_id or normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)

            file_asset = self.get_file_for_user(normalized_id, username)
            if file_asset is None:
                raise ValueError(f"Image file '{normalized_id}' does not exist.")

            if file_asset.task_id is not None and file_asset.task_id != task_id:
                raise ValueError(
                    f"Image file '{normalized_id}' is already attached elsewhere."
                )

            file_asset.session_id = session_id
            file_asset.task_id = task_id
            file_asset.updated_at = now
            self.db.add(file_asset)
            attached_files.append(file_asset)

        if attached_files:
            self.db.commit()
            for file_asset in attached_files:
                self.db.refresh(file_asset)
        return attached_files

    def preprocess_files(
        self,
        files: list[FileAsset],
    ) -> list[PreparedImageAttachment]:
        """Convert stored files into neutral multimodal blocks for LLM calls."""
        prepared: list[PreparedImageAttachment] = []
        for file_asset in files:
            file_bytes = Path(file_asset.storage_path).read_bytes()
            encoded_data = base64.b64encode(file_bytes).decode("ascii")
            prepared.append(
                PreparedImageAttachment(
                    file_id=file_asset.file_id,
                    original_name=file_asset.original_name,
                    mime_type=file_asset.mime_type,
                    width=file_asset.width,
                    height=file_asset.height,
                    content_block={
                        "type": "image",
                        "media_type": file_asset.mime_type,
                        "data": encoded_data,
                    },
                )
            )
        return prepared

    def build_history_items(
        self,
        task_ids: list[str],
    ) -> dict[str, list[FileAssetListItem]]:
        """Return task-grouped file metadata for session history payloads."""
        normalized_ids = [task_id for task_id in task_ids if task_id]
        if not normalized_ids:
            return {}

        stmt = (
            select(FileAsset)
            .where(col(FileAsset.task_id).in_(normalized_ids))
            .order_by(col(FileAsset.created_at).asc())
        )
        items = list(self.db.exec(stmt).all())
        grouped: dict[str, list[FileAssetListItem]] = {}
        for file_asset in items:
            if file_asset.task_id is None:
                continue
            grouped.setdefault(file_asset.task_id, []).append(
                FileAssetListItem(
                    file_id=file_asset.file_id,
                    original_name=file_asset.original_name,
                    mime_type=file_asset.mime_type,
                    format=file_asset.format,
                    extension=file_asset.extension,
                    size_bytes=file_asset.size_bytes,
                    width=file_asset.width,
                    height=file_asset.height,
                    source=file_asset.source,
                    created_at=file_asset.created_at.replace(
                        tzinfo=timezone.utc
                    ).isoformat(),
                )
            )
        return grouped

    def clear_files_by_session_id(self, session_id: str) -> int:
        """Delete every stored file attached to a session."""
        stmt = select(FileAsset).where(FileAsset.session_id == session_id)
        files = list(self.db.exec(stmt).all())
        for file_asset in files:
            self._delete_asset(file_asset, commit=False)
        self.db.commit()
        return len(files)

    def prune_expired_unused_files(self) -> int:
        """Delete uploaded files that were never attached to a session."""
        now = datetime.now(timezone.utc)
        stmt = select(FileAsset).where(
            FileAsset.session_id.is_(None),
            FileAsset.expires_at < now,
        )
        expired_files = list(self.db.exec(stmt).all())
        for file_asset in expired_files:
            self._delete_asset(file_asset, commit=False)
        self.db.commit()
        return len(expired_files)

    def _delete_asset(self, file_asset: FileAsset, commit: bool = False) -> None:
        """Delete both structured metadata and raw file safely."""
        self._safe_unlink(Path(file_asset.storage_path))
        self.db.delete(file_asset)
        if commit:
            self.db.commit()

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        """Delete a stored file only when it lives under the workspace root.

        Why: session-based cleanup deletes by database metadata, so we guard the
        filesystem path to avoid ever unlinking arbitrary user-supplied paths.
        """
        resolved_path = path.resolve()
        workspace_path = workspace_root().resolve()
        if not resolved_path.is_relative_to(workspace_path):
            logger.warning("Skip unsafe file deletion outside workspace: %s", path)
            return
        try:
            resolved_path.unlink(missing_ok=True)
        except OSError as err:
            logger.warning("Failed to delete file %s: %s", resolved_path, err)
