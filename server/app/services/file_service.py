"""Reusable service for validating, storing, attaching, and pruning files."""

from __future__ import annotations

import base64
import io
import logging
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.file import FileAsset
from app.schemas.file import FileAssetListItem
from app.services.workspace_service import workspace_root
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session as DBSession, col, select

logger = logging.getLogger(__name__)

_ALLOWED_IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}

_ALLOWED_DOCUMENT_TYPES: dict[str, tuple[str, str]] = {
    "pdf": ("PDF", "application/pdf"),
    "docx": (
        "DOCX",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "pptx": (
        "PPTX",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    "xlsx": (
        "XLSX",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "md": ("MARKDOWN", "text/markdown"),
    "markdown": ("MARKDOWN", "text/markdown"),
}

_LEGACY_OFFICE_REPLACEMENTS: dict[str, str] = {
    "doc": "docx",
    "ppt": "pptx",
    "xls": "xlsx",
}

_TEXT_LIKE_DOCUMENT_EXTENSIONS = {"md", "markdown"}
_TEXT_ENCODINGS = ("utf-8", "utf-8-sig", "utf-16", "gb18030")


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
class VerifiedDocumentUpload:
    """Validated document metadata derived from Docling inspection."""

    file_bytes: bytes
    format: str
    extension: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    can_extract_text: bool
    suspected_scanned: bool
    text_encoding: str | None
    markdown_text: str


@dataclass(frozen=True, slots=True)
class PdfTextLayerProbe:
    """Fast PDF text-layer probe used to reject OCR-only files early."""

    page_count: int
    sampled_pages: int
    extracted_char_count: int
    non_empty_pages: int
    printable_ratio: float

    @property
    def requires_ocr(self) -> bool:
        """Return whether the sampled PDF pages appear to lack a usable text layer."""
        if self.page_count == 0:
            return True
        return not (
            (self.extracted_char_count >= 400 and self.non_empty_pages >= 1)
            or (self.extracted_char_count >= 200 and self.printable_ratio >= 0.7)
        )


@dataclass(frozen=True, slots=True)
class PreparedFileAttachment:
    """Prepared multimodal payload and metadata for one stored file."""

    file_id: str
    kind: str
    original_name: str
    mime_type: str
    width: int
    height: int
    content_blocks: list[dict[str, Any]]


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

        max_image_size = int(self.settings.MAX_IMAGE_SIZE)
        if size_bytes > max_image_size:
            raise ValueError(
                f"Image exceeds the {max_image_size // (1024 * 1024)}MB upload limit."
            )

        try:
            with Image.open(io.BytesIO(file_bytes)) as image:
                image.verify()
            with Image.open(io.BytesIO(file_bytes)) as inspected_image:
                image_format = (inspected_image.format or "").upper()
                width, height = inspected_image.size
        except (OSError, UnidentifiedImageError) as err:
            raise ValueError("Uploaded file is not a valid image.") from err

        format_config = _ALLOWED_IMAGE_FORMATS.get(image_format)
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

    def verify_document_upload(
        self,
        filename: str,
        file_bytes: bytes,
    ) -> VerifiedDocumentUpload:
        """Validate a document upload and precompute its markdown form.

        Args:
            filename: Original filename received from client.
            file_bytes: Raw uploaded bytes.

        Returns:
            Verified document metadata and cached markdown content.

        Raises:
            ValueError: If the upload is empty, too large, unsupported, or unreadable.
        """
        size_bytes = len(file_bytes)
        if size_bytes == 0:
            raise ValueError("Uploaded file is empty.")

        max_file_size = int(self.settings.MAX_FILE_SIZE)
        if size_bytes > max_file_size:
            raise ValueError(
                f"File exceeds the {max_file_size // (1024 * 1024)}MB upload limit."
            )

        extension = self._extract_extension(filename)
        replacement = _LEGACY_OFFICE_REPLACEMENTS.get(extension)
        if replacement is not None:
            raise ValueError(
                "Legacy Office formats are not supported. "
                f"Please upload '.{replacement}' instead."
            )

        format_config = _ALLOWED_DOCUMENT_TYPES.get(extension)
        if format_config is None:
            allowed = ", ".join(
                f".{ext}" for ext in sorted(_ALLOWED_DOCUMENT_TYPES.keys())
            )
            raise ValueError(f"Unsupported file format. Allowed formats: {allowed}.")

        format_name, mime_type = format_config
        text_encoding = self._detect_text_encoding(file_bytes, extension)

        with tempfile.NamedTemporaryFile(
            suffix=f".{extension}", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(file_bytes)

        try:
            if extension == "pdf":
                self._ensure_pdf_has_embedded_text_layer(temp_path)
            markdown_text, page_count = self._convert_document_with_docling(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

        normalized_markdown = markdown_text.strip()
        can_extract_text = bool(normalized_markdown)
        suspected_scanned = extension == "pdf" and not can_extract_text

        return VerifiedDocumentUpload(
            file_bytes=file_bytes,
            format=format_name,
            extension=extension,
            mime_type=mime_type,
            size_bytes=size_bytes,
            page_count=page_count,
            can_extract_text=can_extract_text,
            suspected_scanned=suspected_scanned,
            text_encoding=text_encoding,
            markdown_text=markdown_text,
        )

    def store_uploaded_file(
        self,
        username: str,
        filename: str,
        source: str,
        file_bytes: bytes,
    ) -> FileAsset:
        """Verify and persist an uploaded file on disk and in database."""
        normalized_name = self._normalize_original_name(filename)
        upload_kind = self._infer_upload_kind(normalized_name)
        now = datetime.now(UTC)
        file_id = str(uuid.uuid4())

        if upload_kind == "document":
            verified_document = self.verify_document_upload(normalized_name, file_bytes)
            stored_name = f"{file_id}.{verified_document.extension}"
            storage_path = self.user_files_dir(username) / stored_name
            markdown_path = storage_path.with_suffix(".extracted.md")
            try:
                storage_path.write_bytes(verified_document.file_bytes)
                markdown_path.write_text(
                    verified_document.markdown_text,
                    encoding="utf-8",
                )
            except OSError as err:
                self._safe_unlink(storage_path)
                self._safe_unlink(markdown_path)
                raise ValueError("Failed to persist uploaded file.") from err

            file_asset = FileAsset(
                file_id=file_id,
                user=username,
                source=source,
                original_name=normalized_name,
                stored_name=stored_name,
                storage_path=str(storage_path),
                kind="document",
                mime_type=verified_document.mime_type,
                format=verified_document.format,
                extension=verified_document.extension,
                size_bytes=verified_document.size_bytes,
                width=0,
                height=0,
                page_count=verified_document.page_count,
                markdown_path=str(markdown_path),
                can_extract_text=verified_document.can_extract_text,
                suspected_scanned=verified_document.suspected_scanned,
                text_encoding=verified_document.text_encoding,
                expires_at=now
                + timedelta(minutes=int(self.settings.FILE_EXPIRE_MINUTES)),
                created_at=now,
                updated_at=now,
            )
        else:
            verified_image = self.verify_image_upload(normalized_name, file_bytes)
            stored_name = f"{file_id}.{verified_image.extension}"
            storage_path = self.user_files_dir(username) / stored_name
            try:
                storage_path.write_bytes(verified_image.file_bytes)
            except OSError as err:
                self._safe_unlink(storage_path)
                raise ValueError("Failed to persist uploaded image.") from err

            file_asset = FileAsset(
                file_id=file_id,
                user=username,
                source=source,
                original_name=normalized_name,
                stored_name=stored_name,
                storage_path=str(storage_path),
                kind="image",
                mime_type=verified_image.mime_type,
                format=verified_image.format,
                extension=verified_image.extension,
                size_bytes=verified_image.size_bytes,
                width=verified_image.width,
                height=verified_image.height,
                page_count=None,
                markdown_path=None,
                can_extract_text=False,
                suspected_scanned=False,
                text_encoding=None,
                expires_at=now
                + timedelta(minutes=int(self.settings.FILE_EXPIRE_MINUTES)),
                created_at=now,
                updated_at=now,
            )

        self.db.add(file_asset)
        self.db.commit()
        self.db.refresh(file_asset)
        return file_asset

    def store_uploaded_image(
        self,
        username: str,
        filename: str,
        source: str,
        file_bytes: bytes,
    ) -> FileAsset:
        """Compatibility wrapper for image-only upload endpoints."""
        stored_file = self.store_uploaded_file(
            username=username,
            filename=filename,
            source=source,
            file_bytes=file_bytes,
        )
        if stored_file.kind != "image":
            raise ValueError("Uploaded file is not a supported image.")
        return stored_file

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
        now = datetime.now(UTC)

        for file_id in file_ids:
            normalized_id = file_id.strip()
            if not normalized_id or normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)

            file_asset = self.get_file_for_user(normalized_id, username)
            if file_asset is None:
                raise ValueError(f"File '{normalized_id}' does not exist.")

            if file_asset.task_id is not None and file_asset.task_id != task_id:
                raise ValueError(
                    f"File '{normalized_id}' is already attached elsewhere."
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
    ) -> list[PreparedFileAttachment]:
        """Convert stored files into neutral multimodal blocks for LLM calls."""
        prepared: list[PreparedFileAttachment] = []
        for file_asset in files:
            if file_asset.kind == "document":
                markdown_text = self._load_document_markdown(file_asset)
                prepared.append(
                    PreparedFileAttachment(
                        file_id=file_asset.file_id,
                        kind=file_asset.kind,
                        original_name=file_asset.original_name,
                        mime_type=file_asset.mime_type,
                        width=file_asset.width,
                        height=file_asset.height,
                        content_blocks=[
                            {
                                "type": "text",
                                "text": self._build_document_prompt_block(
                                    file_asset,
                                    markdown_text,
                                ),
                            }
                        ],
                    )
                )
                continue

            file_bytes = Path(file_asset.storage_path).read_bytes()
            encoded_data = base64.b64encode(file_bytes).decode("ascii")
            prepared.append(
                PreparedFileAttachment(
                    file_id=file_asset.file_id,
                    kind=file_asset.kind,
                    original_name=file_asset.original_name,
                    mime_type=file_asset.mime_type,
                    width=file_asset.width,
                    height=file_asset.height,
                    content_blocks=self._build_image_prompt_blocks(
                        file_asset,
                        encoded_data,
                    ),
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
                    kind=file_asset.kind,
                    original_name=file_asset.original_name,
                    mime_type=file_asset.mime_type,
                    format=file_asset.format,
                    extension=file_asset.extension,
                    size_bytes=file_asset.size_bytes,
                    width=file_asset.width,
                    height=file_asset.height,
                    page_count=file_asset.page_count,
                    can_extract_text=file_asset.can_extract_text,
                    suspected_scanned=file_asset.suspected_scanned,
                    text_encoding=file_asset.text_encoding,
                    source=file_asset.source,
                    created_at=file_asset.created_at.replace(tzinfo=UTC).isoformat(),
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
        now = datetime.now(UTC)
        stmt = select(FileAsset).where(
            col(FileAsset.session_id).is_(None),
            FileAsset.expires_at < now,
        )
        expired_files = list(self.db.exec(stmt).all())
        for file_asset in expired_files:
            self._delete_asset(file_asset, commit=False)
        self.db.commit()
        return len(expired_files)

    def _load_document_markdown(self, file_asset: FileAsset) -> str:
        """Load cached markdown, regenerating it when the cache is missing."""
        if file_asset.markdown_path:
            markdown_path = Path(file_asset.markdown_path)
            if markdown_path.exists():
                return markdown_path.read_text(encoding="utf-8")

        markdown_text, page_count = self._convert_document_with_docling(
            Path(file_asset.storage_path)
        )
        markdown_path = Path(file_asset.storage_path).with_suffix(".extracted.md")
        markdown_path.write_text(markdown_text, encoding="utf-8")
        file_asset.markdown_path = str(markdown_path)
        file_asset.page_count = page_count
        file_asset.can_extract_text = bool(markdown_text.strip())
        file_asset.suspected_scanned = (
            file_asset.extension == "pdf" and not file_asset.can_extract_text
        )
        file_asset.updated_at = datetime.now(UTC)
        self.db.add(file_asset)
        self.db.commit()
        self.db.refresh(file_asset)
        return markdown_text

    def _convert_document_with_docling(
        self,
        file_path: Path,
    ) -> tuple[str, int | None]:
        """Convert a supported document to markdown via Docling."""
        converter = self._build_docling_converter()
        try:
            conversion_result = converter.convert(file_path)
        except Exception as err:
            raise ValueError(
                "Uploaded file could not be understood by Docling."
            ) from err

        document = getattr(conversion_result, "document", None)
        if document is None:
            raise ValueError("Docling conversion returned no document output.")

        export_to_markdown = getattr(document, "export_to_markdown", None)
        if not callable(export_to_markdown):
            raise ValueError(
                "Docling document output does not support markdown export."
            )

        markdown_text = export_to_markdown()
        if not isinstance(markdown_text, str):
            markdown_text = str(markdown_text)
        return markdown_text, self._extract_page_count(conversion_result, document)

    @staticmethod
    def _build_docling_converter() -> Any:
        """Create a Docling converter for supported non-OCR document extraction."""
        try:
            document_converter_module = import_module("docling.document_converter")
        except ModuleNotFoundError as err:
            raise ValueError(
                "Docling is not available in the current backend environment. "
                "This project still runs on Python 3.10 and Pydantic v1, while "
                "Docling requires Python 3.11 and Pydantic v2."
            ) from err

        document_converter_cls = getattr(
            document_converter_module,
            "DocumentConverter",
            None,
        )
        if document_converter_cls is None:
            raise ValueError("Docling is installed but DocumentConverter is missing.")
        return document_converter_cls()

    def _ensure_pdf_has_embedded_text_layer(self, file_path: Path) -> None:
        """Reject PDFs that appear to depend on OCR before slow parsing starts.

        Args:
            file_path: Temporary PDF file path.

        Raises:
            ValueError: If the PDF looks like a scan-only document.
        """
        probe = self._probe_pdf_text_layer(file_path)
        if probe.requires_ocr:
            raise ValueError(
                "Scanned PDFs that require OCR are not supported in the current "
                "deployment. Please upload a text-based PDF instead."
            )

    @staticmethod
    def _probe_pdf_text_layer(file_path: Path) -> PdfTextLayerProbe:
        """Sample a PDF's embedded text layer without invoking OCR or layout models.

        Args:
            file_path: Temporary PDF file path.

        Returns:
            Fast text-layer probe result for early routing.

        Raises:
            ValueError: If the PDF cannot be inspected.
        """
        try:
            pdfium_module = import_module("pypdfium2")
        except ModuleNotFoundError as err:
            raise ValueError(
                "PDF inspection support is not available in the current backend "
                "environment."
            ) from err

        pdf_document_cls = getattr(pdfium_module, "PdfDocument", None)
        if pdf_document_cls is None:
            raise ValueError(
                "PDF inspection support is incomplete in the installed backend "
                "environment."
            )

        try:
            pdf_document = pdf_document_cls(str(file_path))
        except Exception as err:
            raise ValueError("Uploaded PDF could not be inspected.") from err

        page_count = len(pdf_document)
        sampled_pages = min(page_count, 5)
        extracted_fragments: list[str] = []
        non_empty_pages = 0

        try:
            for page_index in range(sampled_pages):
                page = pdf_document[page_index]
                text_page: Any = None
                try:
                    text_page = page.get_textpage()
                    char_count = int(text_page.count_chars())
                    if char_count <= 0:
                        continue
                    snippet = text_page.get_text_range(
                        index=0,
                        count=min(char_count, 4000),
                    )
                    if not isinstance(snippet, str):
                        snippet = str(snippet)
                    normalized = "".join(snippet.split())
                    if normalized:
                        non_empty_pages += 1
                        extracted_fragments.append(snippet)
                finally:
                    close_text_page = getattr(text_page, "close", None)
                    if callable(close_text_page):
                        close_text_page()
                    close_page = getattr(page, "close", None)
                    if callable(close_page):
                        close_page()
        finally:
            close_document = getattr(pdf_document, "close", None)
            if callable(close_document):
                close_document()

        combined_text = "".join(extracted_fragments)
        printable_chars = sum(
            1 for char in combined_text if char.isprintable() and not char.isspace()
        )
        visible_chars = sum(1 for char in combined_text if not char.isspace())
        printable_ratio = (
            printable_chars / visible_chars if visible_chars > 0 else 0.0
        )

        return PdfTextLayerProbe(
            page_count=page_count,
            sampled_pages=sampled_pages,
            extracted_char_count=visible_chars,
            non_empty_pages=non_empty_pages,
            printable_ratio=printable_ratio,
        )

    @staticmethod
    def _extract_page_count(
        conversion_result: Any,
        document: Any,
    ) -> int | None:
        """Extract page count from Docling objects without assuming one schema."""
        for attr_name in ("page_count", "num_pages"):
            candidate = getattr(conversion_result, attr_name, None)
            if isinstance(candidate, int):
                return candidate

        result_pages = getattr(conversion_result, "pages", None)
        if isinstance(result_pages, list | tuple | dict):
            return len(result_pages)

        for attr_name in ("page_count", "num_pages"):
            candidate = getattr(document, attr_name, None)
            if isinstance(candidate, int):
                return candidate

        document_pages = getattr(document, "pages", None)
        if isinstance(document_pages, list | tuple | dict):
            return len(document_pages)
        return None

    @staticmethod
    def _extract_extension(filename: str) -> str:
        """Return normalized extension without dot."""
        return Path(filename.strip()).suffix.lower().lstrip(".")

    @staticmethod
    def _normalize_original_name(filename: str) -> str:
        """Return a non-empty original filename for persistence."""
        normalized = filename.strip()
        return normalized or "upload.bin"

    @staticmethod
    def _infer_upload_kind(filename: str) -> str:
        """Infer whether the upload should be processed as image or document."""
        extension = FileService._extract_extension(filename)
        if (
            extension in _ALLOWED_DOCUMENT_TYPES
            or extension in _LEGACY_OFFICE_REPLACEMENTS
        ):
            return "document"
        return "image"

    @staticmethod
    def _detect_text_encoding(file_bytes: bytes, extension: str) -> str | None:
        """Best-effort encoding detection for text-like document formats."""
        if extension not in _TEXT_LIKE_DOCUMENT_EXTENSIONS:
            return None

        for encoding in _TEXT_ENCODINGS:
            try:
                file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
            return encoding
        return None

    @staticmethod
    def _build_document_prompt_block(file_asset: FileAsset, markdown_text: str) -> str:
        """Compose the text block injected into the LLM request for a document."""
        metadata_lines = [
            f'Attached document: "{file_asset.original_name}"',
            f"Format: {file_asset.format}",
        ]
        if file_asset.page_count is not None:
            metadata_lines.append(f"Pages: {file_asset.page_count}")
        if file_asset.text_encoding:
            metadata_lines.append(f"Encoding: {file_asset.text_encoding}")
        if file_asset.suspected_scanned:
            metadata_lines.append("Scan-heavy: yes")

        content = markdown_text.strip()
        if not content:
            content = "No extractable text was found in this document."

        metadata_lines.append("")
        metadata_lines.append("Document content:")
        metadata_lines.append(content)
        return "\n".join(metadata_lines)

    @staticmethod
    def _build_image_prompt_blocks(
        file_asset: FileAsset,
        encoded_data: str,
    ) -> list[dict[str, Any]]:
        """Compose the multimodal blocks injected into the LLM request for an image.

        Why: a short descriptor keeps the attachment visible in text-only logs while
        the separate image block preserves the provider-specific base64 slot.
        """
        metadata_lines = [
            f'Attached image: "{file_asset.original_name}"',
            f"MIME type: {file_asset.mime_type}",
        ]
        if file_asset.width > 0 and file_asset.height > 0:
            metadata_lines.append(
                f"Dimensions: {file_asset.width}x{file_asset.height}"
            )

        return [
            {
                "type": "text",
                "text": "\n".join(metadata_lines),
            },
            {
                "type": "image",
                "media_type": file_asset.mime_type,
                "data": encoded_data,
            },
        ]

    def _delete_asset(self, file_asset: FileAsset, commit: bool = False) -> None:
        """Delete both structured metadata and raw file safely."""
        self._safe_unlink(Path(file_asset.storage_path))
        if file_asset.markdown_path:
            self._safe_unlink(Path(file_asset.markdown_path))
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
