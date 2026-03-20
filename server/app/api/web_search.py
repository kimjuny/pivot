"""API endpoints for web-search provider catalog and agent bindings."""

from __future__ import annotations

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.models.web_search import AgentWebSearchBinding
from app.orchestration.web_search.registry import get_web_search_provider
from app.schemas.web_search import (
    WebSearchBindingCreate,
    WebSearchBindingResponse,
    WebSearchBindingTestRequest,
    WebSearchBindingUpdate,
    WebSearchCatalogItemResponse,
    WebSearchTestResponse,
)
from app.services.web_search_service import WebSearchService
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/web-search/providers/{provider_key}/logo", include_in_schema=False)
async def get_web_search_provider_logo(provider_key: str) -> FileResponse:
    """Serve the optional built-in logo asset for one web-search provider."""
    try:
        provider = get_web_search_provider(provider_key)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc

    logo_path = provider.get_logo_path()
    if logo_path is None:
        raise HTTPException(status_code=404, detail="Web search provider logo not found")

    return FileResponse(str(logo_path), media_type="image/svg+xml")


@router.get("/web-search/providers", response_model=list[WebSearchCatalogItemResponse])
async def list_web_search_providers(
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[dict[str, object]]:
    """List all installed built-in web-search provider manifests."""
    del current_user
    return WebSearchService(db).list_catalog()


@router.get(
    "/web-search/providers/{provider_key}",
    response_model=WebSearchCatalogItemResponse,
)
async def get_web_search_provider_manifest(
    provider_key: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Return one web-search provider manifest by provider key."""
    del db, current_user
    try:
        provider = get_web_search_provider(provider_key)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/web-search",
    response_model=list[WebSearchBindingResponse],
)
async def list_agent_web_search_bindings(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> list[WebSearchBindingResponse]:
    """List the web-search bindings configured for one agent."""
    del current_user
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return WebSearchService(db).list_agent_bindings(agent_id)


@router.post(
    "/agents/{agent_id}/web-search",
    response_model=WebSearchBindingResponse,
    status_code=201,
)
async def create_agent_web_search_binding(
    agent_id: int,
    payload: WebSearchBindingCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> WebSearchBindingResponse:
    """Create one web-search provider binding for an agent."""
    del current_user
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return WebSearchService(db).create_binding(
            agent_id=agent_id,
            provider_key=payload.provider_key,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch(
    "/agent-web-search/{binding_id}",
    response_model=WebSearchBindingResponse,
)
async def update_agent_web_search_binding(
    binding_id: int,
    payload: WebSearchBindingUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> WebSearchBindingResponse:
    """Update one configured web-search provider binding."""
    del current_user
    try:
        return WebSearchService(db).update_binding(
            binding_id,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agent-web-search/{binding_id}", status_code=204)
async def delete_agent_web_search_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete one configured web-search provider binding."""
    del current_user
    try:
        WebSearchService(db).delete_binding(binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return None


@router.post(
    "/agent-web-search/{binding_id}/test",
    response_model=WebSearchTestResponse,
)
async def test_agent_web_search_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for a saved binding."""
    del current_user
    binding = db.get(AgentWebSearchBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Web search binding not found")
    try:
        return WebSearchService(db).test_binding(binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/web-search/providers/{provider_key}/test",
    response_model=WebSearchTestResponse,
)
async def test_web_search_provider_draft(
    provider_key: str,
    payload: WebSearchBindingTestRequest,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    del current_user
    try:
        return WebSearchService(db).test_binding_draft(
            provider_key=provider_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
