"""Client-facing API endpoints for visible published agents."""

from __future__ import annotations

import json
from datetime import UTC
from typing import TYPE_CHECKING, Any, Literal, cast

from app.api.permissions import permissions
from app.crud.llm import llm as llm_crud
from app.models.access import AccessLevel
from app.schemas.extension import (
    ChatSurfaceDescriptor,
    WebSearchProviderOption,
)
from app.schemas.project import ProjectResponse
from app.schemas.schemas import AgentResponse, LLMUsableResponse
from app.schemas.session import (
    ClientSessionListItem,
    ClientSessionListResponse,
    SessionListItem,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.extension_service import (
    ExtensionService,
    _build_contribution_items,
)
from app.services.project_service import ProjectService
from app.services.session_service import SessionService
from app.services.web_search_service import WebSearchService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .dependencies import get_db

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session as DbSession

router = APIRouter()


def _serialize_client_agent_response(
    agent: Any,
    *,
    model_display: str,
) -> dict[str, Any]:
    """Serialize one Client-visible agent into the existing response shape."""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "created_by_user_id": agent.created_by_user_id,
        "use_scope": agent.use_scope,
        "llm_id": agent.llm_id,
        "session_idle_timeout_minutes": agent.session_idle_timeout_minutes,
        "sandbox_timeout_seconds": agent.sandbox_timeout_seconds,
        "compact_threshold_percent": agent.compact_threshold_percent,
        "active_release_id": agent.active_release_id,
        "client_state": agent.client_state,
        "model_name": model_display,
        "max_iteration": agent.max_iteration,
        "tool_ids": agent.tool_ids,
        "skill_ids": agent.skill_ids,
        "allow_delegation": agent.allow_delegation,
        "delegation_description": agent.delegation_description,
        "created_at": agent.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": agent.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def _resolve_model_display(
    db: DbSession, llm_id: int | None, fallback: str | None
) -> str:
    """Resolve the visible model label shown in Client agent cards."""
    model_display = fallback or "N/A"
    if llm_id is None:
        return model_display

    llm = llm_crud.get(llm_id, db)
    if llm is None:
        return model_display
    return f"{llm.name} ({llm.model})"


