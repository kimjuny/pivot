"""API endpoints for reading and updating system settings."""

from app.api.permissions import permissions
from app.db.session import get_session
from app.models.user import User
from app.schemas.system_settings import (
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
)
from app.security.permission_catalog import Permission
from app.services.system_settings_service import SystemSettingsService
from fastapi import APIRouter, Depends
from sqlmodel import Session

router = APIRouter(tags=["system-settings"])


@router.get("/system/settings", response_model=SystemSettingsResponse)
def get_system_settings(
    db: Session = Depends(get_session),
    _current_user: User = Depends(permissions(Permission.SETTINGS_MANAGE)),
) -> SystemSettingsResponse:
    """Return the current system settings."""
    svc = SystemSettingsService(db)
    settings = svc.get_settings()
    return SystemSettingsResponse.model_validate(settings)


@router.put("/system/settings", response_model=SystemSettingsResponse)
def update_system_settings(
    payload: SystemSettingsUpdateRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(permissions(Permission.SETTINGS_MANAGE)),
) -> SystemSettingsResponse:
    """Update one or more system settings fields."""
    svc = SystemSettingsService(db)
    settings = svc.update_settings(
        time_zone=payload.time_zone,
        language=payload.language,
        user_id=current_user.id,
    )
    return SystemSettingsResponse.model_validate(settings)
