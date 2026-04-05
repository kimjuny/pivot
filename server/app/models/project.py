"""Project models for shared multi-session workspaces."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    """One named project that owns a shared workspace.

    Attributes:
        id: Database primary key.
        project_id: Stable public identifier.
        agent_id: Owning agent identifier.
        user: Username that owns this project.
        name: User-visible project name.
        description: Optional description reserved for future UI use.
        workspace_id: Shared workspace public identifier.
        created_at: UTC creation time.
        updated_at: UTC last-update time.
    """

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(index=True, unique=True, description="Public project ID")
    agent_id: int = Field(foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Project owner username")
    name: str = Field(max_length=255, description="Project display name")
    description: str | None = Field(default=None, description="Optional project note")
    workspace_id: str = Field(index=True, description="Shared workspace public ID")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
