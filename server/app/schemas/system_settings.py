"""Pydantic schemas for system settings API endpoints."""

from datetime import datetime

from app.schemas.base import AppBaseModel


class SystemSettingsResponse(AppBaseModel):
    """Serializer for the single system settings row."""

    time_zone: str
    language: str
    updated_at: datetime
    updated_by_user_id: int | None


class SystemSettingsUpdateRequest(AppBaseModel):
    """Payload for updating one or more system settings fields."""

    time_zone: str | None = None
    language: str | None = None
