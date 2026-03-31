"""Consumer-facing API endpoints for visible published agents."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Any, Literal, cast

from app.api.auth import get_current_user
from app.crud.llm import llm as llm_crud
from app.schemas.schemas import AgentResponse
from app.schemas.session import (
    ConsumerSessionListItem,
    ConsumerSessionListResponse,
)
from app.services.agent_service import AgentService
from app.services.session_service import SessionService
from fastapi import APIRouter, Depends, HTTPException

from .dependencies import get_db

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session

router = APIRouter()


def _serialize_consumer_agent_response(
    agent: Any,
    *,
    model_display: str,
) -> dict[str, Any]:
    """Serialize one Consumer-visible agent into the existing response shape."""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "llm_id": agent.llm_id,
        "skill_resolution_llm_id": agent.skill_resolution_llm_id,
        "session_idle_timeout_minutes": agent.session_idle_timeout_minutes,
        "sandbox_timeout_seconds": agent.sandbox_timeout_seconds,
        "compact_threshold_percent": agent.compact_threshold_percent,
        "active_release_id": agent.active_release_id,
        "serving_enabled": agent.serving_enabled,
        "model_name": model_display,
        "is_active": agent.is_active,
        "max_iteration": agent.max_iteration,
        "tool_ids": agent.tool_ids,
        "skill_ids": agent.skill_ids,
        "created_at": agent.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": agent.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def _resolve_model_display(
    db: Session, llm_id: int | None, fallback: str | None
) -> str:
    """Resolve the visible model label shown in Consumer agent cards."""
    model_display = fallback or "N/A"
    if llm_id is None:
        return model_display

    llm = llm_crud.get(llm_id, db)
    if llm is None:
        return model_display
    return f"{llm.name} ({llm.model})"


@router.get("/consumer/agents", response_model=list[AgentResponse])
async def list_consumer_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all agents currently visible in the Consumer product."""
    del current_user
    service = AgentService(db)
    return [
        _serialize_consumer_agent_response(
            agent,
            model_display=_resolve_model_display(db, agent.llm_id, agent.model_name),
        )
        for agent in service.list_consumer_visible_agents()
    ]


@router.get("/consumer/agents/{agent_id}", response_model=AgentResponse)
async def get_consumer_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return one Consumer-visible agent by identifier."""
    del current_user
    try:
        agent = AgentService(db).require_consumer_visible_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _serialize_consumer_agent_response(
        agent,
        model_display=_resolve_model_display(db, agent.llm_id, agent.model_name),
    )


@router.get("/consumer/sessions", response_model=ConsumerSessionListResponse)
async def list_consumer_sessions(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConsumerSessionListResponse:
    """List the current user's recent sessions for Consumer-visible agents."""
    visible_agents = {
        agent.id: agent
        for agent in AgentService(db).list_consumer_visible_agents()
        if agent.id is not None
    }
    sessions = SessionService(db).get_sessions_by_user(
        user=current_user.username,
        agent_ids=list(visible_agents),
        session_type="consumer",
        limit=limit,
    )

    return ConsumerSessionListResponse(
        sessions=[
            ConsumerSessionListItem(
                session_id=session.session_id,
                agent_id=session.agent_id,
                type=cast(Literal["consumer", "studio_test"], session.type),
                agent_name=visible_agent.name,
                agent_description=visible_agent.description,
                release_id=session.release_id,
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
