"""Database models for uploaded user files."""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class FileAsset(SQLModel, table=True):
    """Persistent metadata for an uploaded file stored in user workspace."""

    id: int | None = Field(default=None, primary_key=True)
    file_id: str = Field(index=True, unique=True, description="Public UUID for file")
    user: str = Field(index=True, description="Owner username")
    source: str = Field(description="Upload source such as local or clipboard")
    original_name: str = Field(description="Original client-side filename")
    stored_name: str = Field(description="Stored filename on disk")
    storage_path: str = Field(description="Absolute path to the stored file")
    kind: str = Field(
        default="image",
        description="Normalized asset kind such as image or document",
    )
    mime_type: str = Field(description="Verified MIME type")
    format: str = Field(description="Verified Pillow format")
    extension: str = Field(description="Normalized file extension without dot")
    size_bytes: int = Field(description="Stored file size in bytes")
    width: int = Field(description="Image width in pixels")
    height: int = Field(description="Image height in pixels")
    page_count: int | None = Field(
        default=None,
        description="Estimated page count for document uploads",
    )
    markdown_path: str | None = Field(
        default=None,
        description="Absolute path to cached markdown extracted from a document",
    )
    can_extract_text: bool = Field(
        default=False,
        description="Whether a textual document representation was extracted",
    )
    suspected_scanned: bool = Field(
        default=False,
        description="Whether the document appears to need OCR or is scan-heavy",
    )
    text_encoding: str | None = Field(
        default=None,
        description="Detected source encoding for text-like documents",
    )
    session_id: str | None = Field(
        default=None,
        index=True,
        description="Session UUID once the file is actually used",
    )
    task_id: str | None = Field(
        default=None,
        index=True,
        description="Task UUID that consumed the file",
    )
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        index=True,
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
