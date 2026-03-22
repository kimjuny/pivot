"""Persistent skill metadata stored separately from markdown source files."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Skill(SQLModel, table=True):
    """Registry row for one visible skill.

    Why: skill source remains on disk for editor and sandbox use, while searchable
    metadata lives in the database so resolution can operate on compact records.

    Attributes:
        id: Primary key of the skill registry row.
        name: Globally unique skill identifier used by agents and sandbox mounts.
        description: Short summary extracted from markdown front matter.
        kind: Visibility scope, either ``private`` or ``shared``.
        source: Origin of the skill, either ``builtin`` or ``user``.
        builtin: Whether the skill ships with the application.
        creator_id: Owning user ID for user-created skills.
        location: Absolute directory path that contains the markdown skill assets.
        filename: Markdown filename inside ``location``.
        md5: Content digest of the markdown source for quick change detection.
        github_repo_url: Upstream GitHub repository URL for imported skills.
        github_ref: Imported Git ref, usually a branch or tag name.
        github_ref_type: Imported ref classification, either ``branch`` or ``tag``.
        github_skill_path: Original repository path for the imported skill folder.
        created_at: UTC timestamp when the skill was first registered.
        updated_at: UTC timestamp when the markdown source last changed.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=255)
    description: str = Field(default="")
    kind: str = Field(max_length=20)
    source: str = Field(max_length=20)
    builtin: bool = Field(default=False, index=True)
    creator_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    location: str = Field(unique=True, max_length=1024)
    filename: str = Field(max_length=255)
    md5: str = Field(max_length=32)
    github_repo_url: str | None = Field(default=None, max_length=1024)
    github_ref: str | None = Field(default=None, max_length=255)
    github_ref_type: str | None = Field(default=None, max_length=32)
    github_skill_path: str | None = Field(default=None, max_length=1024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
