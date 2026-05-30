"""Service for reading and writing the single ``system_settings`` row."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.config import get_settings
from app.models.system_settings import SystemSettings

if TYPE_CHECKING:
    from sqlmodel import Session


class SystemSettingsService:
    """CRUD operations for the single-row system settings table."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_settings(self) -> SystemSettings:
        """Return the system settings row, creating it with defaults if absent."""
        settings = self.db.get(SystemSettings, 1)
        if settings is None:
            settings = SystemSettings(id=1)
            self.db.add(settings)
            self.db.commit()
            self.db.refresh(settings)
        return settings

    def update_settings(
        self,
        *,
        time_zone: str | None = None,
        language: str | None = None,
        user_id: int | None = None,
    ) -> SystemSettings:
        """Update the system settings row with the provided values."""
        settings = self.get_settings()
        if time_zone is not None:
            settings.time_zone = time_zone
        if language is not None:
            settings.language = language
        settings.updated_at = datetime.now(UTC)
        settings.updated_by_user_id = user_id
        self.db.add(settings)
        self.db.commit()
        self.db.refresh(settings)
        return settings

    def get_time_zone(self) -> str:
        """Return the configured timezone, falling back to the env var."""
        settings = self.db.get(SystemSettings, 1)
        if settings is not None and settings.time_zone:
            return settings.time_zone
        return get_settings().SYSTEM_TIME_ZONE
