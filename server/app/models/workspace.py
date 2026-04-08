"""Workspace records that own sandbox filesystem state."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Workspace(SQLModel, table=True):
    """One persistent runtime workspace bound to a session or project.

    Attributes:
        id: Database primary key.
        workspace_id: Stable public identifier used by the backend and sandbox.
        agent_id: Owning agent identifier.
        user: Username that owns this workspace.
        scope: Either ``session_private`` or ``project_shared``.
        session_id: Session UUID for private workspaces.
        project_id: Project UUID for shared project workspaces.
        status: Lifecycle state for future reset/repair flows.
        storage_backend: Persistent storage backend identity for this workspace.
        logical_path: Canonical storage path within the selected backend.
        mount_mode: Runtime attach behavior, currently ``live_sync``.
        source_workspace_id: Optional future source workspace for clone flows.
        created_at: UTC creation time.
        updated_at: UTC last-update time.
    """

    id: int | None = Field(default=None, primary_key=True)
    workspace_id: str = Field(
        index=True, unique=True, description="Public workspace ID"
    )
    agent_id: int = Field(foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Workspace owner username")
    scope: str = Field(description="Workspace scope: session_private or project_shared")
    session_id: str | None = Field(default=None, index=True)
    project_id: str | None = Field(default=None, index=True)
    status: str = Field(default="active", description="Workspace lifecycle status")
    storage_backend: str = Field(default="seaweedfs", max_length=64)
    logical_path: str = Field(default="", unique=True, max_length=1024)
    mount_mode: str = Field(default="live_sync", max_length=64)
    source_workspace_id: str | None = Field(default=None, index=True, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
