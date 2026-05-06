"""Persistent skill metadata stored alongside runtime and artifact references."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Skill(SQLModel, table=True):
    """Registry row for one visible skill.

    Why: the canonical skill bundle should be artifact-backed, while the runtime
    still keeps one local directory for editor access and sandbox injection.

    Attributes:
        id: Primary key of the skill registry row.
        name: Globally unique skill identifier used by agents and sandbox mounts.
        description: Short summary extracted from markdown front matter.
        source: Origin of the skill, one of ``manual``, ``network``,
            ``bundle``, or ``agent``.
        creator_id: Owning user ID for user-created skills.
        location: Absolute directory path that contains the markdown skill assets.
        artifact_storage_backend: Stable object-storage backend identifier for
            the canonical skill artifact bundle.
        artifact_key: Canonical object-storage key for the skill artifact.
        artifact_digest: Stable digest of the persisted artifact payload.
        artifact_size_bytes: Size of the persisted artifact in bytes.
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
    use_scope: str = Field(default="all", max_length=20)
    source: str = Field(max_length=20)
    creator_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    location: str = Field(unique=True, max_length=1024)
    artifact_storage_backend: str | None = Field(default=None, max_length=64)
    artifact_key: str | None = Field(default=None, unique=True, max_length=2048)
    artifact_digest: str | None = Field(default=None, index=True, max_length=64)
    artifact_size_bytes: int = Field(default=0)
    filename: str = Field(max_length=255)
    md5: str = Field(max_length=32)
    github_repo_url: str | None = Field(default=None, max_length=1024)
    github_ref: str | None = Field(default=None, max_length=255)
    github_ref_type: str | None = Field(default=None, max_length=32)
    github_skill_path: str | None = Field(default=None, max_length=1024)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
