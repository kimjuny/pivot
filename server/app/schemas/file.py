"""Schemas for uploaded image APIs."""

from pydantic import BaseModel, Field


class FileAssetResponse(BaseModel):
    """Metadata returned for an uploaded image."""

    file_id: str = Field(..., description="Public UUID for the uploaded file")
    source: str = Field(..., description="Upload source such as local or clipboard")
    original_name: str = Field(..., description="Original client-side filename")
    mime_type: str = Field(..., description="Verified MIME type")
    format: str = Field(..., description="Verified image format")
    extension: str = Field(..., description="Normalized extension without dot")
    size_bytes: int = Field(..., description="Stored file size in bytes")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    session_id: str | None = Field(
        default=None,
        description="Session UUID once the file is used in a conversation",
    )
    task_id: str | None = Field(
        default=None,
        description="Task UUID that consumed the file",
    )
    created_at: str = Field(..., description="UTC creation timestamp in ISO format")
    expires_at: str = Field(..., description="UTC expiry timestamp in ISO format")


class FileAssetListItem(BaseModel):
    """Compact file metadata used inside task history responses."""

    file_id: str
    original_name: str
    mime_type: str
    format: str
    extension: str
    size_bytes: int
    width: int
    height: int
    source: str
    created_at: str
