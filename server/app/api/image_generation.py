"""API endpoints for image-generation provider catalog and agent bindings."""

from __future__ import annotations

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.models.image_generation import AgentImageProviderBinding
from app.schemas.image_generation import (
    ImageProviderBindingCreate,
    ImageProviderBindingResponse,
    ImageProviderBindingTestRequest,
    ImageProviderBindingUpdate,
    ImageProviderCatalogItemResponse,
    ImageProviderTestResponse,
)
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.image_generation_service import ImageGenerationService
from app.services.provider_registry_service import ProviderRegistryService
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter()


@router.get(
    "/image-generation/providers",
    response_model=list[ImageProviderCatalogItemResponse],
)
async def list_image_generation_providers(
    agent_id: int | None = None,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[dict[str, object]]:
    """List all installed image-generation provider manifests."""
    del current_user
    return ImageGenerationService(db).list_catalog(agent_id)


@router.get(
    "/image-generation/providers/{provider_key}",
    response_model=ImageProviderCatalogItemResponse,
)
async def get_image_generation_provider_manifest(
    provider_key: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Return one image-generation provider manifest by provider key."""
    del current_user
    try:
        provider = ProviderRegistryService(db).get_image_generation_provider(
            provider_key
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Image generation provider not found"
        ) from exc
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/image-providers",
    response_model=list[ImageProviderBindingResponse],
)
async def list_agent_image_provider_bindings(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[ImageProviderBindingResponse]:
    """List the image-generation bindings configured for one agent."""
    del current_user
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return ImageGenerationService(db).list_agent_bindings(agent_id)


@router.post(
    "/agents/{agent_id}/image-providers",
    response_model=ImageProviderBindingResponse,
    status_code=201,
)
async def create_agent_image_provider_binding(
    agent_id: int,
    payload: ImageProviderBindingCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> ImageProviderBindingResponse:
    """Create one image-generation provider binding for an agent."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        binding = ImageGenerationService(db).create_binding(
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
            status_code=404, detail="Image generation provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/agent-image-providers/{binding_id}",
    response_model=ImageProviderBindingResponse,
)
async def update_agent_image_provider_binding(
    binding_id: int,
    payload: ImageProviderBindingUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> ImageProviderBindingResponse:
    """Update one configured image-generation provider binding."""
    try:
        binding = ImageGenerationService(db).update_binding(
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


@router.delete("/agent-image-providers/{binding_id}", status_code=204)
async def delete_agent_image_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete one configured image-generation provider binding."""
    binding = db.get(AgentImageProviderBinding, binding_id)
    if binding is None:
        raise HTTPException(
            status_code=404, detail="Image generation binding not found"
        )
    try:
        ImageGenerationService(db).delete_binding(binding_id)
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post(
    "/agent-image-providers/{binding_id}/test",
    response_model=ImageProviderTestResponse,
)
async def test_agent_image_provider_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for a saved binding."""
    del current_user
    binding = db.get(AgentImageProviderBinding, binding_id)
    if binding is None:
        raise HTTPException(
            status_code=404, detail="Image generation binding not found"
        )
    try:
        return ImageGenerationService(db).test_binding(binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/image-generation/providers/{provider_key}/test",
    response_model=ImageProviderTestResponse,
)
async def test_image_generation_provider_draft(
    provider_key: str,
    payload: ImageProviderBindingTestRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    del current_user
    try:
        return ImageGenerationService(db).test_binding_draft(
            provider_key=provider_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Image generation provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
