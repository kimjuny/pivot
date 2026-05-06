"""API endpoints for media-generation provider catalog and agent bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel
from app.models.media_generation import AgentMediaProviderBinding
from app.schemas.media_generation import (
    MediaProviderBindingCreate,
    MediaProviderBindingResponse,
    MediaProviderBindingTestRequest,
    MediaProviderBindingUpdate,
    MediaProviderCatalogItemResponse,
    MediaProviderTestResponse,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.media_generation_service import MediaGenerationService
from app.services.provider_registry_service import ProviderRegistryService
from fastapi import APIRouter, Depends, HTTPException, Response

router = APIRouter()

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from sqlmodel import Session


def _require_agent_edit(db: Session, agent_id: int, current_user: User) -> Agent:
    """Return one agent after checking media-provider edit access."""
    try:
        agent = AgentService(db).get_required_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    AccessService(db).require_agent_access(
        user=current_user,
        agent=agent,
        access_level=AccessLevel.EDIT,
    )
    return agent


def _require_media_binding_edit(
    db: Session,
    binding_id: int,
    current_user: User,
) -> AgentMediaProviderBinding:
    """Return one media provider binding after parent Agent.edit check."""
    binding = db.get(AgentMediaProviderBinding, binding_id)
    if binding is None:
        raise HTTPException(
            status_code=404,
            detail="Media generation binding not found",
        )
    _require_agent_edit(db, binding.agent_id, current_user)
    return binding


@router.get(
    "/media-generation/providers",
    response_model=list[MediaProviderCatalogItemResponse],
)
async def list_media_generation_providers(
    agent_id: int | None = None,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> list[dict[str, object]]:
    """List all media-generation providers available to the current Studio user."""
    if agent_id is not None:
        _require_agent_edit(db, agent_id, current_user)
    return MediaGenerationService(db).list_catalog(agent_id, user=current_user)


@router.get(
    "/media-generation/providers/{provider_key}",
    response_model=MediaProviderCatalogItemResponse,
)
async def get_media_generation_provider_manifest(
    provider_key: str,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> dict[str, object]:
    """Return one media-generation provider manifest by provider key."""
    service = MediaGenerationService(db)
    try:
        provider = ProviderRegistryService(db).get_media_generation_provider(
            provider_key
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Media generation provider not found"
        ) from exc
    if not service.is_provider_usable_by_user(user=current_user, provider=provider):
        raise HTTPException(
            status_code=404,
            detail="Media generation provider not found",
        )
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/media-providers",
    response_model=list[MediaProviderBindingResponse],
)
async def list_agent_media_provider_bindings(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> list[MediaProviderBindingResponse]:
    """List the media-generation bindings configured for one agent."""
    _require_agent_edit(db, agent_id, current_user)
    return MediaGenerationService(db).list_agent_bindings(agent_id)


@router.post(
    "/agents/{agent_id}/media-providers",
    response_model=MediaProviderBindingResponse,
    status_code=201,
)
async def create_agent_media_provider_binding(
    agent_id: int,
    payload: MediaProviderBindingCreate,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> MediaProviderBindingResponse:
    """Create one media-generation provider binding for an agent."""
    _require_agent_edit(db, agent_id, current_user)
    try:
        binding = MediaGenerationService(db).create_binding(
            agent_id=agent_id,
            provider_key=payload.provider_key,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
            user=current_user,
        )
        AgentSnapshotService(db).save_draft(
            agent_id,
            saved_by=current_user.username,
        )
        return binding
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Media generation provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/agent-media-providers/{binding_id}",
    response_model=MediaProviderBindingResponse,
)
async def update_agent_media_provider_binding(
    binding_id: int,
    payload: MediaProviderBindingUpdate,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> MediaProviderBindingResponse:
    """Update one configured media-generation provider binding."""
    binding_row = _require_media_binding_edit(db, binding_id, current_user)
    try:
        binding = MediaGenerationService(db).update_binding(
            binding_id,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
        AgentSnapshotService(db).save_draft(
            binding_row.agent_id,
            saved_by=current_user.username,
        )
        return binding
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agent-media-providers/{binding_id}", status_code=204)
async def delete_agent_media_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> Response:
    """Delete one configured media-generation provider binding."""
    binding = _require_media_binding_edit(db, binding_id, current_user)
    try:
        MediaGenerationService(db).delete_binding(binding_id)
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/agent-media-providers/{binding_id}/test",
    response_model=MediaProviderTestResponse,
)
async def test_agent_media_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test for a saved binding."""
    _require_media_binding_edit(db, binding_id, current_user)
    try:
        return MediaGenerationService(db).test_binding(binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/media-generation/providers/{provider_key}/test",
    response_model=MediaProviderTestResponse,
)
async def test_media_generation_provider_draft(
    provider_key: str,
    payload: MediaProviderBindingTestRequest,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.MEDIA_GENERATION_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    try:
        return MediaGenerationService(db).test_binding_draft(
            provider_key=provider_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
            user=current_user,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Media generation provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
