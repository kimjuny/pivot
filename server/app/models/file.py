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
    mime_type: str = Field(description="Verified MIME type")
    format: str = Field(description="Verified Pillow format")
    extension: str = Field(description="Normalized file extension without dot")
    size_bytes: int = Field(description="Stored file size in bytes")
    width: int = Field(description="Image width in pixels")
    height: int = Field(description="Image height in pixels")
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
