"""API endpoints for agent management."""

import logging
from datetime import UTC
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.crud.llm import llm as llm_crud
from app.models.agent_release import AgentRelease
from app.models.user import User
from app.schemas.schemas import (
    AgentCreate,
    AgentDraftStateResponse,
    AgentPublishRequest,
    AgentReleaseResponse,
    AgentResponse,
    AgentServingUpdate,
    AgentUpdate,
)
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

logger = logging.getLogger(__name__)

router = APIRouter()


def _serialize_agent_response(
    agent: Any,
    *,
    model_display: str,
    active_release_version: int | None = None,
) -> dict[str, Any]:
    """Serialize one agent row into the shared response payload shape."""
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "llm_id": agent.llm_id,
        "session_idle_timeout_minutes": agent.session_idle_timeout_minutes,
        "sandbox_timeout_seconds": agent.sandbox_timeout_seconds,
        "compact_threshold_percent": agent.compact_threshold_percent,
        "active_release_id": agent.active_release_id,
        "active_release_version": active_release_version,
        "serving_enabled": agent.serving_enabled,
        "model_name": model_display,
        "is_active": agent.is_active,
        "max_iteration": agent.max_iteration,
        "tool_ids": agent.tool_ids,
        "skill_ids": agent.skill_ids,
        "created_at": agent.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": agent.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def _resolve_model_display(agent: Any, db: Session) -> str:
    """Resolve one agent row into the display string shown in Studio."""
    model_display = agent.model_name or "N/A"
    if agent.llm_id:
        llm = llm_crud.get(agent.llm_id, db)
        if llm:
            model_display = f"{llm.name} ({llm.model})"
    return model_display


@router.get("/agents", response_model=list[AgentResponse])
async def get_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get all agents with pagination."""
    del current_user
    agents = agent_crud.get_all(db, skip=skip, limit=limit)
    result = []
    for agent in agents:
        release_version = None
        if agent.active_release_id is not None:
            release = db.get(AgentRelease, agent.active_release_id)
            if release is not None:
                release_version = release.version

        result.append(
            _serialize_agent_response(
                agent,
                model_display=_resolve_model_display(agent, db),
                active_release_version=release_version,
            )
        )
    return result


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    agent_data: AgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new agent."""
    llm = llm_crud.get(agent_data.llm_id, db)
    if not llm:
        raise HTTPException(
            status_code=400,
            detail=f"LLM with ID {agent_data.llm_id} does not exist",
        )
    existing_agent = agent_crud.get_by_name(agent_data.name, db)
    if existing_agent:
        raise HTTPException(
            status_code=400, detail="Agent with this name already exists"
        )

    agent = agent_crud.create(
        db,
        name=agent_data.name,
        description=agent_data.description,
        llm_id=agent_data.llm_id,
        session_idle_timeout_minutes=agent_data.session_idle_timeout_minutes,
        sandbox_timeout_seconds=agent_data.sandbox_timeout_seconds,
        compact_threshold_percent=agent_data.compact_threshold_percent,
        is_active=agent_data.is_active,
        max_iteration=agent_data.max_iteration,
    )
    AgentSnapshotService(db).save_draft(
        agent.id or 0,
        saved_by=current_user.username,
    )

    return _serialize_agent_response(
        agent,
        model_display=_resolve_model_display(agent, db),
    )


@router.get(
    "/agents/{agent_id}/draft-state",
    response_model=AgentDraftStateResponse,
)
async def get_agent_draft_state(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return saved-draft and release metadata for one agent editor."""
    del current_user
    try:
        return AgentSnapshotService(db).get_draft_state(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/agents/{agent_id}/drafts/save",
    response_model=AgentDraftStateResponse,
)
async def save_agent_draft(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Persist the current normalized agent state as the saved draft."""
    snapshot_service = AgentSnapshotService(db)
    try:
        snapshot_service.save_draft(agent_id, saved_by=current_user.username)
        return snapshot_service.get_draft_state(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/agents/{agent_id}/releases",
    response_model=list[AgentReleaseResponse],
)
async def list_agent_releases(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List immutable releases for one agent."""
    del current_user
    try:
        return AgentSnapshotService(db).list_releases(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/agents/{agent_id}/releases",
    response_model=AgentDraftStateResponse,
)
async def publish_agent_release(
    agent_id: int,
    payload: AgentPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Publish the current saved draft as the next immutable release."""
    try:
        return AgentSnapshotService(db).publish_saved_draft(
            agent_id,
            release_note=payload.release_note,
            published_by=current_user.username,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "already published" in detail else 404
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.patch("/agents/{agent_id}/serving", response_model=AgentResponse)
async def update_agent_serving_state(
    agent_id: int,
    payload: AgentServingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Enable or disable one agent for end-user traffic."""
    del current_user
    try:
        updated_agent = AgentService(db).set_serving_enabled(
            agent_id,
            payload.serving_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return _serialize_agent_response(
        updated_agent,
        model_display=_resolve_model_display(updated_agent, db),
    )


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: int,
    agent_data: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update an existing agent."""
    del current_user
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if agent_data.llm_id is not None:
        llm = llm_crud.get(agent_data.llm_id, db)
        if not llm:
            raise HTTPException(
                status_code=400,
                detail=f"LLM with ID {agent_data.llm_id} does not exist",
            )
    if agent_data.name and agent_data.name != agent.name:
        existing_agent = agent_crud.get_by_name(agent_data.name, db)
        if existing_agent:
            raise HTTPException(
                status_code=400, detail="Agent with this name already exists"
            )

    update_data: dict[str, Any] = {}
    if agent_data.name is not None:
        update_data["name"] = agent_data.name
    if agent_data.description is not None:
        update_data["description"] = agent_data.description
    if agent_data.llm_id is not None:
        update_data["llm_id"] = agent_data.llm_id
    if agent_data.session_idle_timeout_minutes is not None:
        update_data["session_idle_timeout_minutes"] = (
            agent_data.session_idle_timeout_minutes
        )
    if agent_data.sandbox_timeout_seconds is not None:
        update_data["sandbox_timeout_seconds"] = agent_data.sandbox_timeout_seconds
    if agent_data.compact_threshold_percent is not None:
        update_data["compact_threshold_percent"] = agent_data.compact_threshold_percent
    if agent_data.is_active is not None:
        update_data["is_active"] = agent_data.is_active
    if agent_data.max_iteration is not None:
        update_data["max_iteration"] = agent_data.max_iteration
    if "tool_ids" in agent_data.__fields_set__:
        update_data["tool_ids"] = agent_data.tool_ids
    if "skill_ids" in agent_data.__fields_set__:
        update_data["skill_ids"] = agent_data.skill_ids

    updated_agent = agent_crud.update(agent_id, db, **update_data)
    if not updated_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _serialize_agent_response(
        updated_agent,
        model_display=_resolve_model_display(updated_agent, db),
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single agent by ID."""
    del current_user
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return _serialize_agent_response(
        agent,
        model_display=_resolve_model_display(agent, db),
    )


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an agent and all associated saved state."""
    del current_user
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    AgentSnapshotService(db).delete_agent_state(agent_id)
    db.delete(agent)
    db.commit()
    return None
