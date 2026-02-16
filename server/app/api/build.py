"""API endpoints for agent building/modification.

This module provides endpoints for building and modifying agents
using LLM-powered natural language interactions.
All endpoints require authentication.
"""

import logging
import traceback
from datetime import datetime, timezone

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.schemas.build import BuildChatRequest
from app.schemas.schemas import StreamEvent, StreamEventType
from app.services.build_service import BuildService
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlmodel import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/build/chat/stream")
async def build_chat_stream(
    request: BuildChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Streaming endpoint for building/modifying agents.

    Returns a Server-Sent Events (SSE) stream with events:
    - reasoning: Chain-of-Thought updates (for thinking models)
    - response: Response text from LLM
    - reason: Reason for the changes
    - updated_scenes: Complete updated agent JSON configuration in delta field
    - error: Error details

    Args:
        request: Build chat request with content and optional agent ID.
        db: Database session.

    Returns:
        StreamingResponse with SSE events.
    """
    logger.info(f"Received build chat stream request. Agent ID: {request.agent_id}")

    async def event_generator():
        try:
            # Load existing agent if agent_id provided
            agent_detail = None
            if request.agent_id:
                from app.crud.agent import agent as agent_crud
                from app.crud.connection import connection as connection_crud
                from app.crud.scene import scene as scene_crud
                from app.crud.subscene import subscene as subscene_crud
                from app.schemas.schemas import (
                    ConnectionResponse,
                    SceneGraphResponse,
                    SubsceneWithConnectionsResponse,
                )

                # Convert agent_id from string to int
                agent_id_int = int(request.agent_id)
                agent = agent_crud.get(agent_id_int, db)

                if not agent:
                    error_event = StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Agent with ID {request.agent_id} not found",
                        create_time=datetime.now(timezone.utc).isoformat(),
                    )
                    yield f"data: {error_event.json()}\n\n"
                    return

                # Build agent detail with scenes
                scenes = scene_crud.get_by_agent_id(agent_id_int, db)

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
                        connections = connection_crud.get_by_from_subscene(
                            subscene.name, db
                        )

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
                                    ConnectionResponse.from_orm(conn)
                                    for conn in connections
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
                            state="inactive",  # Default state
                            agent_id=scene.agent_id or agent_id_int,
                            subscenes=subscenes_with_connections,
                            created_at=scene.created_at,
                            updated_at=scene.updated_at,
                        )
                    )

                from app.schemas.schemas import AgentDetailResponse

                if not agent.id:
                    error_event = StreamEvent(
                        type=StreamEventType.ERROR,
                        error=f"Agent {request.agent_id} has no ID",
                        create_time=datetime.now(timezone.utc).isoformat(),
                    )
                    yield f"data: {error_event.json()}\n\n"
                    return

                agent_detail = AgentDetailResponse(
                    id=agent.id,
                    name=agent.name,
                    description=agent.description,
                    llm_id=agent.llm_id,
                    model_name=agent.model_name,
                    is_active=agent.is_active,
                    max_iteration=agent.max_iteration,
                    created_at=agent.created_at,
                    updated_at=agent.updated_at,
                    scenes=scenes_graph_responses,
                )

            # Determine which LLM to use
            llm_id = agent_detail.llm_id if agent_detail else request.llm_id

            if not llm_id:
                error_event = StreamEvent(
                    type=StreamEventType.ERROR,
                    error="LLM ID is required. Please specify llm_id or provide an agent with configured LLM.",
                    create_time=datetime.now(timezone.utc).isoformat(),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Stream build responses
            for event in BuildService.stream_build_chat(
                agent_detail=agent_detail,
                message=request.content,
                llm_id=llm_id,
                db=db,
            ):
                yield f"data: {event.json()}\n\n"

        except Exception as e:
            logger.error(f"Error in build chat stream: {e}")
            logger.error(traceback.format_exc())
            error_event = StreamEvent(
                type=StreamEventType.ERROR,
                error=str(e),
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            yield f"data: {error_event.json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
