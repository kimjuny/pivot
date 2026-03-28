"""API endpoints for agent management.

This module provides CRUD operations for agents.
All endpoints require authentication.
"""

import logging
from datetime import UTC
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.crud.connection import connection as connection_crud
from app.crud.llm import llm as llm_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from app.models.agent import Connection
from app.models.agent_release import AgentRelease
from app.models.user import User
from app.schemas.schemas import (
    AgentCreate,
    AgentDetailResponse,
    AgentDraftStateResponse,
    AgentPublishRequest,
    AgentReleaseResponse,
    AgentResponse,
    AgentSceneListUpdate,
    AgentServingUpdate,
    AgentUpdate,
    ConnectionResponse,
    SceneGraphResponse,
    SceneResponse,
    SubsceneWithConnectionsResponse,
)
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

# Get logger for this module
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
        "skill_resolution_llm_id": agent.skill_resolution_llm_id,
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


@router.get("/agents", response_model=list[AgentResponse])
async def get_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get all agents with pagination.

    Args:
        skip: Number of agents to skip.
        limit: Maximum number of agents to return.
        db: Database session.

    Returns:
        A list of agents.
    """
    agents = agent_crud.get_all(db, skip=skip, limit=limit)
    result = []
    for agent in agents:
        # Get LLM name for display
        model_display = agent.model_name or "N/A"
        if agent.llm_id:
            llm = llm_crud.get(agent.llm_id, db)
            if llm:
                model_display = f"{llm.name} ({llm.model})"

        release_version = None
        if agent.active_release_id is not None:
            release = db.get(AgentRelease, agent.active_release_id)
            if release is not None:
                release_version = release.version

        result.append(
            _serialize_agent_response(
                agent,
                model_display=model_display,
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
    """Create a new agent.

    Args:
        agent_data: Agent creation data containing name, description, and llm_id.
        db: Database session.

    Returns:
        The created agent with ID populated.

    Raises:
        HTTPException: If an agent with the same name already exists (400) or if the LLM does not exist (400).
    """
    # Validate LLM exists
    llm = llm_crud.get(agent_data.llm_id, db)
    if not llm:
        raise HTTPException(
            status_code=400,
            detail=f"LLM with ID {agent_data.llm_id} does not exist",
        )
    if agent_data.skill_resolution_llm_id is not None:
        skill_llm = llm_crud.get(agent_data.skill_resolution_llm_id, db)
        if not skill_llm:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Skill resolution LLM with ID "
                    f"{agent_data.skill_resolution_llm_id} does not exist"
                ),
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
        skill_resolution_llm_id=agent_data.skill_resolution_llm_id,
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

    # Get LLM name for display
    model_display = agent.model_name or "N/A"
    if agent.llm_id:
        llm = llm_crud.get(agent.llm_id, db)
        if llm:
            model_display = f"{llm.name} ({llm.model})"

    return _serialize_agent_response(agent, model_display=model_display)


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

    model_display = updated_agent.model_name or "N/A"
    if updated_agent.llm_id:
        llm = llm_crud.get(updated_agent.llm_id, db)
        if llm:
            model_display = f"{llm.name} ({llm.model})"
    return _serialize_agent_response(updated_agent, model_display=model_display)


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: int,
    agent_data: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update an existing agent.

    Args:
        agent_id: The ID of the agent to update.
        agent_data: Agent update data containing optional fields to update.
        db: Database session.

    Returns:
        The updated agent.

    Raises:
        HTTPException: If the agent is not found (404) or if the new name already exists (400).
    """
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Validate LLM exists if provided
    if agent_data.llm_id is not None:
        llm = llm_crud.get(agent_data.llm_id, db)
        if not llm:
            raise HTTPException(
                status_code=400,
                detail=f"LLM with ID {agent_data.llm_id} does not exist",
            )
    if agent_data.skill_resolution_llm_id is not None:
        skill_llm = llm_crud.get(agent_data.skill_resolution_llm_id, db)
        if not skill_llm:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Skill resolution LLM with ID "
                    f"{agent_data.skill_resolution_llm_id} does not exist"
                ),
            )

    # Check if name change conflicts with existing agent
    if agent_data.name and agent_data.name != agent.name:
        existing_agent = agent_crud.get_by_name(agent_data.name, db)
        if existing_agent:
            raise HTTPException(
                status_code=400, detail="Agent with this name already exists"
            )

    # Update only provided fields
    update_data: dict[str, Any] = {}
    if agent_data.name is not None:
        update_data["name"] = agent_data.name
    if agent_data.description is not None:
        update_data["description"] = agent_data.description
    if agent_data.llm_id is not None:
        update_data["llm_id"] = agent_data.llm_id
    if agent_data.skill_resolution_llm_id is not None:
        update_data["skill_resolution_llm_id"] = agent_data.skill_resolution_llm_id
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
    # tool_ids uses a sentinel check: the field is present in the payload
    # even when set to None (meaning "remove all restrictions"), so we check
    # via __fields_set__ rather than `is not None`.
    if "tool_ids" in agent_data.__fields_set__:
        update_data["tool_ids"] = agent_data.tool_ids
    if "skill_ids" in agent_data.__fields_set__:
        update_data["skill_ids"] = agent_data.skill_ids

    updated_agent = agent_crud.update(agent_id, db, **update_data)
    if not updated_agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get LLM name for display
    model_display = updated_agent.model_name or "N/A"
    if updated_agent.llm_id:
        llm = llm_crud.get(updated_agent.llm_id, db)
        if llm:
            model_display = f"{llm.name} ({llm.model})"

    return _serialize_agent_response(updated_agent, model_display=model_display)


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse)
async def get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single agent by ID with full details (scenes and graphs).

    Args:
        agent_id: The ID of the agent to retrieve.
        db: Database session.

    Returns:
        The agent with all its scenes and their graphs.

    Raises:
        HTTPException: If the agent is not found (404).
    """
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get LLM name for display
    model_display = agent.model_name or "N/A"
    if agent.llm_id:
        llm = llm_crud.get(agent.llm_id, db)
        if llm:
            model_display = f"{llm.name} ({llm.model})"

    # Get all scenes for this agent
    scenes = scene_crud.get_by_agent_id(agent_id, db)

    scenes_graph_responses = []
    for scene in scenes:
        if not scene.id:
            continue

        # Get all subscenes for this scene
        subscenes = subscene_crud.get_by_scene_id(scene.id, db)

        # Build subscenes with connections
        subscenes_with_connections = []
        for subscene in subscenes:
            # Get all connections where this subscene is the source
            connections = connection_crud.get_by_from_subscene(subscene.name, db)

            # Build subscene with connections response
            subscenes_with_connections.append(
                SubsceneWithConnectionsResponse(
                    id=subscene.id,
                    name=subscene.name,
                    type=subscene.type,
                    state=subscene.state,
                    description=subscene.description,
                    mandatory=subscene.mandatory,
                    objective=subscene.objective,
                    scene_id=subscene.scene_id,
                    connections=[
                        ConnectionResponse.model_validate(conn) for conn in connections
                    ],
                    created_at=subscene.created_at,
                    updated_at=subscene.updated_at,
                )
            )

        scenes_graph_responses.append(
            SceneGraphResponse(
                id=scene.id,
                name=scene.name,
                description=scene.description,
                state="inactive",  # Default state as it's not stored in DB
                agent_id=scene.agent_id or agent_id,
                subscenes=subscenes_with_connections,
                created_at=scene.created_at,
                updated_at=scene.updated_at,
            )
        )

    response = _serialize_agent_response(agent, model_display=model_display)
    response["scenes"] = scenes_graph_responses
    return response


@router.put("/agents/{agent_id}/scenes", response_model=list[SceneResponse])
async def update_agent_scenes(
    agent_id: int,
    scenes_update: AgentSceneListUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Bulk update scenes for an agent.

    Syncs the provided list of scenes with the agent's existing scenes.
    - Creates new scenes (if name doesn't exist for this agent).
    - Updates existing scenes (if name exists and belongs to agent).
    - Deletes scenes not in the list (belonging to agent).
    - If graph data is provided for a scene, updates its subscenes and connections.

    Preserves subscenes for updated scenes unless graph data is explicitly provided.
    """
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get current scenes
    current_scenes = scene_crud.get_by_agent_id(agent_id, db)
    current_scenes_map = {s.name: s for s in current_scenes}

    input_scenes_data = scenes_update.scenes
    input_scenes_names = {s.name for s in input_scenes_data}

    # Process inputs

    # 1. Update or Create
    for scene_data in input_scenes_data:
        existing_scene = current_scenes_map.get(scene_data.name)
        target_scene = None

        if existing_scene:
            # Update description if changed
            if (
                existing_scene.id
                and existing_scene.description != scene_data.description
            ):
                scene_crud.update(
                    existing_scene.id, db, description=scene_data.description
                )
            target_scene = existing_scene
        else:
            # Create
            # Check if name is globally unique (consistent with create_scene logic)
            global_existing = scene_crud.get_by_name(scene_data.name, db)
            if global_existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Scene '{scene_data.name}' already exists (possibly for another agent)",
                )

            target_scene = scene_crud.create(
                db,
                name=scene_data.name,
                description=scene_data.description,
                agent_id=agent_id,
            )

        # Handle Graph Update if provided and target_scene is valid
        if target_scene and target_scene.id and scene_data.graph is not None:
            scene_id = target_scene.id

            # Delete all existing connections for this scene
            existing_subscenes = subscene_crud.get_by_scene_id(scene_id, db)
            for subscene in existing_subscenes:
                if subscene.id:
                    connections = connection_crud.get_by_from_subscene(
                        subscene.name, db
                    )
                    for conn in connections:
                        if conn.id:
                            connection_crud.delete(conn.id, db)

            # Delete all existing subscenes
            for subscene in existing_subscenes:
                if subscene.id:
                    subscene_crud.delete(subscene.id, db)

            # Create new subscenes
            for subscene_item in scene_data.graph:
                subscene_crud.create(
                    db,
                    name=subscene_item.name,
                    type=subscene_item.type,
                    state=subscene_item.state,
                    description=subscene_item.description,
                    mandatory=subscene_item.mandatory,
                    objective=subscene_item.objective,
                    scene_id=scene_id,
                )

            # Create new connections
            for subscene_item in scene_data.graph:
                for conn_item in subscene_item.connections:
                    connection_crud.create(
                        db,
                        name=conn_item.name,
                        condition=conn_item.condition,
                        from_subscene=subscene_item.name,
                        to_subscene=conn_item.to_subscene,
                        from_subscene_id=None,
                        to_subscene_id=None,
                        scene_id=scene_id,
                    )

    # 2. Delete missing
    for name, scene in current_scenes_map.items():
        if name not in input_scenes_names and scene.id:
            scene_crud.delete(scene.id, db)

    # Return final list
    # Re-fetch to get fresh data and consistent order
    scenes = scene_crud.get_by_agent_id(agent_id, db)
    return [
        {
            "id": scene.id,
            "name": scene.name,
            "description": scene.description,
            "agent_id": scene.agent_id,
            "created_at": scene.created_at.replace(tzinfo=UTC).isoformat(),
            "updated_at": scene.updated_at.replace(tzinfo=UTC).isoformat(),
        }
        for scene in scenes
    ]


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an agent and all associated data.

    Recursively deletes:
    1. Connections associated with the agent's scenes
    2. Subscenes associated with the agent's scenes
    3. Scenes associated with the agent
    4. Chat history associated with the agent
    5. The agent itself

    Args:
        agent_id: The ID of the agent to delete.
        db: Database session.

    Raises:
        HTTPException: If the agent is not found (404).
    """
    # Check if agent exists
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get all scenes
    scenes = scene_crud.get_by_agent_id(agent_id, db)

    for scene in scenes:
        if not scene.id:
            continue

        # 1. Delete Connections
        # We need to find connections by scene_id.
        connections = db.exec(
            select(Connection).where(Connection.scene_id == scene.id)
        ).all()
        for conn in connections:
            db.delete(conn)

        # 2. Delete Subscenes
        subscenes = subscene_crud.get_by_scene_id(scene.id, db)
        for subscene in subscenes:
            db.delete(subscene)

        # 3. Delete Scene
        db.delete(scene)

    AgentSnapshotService(db).delete_agent_state(agent_id)

    # 4. Delete Agent
    db.delete(agent)

    db.commit()
    # Explicitly return None to ensure empty body for 204
    return None
