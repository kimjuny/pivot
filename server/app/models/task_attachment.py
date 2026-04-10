"""Database models for agent-generated task attachments."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class TaskAttachment(SQLModel, table=True):
    """Live assistant file reference generated for one task answer."""

    id: int | None = Field(default=None, primary_key=True)
    attachment_id: str = Field(
        index=True,
        unique=True,
        description="Public UUID for one persisted task attachment.",
    )
    task_id: str = Field(index=True, description="Owning ReAct task UUID.")
    session_id: str | None = Field(
        default=None,
        index=True,
        description="Owning session UUID when the task belongs to a session.",
    )
    workspace_id: str = Field(
        index=True,
        description="Owning workspace UUID that currently hosts the live file.",
    )
    agent_id: int = Field(index=True, description="Owning agent identifier.")
    user: str = Field(index=True, description="Owner username.")
    display_name: str = Field(description="User-facing filename shown in the UI.")
    original_name: str = Field(
        description="Original artifact filename derived from the workspace path."
    )
    mime_type: str = Field(description="Detected MIME type for preview routing.")
    extension: str = Field(description="Normalized file extension without dot.")
    size_bytes: int = Field(description="Persisted file size in bytes.")
    render_kind: str = Field(
        description="Preferred frontend renderer such as markdown, pdf, image, or download."
    )
    sandbox_path: str = Field(
        description="Original sandbox path declared by the model under /workspace."
    )
    workspace_relative_path: str = Field(
        description="Path relative to the agent workspace root."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