@router.get("/client/agents", response_model=list[AgentResponse])
async def list_client_agents(
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> list[dict[str, Any]]:
    """List all agents currently visible in the Client product."""
    agents = AccessService(db).list_accessible_agents(
        user=current_user,
        access_level=AccessLevel.USE,
        require_published=True,
        require_serving=True,
    )
    return [
        _serialize_client_agent_response(
            agent,
            model_display=_resolve_model_display(db, agent.llm_id, agent.model_name),
        )
        for agent in agents
    ]


@router.get("/client/agents/{agent_id}", response_model=AgentResponse)
async def get_client_agent(
    agent_id: int,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> dict[str, Any]:
    """Return one Client-visible agent by identifier."""
    try:
        agent = AgentService(db).require_client_visible_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    AccessService(db).require_agent_access(
        user=current_user,
        agent=agent,
        access_level=AccessLevel.USE,
    )

    return _serialize_client_agent_response(
        agent,
        model_display=_resolve_model_display(db, agent.llm_id, agent.model_name),
    )


@router.get("/client/sessions", response_model=ClientSessionListResponse)
async def list_client_sessions(
    limit: int = 20,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ClientSessionListResponse:
    """List the current user's recent sessions for Client-visible agents."""
    visible_agents = {
        agent.id: agent
        for agent in AccessService(db).list_accessible_agents(
            user=current_user,
            access_level=AccessLevel.USE,
            require_published=True,
            require_serving=True,
            limit=10000,
        )
        if agent.id is not None
    }
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    sessions = SessionService(db).get_sessions_by_user(
        user_id=current_user.id,
        agent_ids=list(visible_agents),
        session_type="client",
        limit=limit,
    )

    session_service = SessionService(db)
    return ClientSessionListResponse(
        sessions=[
            ClientSessionListItem(
                session_id=session.session_id,
                agent_id=session.agent_id,
                type=cast("Literal['client', 'studio_test']", session.type),
                agent_name=visible_agent.name,
                agent_description=visible_agent.description,
                release_id=session.release_id,
                latest_release_id=visible_agent.active_release_id,
                is_stale=session_service.is_session_stale(
                    session, visible_agent.active_release_id
                ),
                migrated_to_session_id=session.migrated_to_session_id,
                status=session.status,
                runtime_status=session.runtime_status,
                title=session.title,
                is_pinned=session.is_pinned,
                created_at=session.created_at.replace(tzinfo=UTC).isoformat(),
                updated_at=session.updated_at.replace(tzinfo=UTC).isoformat(),
            )
            for session in sessions
            if (visible_agent := visible_agents.get(session.agent_id)) is not None
        ],
        total=len(sessions),
    )


class ChatBootstrapResponse(BaseModel):
    """Aggregated payload for bootstrapping the Chat page in one request."""

    agent: AgentResponse
    llm: LLMUsableResponse | None
    sessions: list[SessionListItem]
    projects: list[ProjectResponse]
    chat_surfaces: list[ChatSurfaceDescriptor]
    web_search_providers: list[WebSearchProviderOption]


@router.get(
    "/client/agents/{agent_id}/chat-bootstrap",
    response_model=ChatBootstrapResponse,
)
async def get_chat_bootstrap(
    agent_id: int,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ChatBootstrapResponse:
    """Bootstrap the Chat page with a single aggregated response.

    Merges agent detail, LLM config, sessions, projects, chat surfaces,
    and web search providers into one payload to eliminate 6 separate
    HTTP round-trips on page load.
    """
    try:
        agent = AgentService(db).require_client_visible_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    AccessService(db).require_agent_access(
        user=current_user,
        agent=agent,
        access_level=AccessLevel.USE,
    )

    agent_data = _serialize_client_agent_response(
        agent,
        model_display=_resolve_model_display(db, agent.llm_id, agent.model_name),
    )

    llm_data: LLMUsableResponse | None = None
    if agent.llm_id is not None:
        llm_row = llm_crud.get(agent.llm_id, db)
        if llm_row is not None:
            llm_data = LLMUsableResponse.model_validate(llm_row)

    sessions_data: list[SessionListItem] = []
    if current_user.id is not None:
        session_svc = SessionService(db)
        raw_sessions = session_svc.get_sessions_by_user(
            user_id=current_user.id,
            agent_id=agent_id,
            session_type="client",
            limit=50,
        )
        for s in raw_sessions:
            sessions_data.append(
                SessionListItem(
                    session_id=s.session_id,
                    agent_id=s.agent_id,
                    type=cast("Literal['client', 'studio_test']", s.type),
                    release_id=s.release_id,
                    latest_release_id=agent.active_release_id,
                    is_stale=session_svc.is_session_stale(s, agent.active_release_id),
                    migrated_to_session_id=s.migrated_to_session_id,
                    project_id=s.project_id,
                    workspace_id=s.workspace_id,
                    workspace_scope=SessionService.get_workspace_scope(s),
                    test_workspace_hash=None,
                    status=s.status,
                    runtime_status=s.runtime_status,
                    title=s.title,
                    is_pinned=s.is_pinned,
                    created_at=s.created_at.replace(tzinfo=UTC).isoformat(),
                    updated_at=s.updated_at.replace(tzinfo=UTC).isoformat(),
                )
            )

    project_svc = ProjectService(db)
    projects_data: list[ProjectResponse] = []
    for project in project_svc.list_projects(user=current_user, agent_id=agent_id):
        projects_data.append(
            ProjectResponse(
                id=project.id or 0,
                project_id=project.project_id,
                agent_id=project.agent_id,
                name=project.name,
                description=project.description,
                workspace_id=project.workspace_id,
                can_edit=project_svc.has_project_access(
                    user=current_user,
                    project=project,
                    access_level=AccessLevel.EDIT,
                ),
                created_at=project.created_at.replace(tzinfo=UTC).isoformat(),
                updated_at=project.updated_at.replace(tzinfo=UTC).isoformat(),
            )
        )

    ext_svc = ExtensionService(db)
    bindings = ext_svc.list_agent_bindings(agent_id)
    chat_surfaces: list[ChatSurfaceDescriptor] = []

    installations_cache: dict[int, Any] = {}
    for b in bindings:
        if not b.enabled:
            continue
        iid = b.extension_installation_id
        if iid not in installations_cache:
            installations_cache[iid] = ext_svc.get_installation(iid)
        installation = installations_cache[iid]
        if installation is None or installation.status != "active":
            continue

        manifest = json.loads(installation.manifest_json)
        for item in _build_contribution_items(manifest):
            if item.get("type") == "chat_surface":
                chat_surfaces.append(
                    ChatSurfaceDescriptor(
                        installation_id=installation.id or 0,
                        package_id=installation.package_id,
                        surface_key=item.get("key") or "",
                        display_name=item.get("name", ""),
                        logo_url=ext_svc.get_installation_logo_url(installation),
                        description=item.get("description") or installation.description,
                        min_width=item.get("min_width"),
                        icon=item.get("icon"),
                    )
                )

    web_search_providers: list[WebSearchProviderOption] = []
    for wb in WebSearchService(db).list_agent_bindings(agent_id):
        if not wb.effective_enabled:
            continue
        manifest_info = wb.manifest or {}
        web_search_providers.append(
            WebSearchProviderOption(
                provider_key=wb.provider_key,
                name=manifest_info.get("name", wb.provider_key),
                logo_url=manifest_info.get("logo_url"),
            )
        )

    return ChatBootstrapResponse(
        agent=AgentResponse.model_validate(agent_data),
        llm=llm_data,
        sessions=sessions_data,
        projects=projects_data,
        chat_surfaces=chat_surfaces,
        web_search_providers=web_search_providers,
    )
