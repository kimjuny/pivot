"""API endpoints for scene management.

This module provides CRUD operations for scenes.
"""
import logging
from datetime import timezone

from app.api.dependencies import get_db
from app.crud.connection import connection as connection_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from app.schemas.schemas import (
    ConnectionResponse,
    ConnectionUpdate,
    SceneCreate,
    SceneGraphResponse,
    SceneResponse,
    SubsceneResponse,
    SubsceneUpdate,
    SubsceneWithConnectionsResponse,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/scenes", response_model=list[SceneResponse])
async def get_scenes(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all scenes with pagination.

    Args:
        skip: Number of scenes to skip.
        limit: Maximum number of scenes to return.
        db: Database session.

    Returns:
        A list of scenes.
    """
    scenes = scene_crud.get_all(db, skip=skip, limit=limit)
    return [SceneResponse.from_orm(scene) for scene in scenes]


@router.post("/scenes", response_model=SceneResponse, status_code=201)
async def create_scene(
    scene_data: SceneCreate,
    db: Session = Depends(get_db)
):
    """Create a new scene.

    Args:
        scene_data: Scene creation data containing name, description, and agent_id.
        db: Database session.

    Returns:
        The created scene with ID populated.

    Raises:
        HTTPException: If a scene with the same name already exists for the same agent (400).
    """
    existing_scene = scene_crud.get_by_name(scene_data.name, db)
    if existing_scene:
        raise HTTPException(status_code=400, detail="Scene with this name already exists for this agent")

    scene = scene_crud.create(
        db,
        name=scene_data.name,
        description=scene_data.description,
        agent_id=scene_data.agent_id
    )
    return {
        "id": scene.id,
        "name": scene.name,
        "description": scene.description,
        "agent_id": scene.agent_id,
        "created_at": scene.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": scene.updated_at.replace(tzinfo=timezone.utc).isoformat()
    }


@router.get("/scenes/{scene_id}/graph", response_model=SceneGraphResponse)
async def get_scene_graph(
    scene_id: int,
    db: Session = Depends(get_db)
):
    """Get the complete scene graph with all subscenes and their connections.

    Args:
        scene_id: The ID of the scene.
        db: Database session.

    Returns:
        The scene graph containing all subscenes and connections.

    Raises:
        HTTPException: If the scene is not found (404).
    """
    # Get scene
    scene = scene_crud.get(scene_id, db)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    # Get all subscenes for this scene
    subscenes = subscene_crud.get_by_scene_id(scene_id, db)

    # Build subscenes with connections
    subscenes_with_connections = []
    for subscene in subscenes:
        # Get all connections where this subscene is the source
        connections = connection_crud.get_by_from_subscene(subscene.name, db)

        # Build subscene with connections response
        subscenes_with_connections.append(SubsceneWithConnectionsResponse(
            id=subscene.id,
            name=subscene.name,
            type=subscene.type,
            state=subscene.state,
            description=subscene.description,
            mandatory=subscene.mandatory,
            objective=subscene.objective,
            scene_id=subscene.scene_id,
            connections=[ConnectionResponse.from_orm(conn) for conn in connections],
            created_at=subscene.created_at,
            updated_at=subscene.updated_at
        ))

    # Build scene graph response with all required fields
    return {
        "id": scene.id,
        "name": scene.name,
        "description": scene.description,
        "agent_id": scene.agent_id,
        "scenes": subscenes_with_connections,
        "created_at": scene.created_at,
        "updated_at": scene.updated_at
    }


@router.put("/scenes/{scene_id}/subscenes/{subscene_name}", response_model=SubsceneResponse)
async def update_subscene(
    scene_id: int,
    subscene_name: str,
    subscene_data: SubsceneUpdate,
    db: Session = Depends(get_db)
):
    """Update a subscene within a scene.

    Args:
        scene_id: The ID of the scene.
        subscene_name: The name of the subscene to update.
        subscene_data: Subscene update data.
        db: Database session.

    Returns:
        The updated subscene.

    Raises:
        HTTPException: If the scene or subscene is not found (404).
    """
    scene = scene_crud.get(scene_id, db)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    subscene = subscene_crud.get_by_name(subscene_name, scene_id, db)
    if not subscene or subscene.id is None:
        raise HTTPException(status_code=404, detail="Subscene not found")

    updated_subscene = subscene_crud.update(subscene.id, db, **subscene_data.dict(exclude_none=True))
    if not updated_subscene:
        raise HTTPException(status_code=404, detail="Failed to update subscene")

    return SubsceneResponse.from_orm(updated_subscene)


@router.put("/scenes/{scene_id}/connections", response_model=ConnectionResponse)
async def update_connection(
    scene_id: int,
    connection_data: ConnectionUpdate,
    db: Session = Depends(get_db)
):
    """Update a connection within a scene.

    Args:
        scene_id: The ID of the scene.
        connection_data: Connection update data including from_subscene and to_subscene.
        db: Database session.

    Returns:
        The updated connection.

    Raises:
        HTTPException: If the scene or connection is not found (404).
    """
    scene = scene_crud.get(scene_id, db)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    if not connection_data.from_subscene or not connection_data.to_subscene:
        raise HTTPException(status_code=400, detail="from_subscene and to_subscene are required")

    connections = connection_crud.get_by_from_subscene(connection_data.from_subscene, db)
    connection = next((c for c in connections if c.to_subscene == connection_data.to_subscene), None)

    if not connection or connection.id is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    update_data = connection_data.dict(exclude_none=True, exclude={"from_subscene", "to_subscene"})
    updated_connection = connection_crud.update(connection.id, db, **update_data)
    if not updated_connection:
        raise HTTPException(status_code=404, detail="Failed to update connection")

    return ConnectionResponse.from_orm(updated_connection)
