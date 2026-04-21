"""API endpoints for media-generation provider catalog and agent bindings."""

from __future__ import annotations

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.models.media_generation import AgentMediaProviderBinding
from app.schemas.media_generation import (
    MediaProviderBindingCreate,
    MediaProviderBindingResponse,
    MediaProviderBindingTestRequest,
    MediaProviderBindingUpdate,
    MediaProviderCatalogItemResponse,
    MediaProviderTestResponse,
)
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.media_generation_service import MediaGenerationService
from app.services.provider_registry_service import ProviderRegistryService
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get(
    "/media-generation/providers",
    response_model=list[MediaProviderCatalogItemResponse],
)
async def list_media_generation_providers(
    agent_id: int | None = None,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[dict[str, object]]:
    """List all installed media-generation provider manifests."""
    del current_user
    return MediaGenerationService(db).list_catalog(agent_id)


@router.get(
    "/media-generation/providers/{provider_key}",
    response_model=MediaProviderCatalogItemResponse,
)
async def get_media_generation_provider_manifest(
    provider_key: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Return one media-generation provider manifest by provider key."""
    del current_user
    try:
        provider = ProviderRegistryService(db).get_media_generation_provider(
            provider_key
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Media generation provider not found"
        ) from exc
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/media-providers",
    response_model=list[MediaProviderBindingResponse],
)
async def list_agent_media_provider_bindings(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[MediaProviderBindingResponse]:
    """List the media-generation bindings configured for one agent."""
    del current_user
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
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
    current_user=Depends(get_current_user),
) -> MediaProviderBindingResponse:
    """Create one media-generation provider binding for an agent."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        binding = MediaGenerationService(db).create_binding(
            agent_id=agent_id,
            provider_key=payload.provider_key,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
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
    current_user=Depends(get_current_user),
) -> MediaProviderBindingResponse:
    """Update one configured media-generation provider binding."""
    try:
        binding = MediaGenerationService(db).update_binding(
            binding_id,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
        return binding
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agent-media-providers/{binding_id}", status_code=204)
async def delete_agent_media_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete one configured media-generation provider binding."""
    binding = db.get(AgentMediaProviderBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Media generation binding not found")
    try:
        MediaGenerationService(db).delete_binding(binding_id)
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post(
    "/agent-media-providers/{binding_id}/test",
    response_model=MediaProviderTestResponse,
)
async def test_agent_media_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for a saved binding."""
    del current_user
    binding = db.get(AgentMediaProviderBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Media generation binding not found")
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
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    del current_user
    try:
        return MediaGenerationService(db).test_binding_draft(
            provider_key=provider_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Media generation provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
