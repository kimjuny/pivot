"""Persistent authorization metadata for tools."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class ToolResource(SQLModel, table=True):
    """Registry row for one built-in or user-created tool's auth metadata."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True, max_length=255)
    name: str = Field(index=True, max_length=255)
    source_type: str = Field(index=True, max_length=20)
    creator_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    use_scope: str = Field(default="all", max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
