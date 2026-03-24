"""Persistent records for agent-authored skill change submissions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class SkillChangeSubmission(SQLModel, table=True):
    """One pending or finalized skill change staged from a sandbox draft.

    Attributes:
        id: Primary key of the submission row.
        creator_id: User who owns the target private skill namespace.
        agent_id: Agent workspace that produced the draft.
        skill_name: Target globally unique skill identifier.
        target_kind: Destination scope. V1 only supports ``private``.
        change_type: Whether the submission creates or updates a skill.
        status: Lifecycle state such as ``pending`` or ``applied``.
        sandbox_draft_path: Original sandbox-local draft directory path.
        snapshot_location: Host path that stores the frozen submission snapshot.
        summary: Optional agent-authored rationale for the submission.
        details_json: Serialized validation and preview metadata for the UI/tooling.
        reviewed_at: UTC timestamp when the user approved or rejected the change.
        created_at: UTC timestamp when the submission was staged.
        updated_at: UTC timestamp when the row last changed.
    """

    id: int | None = Field(default=None, primary_key=True)
    creator_id: int = Field(foreign_key="user.id", index=True)
    agent_id: int = Field(index=True)
    skill_name: str = Field(index=True, max_length=255)
    target_kind: str = Field(default="private", max_length=20)
    change_type: str = Field(max_length=20)
    status: str = Field(default="pending", max_length=32, index=True)
    sandbox_draft_path: str = Field(max_length=1024)
    snapshot_location: str = Field(max_length=1024)
    summary: str = Field(default="")
    details_json: str | None = Field(default=None)
    reviewed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
