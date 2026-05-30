"""System-level configuration stored in the database.

Unlike ``app.config.Settings`` which reads from environment variables,
this model stores runtime-editable settings (timezone, language, etc.)
that can be changed via the admin UI without restarting the server.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class SystemSettings(SQLModel, table=True):
    """Single-row table holding global application settings.

    Convention: exactly one row with ``id=1`` always exists after
    ``ensure_database_ready`` seeds the defaults.
    """

    __tablename__ = "system_settings"  # type: ignore[assignment]

    id: int = Field(default=1, primary_key=True)
    time_zone: str = Field(default="Asia/Shanghai", max_length=64)
    language: str = Field(default="en-US", max_length=16)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_by_user_id: int | None = Field(default=None, foreign_key="user.id")
