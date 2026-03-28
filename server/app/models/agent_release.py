"""Database models for persisted agent draft and release snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class AgentSavedDraft(SQLModel, table=True):
    """Persisted saved-draft snapshot for one agent.

    Attributes:
        id: Primary key of the saved draft row.
        agent_id: Unique agent that owns this saved draft snapshot.
        snapshot_json: Canonical JSON payload representing the saved draft.
        snapshot_hash: Stable content hash for quick equality checks.
        saved_by: Username that last saved this draft, if known.
        saved_at: UTC timestamp of the latest persisted draft save.
    """

    __table_args__ = (UniqueConstraint("agent_id"),)

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    snapshot_json: str = Field()
    snapshot_hash: str = Field(index=True, max_length=64)
    saved_by: str | None = Field(default=None, max_length=120)
    saved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentTestSnapshot(SQLModel, table=True):
    """Immutable Studio test snapshot frozen from one working copy.

    Attributes:
        id: Primary key of the Studio test snapshot row.
        agent_id: Agent whose working copy produced the snapshot.
        snapshot_json: Canonical runtime snapshot used for test execution.
        snapshot_hash: Stable content hash for the full runtime snapshot.
        workspace_hash: Stable content hash for the Studio working-copy anchor.
        created_by: Username that created the test snapshot, if known.
        created_at: UTC timestamp when the snapshot was frozen.
    """

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    snapshot_json: str = Field()
    snapshot_hash: str = Field(index=True, max_length=64)
    workspace_hash: str = Field(index=True, max_length=64)
    created_by: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentRelease(SQLModel, table=True):
    """Immutable published release snapshot for one agent.

    Attributes:
        id: Primary key of the release row.
        agent_id: Agent that owns this release.
        version: Agent-scoped release sequence number starting from 1.
        snapshot_json: Canonical JSON payload published for this release.
        snapshot_hash: Stable content hash for quick equality checks.
        release_note: Optional human-written release note captured at publish time.
        change_summary_json: JSON array of summary strings for audit surfaces.
        published_by: Username that published this release, if known.
        created_at: UTC timestamp when the release was published.
    """

    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    version: int = Field(index=True, ge=1)
    snapshot_json: str = Field()
    snapshot_hash: str = Field(index=True, max_length=64)
    release_note: str | None = Field(default=None)
    change_summary_json: str = Field(default="[]")
    published_by: str | None = Field(default=None, max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
