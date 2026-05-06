"""API endpoints for web-search provider catalog and agent bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel
from app.models.web_search import AgentWebSearchBinding
from app.schemas.web_search import (
    WebSearchBindingCreate,
    WebSearchBindingResponse,
    WebSearchBindingTestRequest,
    WebSearchBindingUpdate,
    WebSearchCatalogItemResponse,
    WebSearchTestResponse,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.provider_registry_service import ProviderRegistryService
from app.services.web_search_service import WebSearchService
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

router = APIRouter()

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from sqlmodel import Session


def _require_agent_edit(db: Session, agent_id: int, current_user: User) -> Agent:
    """Return one agent after checking web-search edit access."""
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


def _require_web_search_binding_edit(
    db: Session,
    binding_id: int,
    current_user: User,
) -> AgentWebSearchBinding:
    """Return one web-search binding after parent Agent.edit check."""
    binding = db.get(AgentWebSearchBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Web search binding not found")
    _require_agent_edit(db, binding.agent_id, current_user)
    return binding


@router.get("/web-search/providers/{provider_key}/logo", include_in_schema=False)
async def get_web_search_provider_logo(
    provider_key: str,
    db=Depends(get_db),
) -> FileResponse:
    """Serve the optional built-in logo asset for one web-search provider."""
    try:
        provider = ProviderRegistryService(db).get_web_search_provider(provider_key)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc

    logo_path = provider.get_logo_path()
    if logo_path is None:
        raise HTTPException(
            status_code=404, detail="Web search provider logo not found"
        )

    return FileResponse(str(logo_path), media_type="image/svg+xml")


@router.get("/web-search/providers", response_model=list[WebSearchCatalogItemResponse])
async def list_web_search_providers(
    agent_id: int | None = None,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> list[dict[str, object]]:
    """List all web-search providers available to the current Studio user."""
    if agent_id is not None:
        _require_agent_edit(db, agent_id, current_user)
    return WebSearchService(db).list_catalog(agent_id, user=current_user)


@router.get(
    "/web-search/providers/{provider_key}",
    response_model=WebSearchCatalogItemResponse,
)
async def get_web_search_provider_manifest(
    provider_key: str,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> dict[str, object]:
    """Return one web-search provider manifest by provider key."""
    service = WebSearchService(db)
    try:
        provider = ProviderRegistryService(db).get_web_search_provider(provider_key)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc
    if not service.is_provider_usable_by_user(user=current_user, provider=provider):
        raise HTTPException(status_code=404, detail="Web search provider not found")
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/web-search",
    response_model=list[WebSearchBindingResponse],
)
async def list_agent_web_search_bindings(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> list[WebSearchBindingResponse]:
    """List the web-search bindings configured for one agent."""
    _require_agent_edit(db, agent_id, current_user)
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
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> WebSearchBindingResponse:
    """Create one web-search provider binding for an agent."""
    _require_agent_edit(db, agent_id, current_user)
    try:
        binding = WebSearchService(db).create_binding(
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
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> WebSearchBindingResponse:
    """Update one configured web-search provider binding."""
    binding_row = _require_web_search_binding_edit(db, binding_id, current_user)
    try:
        binding = WebSearchService(db).update_binding(
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


@router.delete("/agent-web-search/{binding_id}", status_code=204)
async def delete_agent_web_search_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> Response:
    """Delete one configured web-search provider binding."""
    binding = _require_web_search_binding_edit(db, binding_id, current_user)
    try:
        WebSearchService(db).delete_binding(binding_id)
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/agent-web-search/{binding_id}/test",
    response_model=WebSearchTestResponse,
)
async def test_agent_web_search_binding(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test for a saved binding."""
    _require_web_search_binding_edit(db, binding_id, current_user)
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
    current_user=Depends(permissions(Permission.WEB_SEARCH_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    try:
        return WebSearchService(db).test_binding_draft(
            provider_key=provider_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
            user=current_user,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Web search provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
