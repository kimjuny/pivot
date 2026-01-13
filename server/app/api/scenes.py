"""API endpoints for scene management.

This module provides read-only operations for scenes.
All CRUD operations (create, update, delete) are not used by the frontend.
"""
import logging

from app.api.dependencies import get_db
from app.crud.connection import connection as connection_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from app.schemas.schemas import (
    ConnectionResponse,
    SceneGraphResponse,
    SceneResponse,
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
