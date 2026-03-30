"""Schemas for assistant-generated task attachments."""

from app.schemas.base import AppBaseModel
from pydantic import Field


class TaskAttachmentListItem(AppBaseModel):
    """Compact metadata used in streaming events and chat history payloads."""

    attachment_id: str
    display_name: str
    original_name: str
    mime_type: str
    extension: str
    size_bytes: int
    render_kind: str
    workspace_relative_path: str
    created_at: str


class TaskAttachmentResponse(TaskAttachmentListItem):
    """Expanded attachment metadata returned by detail APIs."""

    task_id: str = Field(..., description="Owning task UUID.")
    session_id: str | None = Field(
        default=None,
        description="Owning session UUID when available.",
    )
    agent_id: int = Field(..., description="Owning agent identifier.")
