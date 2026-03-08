"""Schemas for uploaded file APIs."""

from pydantic import Field

from app.schemas.base import AppBaseModel


class FileAssetResponse(AppBaseModel):
    """Metadata returned for an uploaded file."""

    file_id: str = Field(..., description="Public UUID for the uploaded file")
    kind: str = Field(..., description="Normalized asset kind such as image or document")
    source: str = Field(..., description="Upload source such as local or clipboard")
    original_name: str = Field(..., description="Original client-side filename")
    mime_type: str = Field(..., description="Verified MIME type")
    format: str = Field(..., description="Verified file format")
    extension: str = Field(..., description="Normalized extension without dot")
    size_bytes: int = Field(..., description="Stored file size in bytes")
    width: int = Field(..., description="Image width in pixels")
    height: int = Field(..., description="Image height in pixels")
    page_count: int | None = Field(
        default=None,
        description="Estimated page count for document uploads",
    )
    can_extract_text: bool = Field(
        default=False,
        description="Whether a textual representation is available",
    )
    suspected_scanned: bool = Field(
        default=False,
        description="Whether the document appears scan-heavy",
    )
    text_encoding: str | None = Field(
        default=None,
        description="Detected text encoding when applicable",
    )
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


class FileAssetListItem(AppBaseModel):
    """Compact file metadata used inside task history responses."""

    file_id: str
    kind: str
    original_name: str
    mime_type: str
    format: str
    extension: str
    size_bytes: int
    width: int
    height: int
    page_count: int | None = None
    can_extract_text: bool = False
    suspected_scanned: bool = False
    text_encoding: str | None = None
    source: str
    created_at: str
