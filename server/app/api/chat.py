"""API endpoints for agent chat and chat history management.

This module provides endpoints for chatting with agents and managing
chat history, including conversation state persistence.
"""

import logging
import traceback
import uuid
from datetime import datetime, timezone

from app.llm_globals import get_default_llm, get_llm
from app.models.agent import (
    Connection as DBConnection,
    Scene as DBScene,
    Subscene as DBSubscene,
)
from app.schemas.schemas import (
    AgentDetailResponse,
    ConnectionResponse,
    PreviewChatRequest,
    SceneGraphResponse,
    StreamEvent,
    StreamEventType,
    SubsceneWithConnectionsResponse,
)
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from core.agent.agent import Agent as CoreAgent
from core.agent.base.stream import AgentResponseChunkType
from core.agent.plan.connection import Connection as CoreConnection
from core.agent.plan.scene import Scene as CoreScene
from core.agent.plan.subscene import Subscene as CoreSubscene, SubsceneType

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


def convert_db_to_core_scene(db_scene: DBScene, db_subscenes: list[DBSubscene], db_connections: list[DBConnection]) -> CoreScene:
    """Convert database models to core scene models.

    This function transforms database models (SQLModel) into core domain models
    used by the agent framework. It builds a complete scene graph with
    all subscenes and their connections.

    Args:
        db_scene: Database scene model.
        db_subscenes: List of database subscene models.
        db_connections: List of database connection models.

    Returns:
        CoreScene: Core scene model with subscenes and connections.
    """
    # Create a map of subscene name to subscene object
    {db_subscene.name: db_subscene for db_subscene in db_subscenes}

    # Create core subscenes with connections
    core_subscenes = []
    for db_subscene in db_subscenes:
        # Create core subscene
        core_subscene = CoreSubscene(
            name=db_subscene.name,
            subscene_type=SubsceneType(db_subscene.type),
            mandatory=db_subscene.mandatory,
            objective=db_subscene.objective or "",
        )

        # Get all connections for this subscene
        subscene_connections = [
            CoreConnection(
                name=conn.name,
                condition=conn.condition or "",
                from_subscene=conn.from_subscene,
                to_subscene=conn.to_subscene,
            )
            for conn in db_connections
            if conn.from_subscene == db_subscene.name
        ]

        # Add connections to subscene
        for connection in subscene_connections:
            core_subscene.add_connection(connection)

        core_subscenes.append(core_subscene)

    # Create core scene
    core_scene = CoreScene(
        name=db_scene.name, identification_condition=db_scene.description or ""
    )

    # Add subscenes to scene
    for core_subscene in core_subscenes:
        core_scene.add_subscene(core_subscene)

    return core_scene

def merge_graph_with_input(
    updated_scenes: list[CoreScene], input_agent_detail: AgentDetailResponse
) -> list[SceneGraphResponse]:
    """Merge updated core scenes with input agent detail to preserve IDs and structure.

    Args:
        updated_scenes: List of CoreScene objects from LLM output.
        input_agent_detail: The original input agent detail with IDs.

    Returns:
        List of SceneGraphResponse with IDs and timestamps populated.
    """
    # Create lookup maps for input data
    input_scene_map = {s.name: s for s in input_agent_detail.scenes}
    input_subscene_map: dict[str, dict[str, SubsceneWithConnectionsResponse]] = {}
    input_connection_map: dict[str, dict[str, dict[str, ConnectionResponse]]] = {}

    for scene in input_agent_detail.scenes:
        input_subscene_map[scene.name] = {ss.name: ss for ss in scene.subscenes}
        input_connection_map[scene.name] = {}
        for ss in scene.subscenes:
            # Map connections by to_subscene (assuming unique connection per target for simplicity)
            # Or better, key by (from_subscene, to_subscene, name)
            input_connection_map[scene.name][ss.name] = {}
            for conn in ss.connections:
                # Key by to_subscene and name to be more specific
                conn_key = f"{conn.to_subscene}|{conn.name}"
                input_connection_map[scene.name][ss.name][conn_key] = conn

    merged_scenes: list[SceneGraphResponse] = []
    current_time = datetime.now(timezone.utc)

    for core_scene in updated_scenes:
        # Match Scene
        input_scene = input_scene_map.get(core_scene.name)
        
        scene_id = input_scene.id if input_scene else f"new-{uuid.uuid4().hex[:8]}"
        created_at = input_scene.created_at if input_scene else current_time
        updated_at = current_time # Always update updated_at? Or only if changed? Simplified to now.
        agent_id = input_scene.agent_id if input_scene else input_agent_detail.id # Fallback to agent ID
        
        # Process Subscenes
        merged_subscenes: list[SubsceneWithConnectionsResponse] = []
        
        for core_subscene in core_scene.subscenes:
            input_subscene = None
            if input_scene:
                input_subscene = input_subscene_map.get(core_scene.name, {}).get(core_subscene.name)
            
            subscene_id = input_subscene.id if input_subscene else f"new-{uuid.uuid4().hex[:8]}"
            sub_created_at = input_subscene.created_at if input_subscene else current_time
            
            # Process Connections
            merged_connections: list[ConnectionResponse] = []
            for core_conn in core_subscene.connections:
                input_conn = None
                if input_scene and input_subscene:
                    conn_key = f"{core_conn.to_subscene}|{core_conn.name}"
                    input_conn = input_connection_map.get(core_scene.name, {}).get(core_subscene.name, {}).get(conn_key)
                    # Fallback: try matching just by to_subscene if name is empty in core
                    if not input_conn and not core_conn.name:
                        # Find first connection with matching to_subscene
                        conns = input_connection_map.get(core_scene.name, {}).get(core_subscene.name, {})
                        for _, v in conns.items():
                            if v.to_subscene == core_conn.to_subscene:
                                input_conn = v
                                break

                conn_id = input_conn.id if input_conn else f"new-{uuid.uuid4().hex[:8]}"
                conn_created_at = input_conn.created_at if input_conn else current_time
                
                merged_connections.append(
                    ConnectionResponse(
                        id=conn_id,
                        name=core_conn.name,
                        condition=core_conn.condition,
                        from_subscene=core_conn.from_subscene,
                        to_subscene=core_conn.to_subscene,
                        from_subscene_id=input_conn.from_subscene_id if input_conn else None, # We don't have easy access to ID here for new ones
                        to_subscene_id=input_conn.to_subscene_id if input_conn else None,
                        scene_id=input_conn.scene_id if input_conn else scene_id,
                        created_at=conn_created_at,
                        updated_at=current_time
                    )
                )

            merged_subscenes.append(
                SubsceneWithConnectionsResponse(
                    id=subscene_id,
                    name=core_subscene.name,
                    type=core_subscene.type.value,
                    state=core_subscene.state.value,
                    description=input_subscene.description if input_subscene else None, # Preserve description if not in Core
                    mandatory=core_subscene.mandatory,
                    objective=core_subscene.objective,
                    scene_id=scene_id,
                    connections=merged_connections,
                    created_at=sub_created_at,
                    updated_at=current_time
                )
            )

        merged_scenes.append(
            SceneGraphResponse(
                id=scene_id,
                name=core_scene.name,
                description=core_scene.identification_condition, # Core uses identification_condition as description-like
                state=core_scene.state.value,
                agent_id=agent_id,
                subscenes=merged_subscenes,
                created_at=created_at,
                updated_at=updated_at
            )
        )
    
    return merged_scenes


def build_core_agent_from_detail(agent_detail: AgentDetailResponse, current_scene_name: str | None = None, current_subscene_name: str | None = None) -> CoreAgent:
    """Build a CoreAgent instance from AgentDetailResponse."""
    core_agent = CoreAgent()
    
    # Configure LLM (use env var or agent setting)
    model_name = agent_detail.model_name
    llm_model = get_llm(model_name) if model_name else get_default_llm()
    
    if llm_model:
        core_agent.set_model(llm_model)
    else:
        logger.warning(f"No LLM found for model name '{model_name}' and no default available.")

    # Build Scenes
    for scene_resp in agent_detail.scenes:
        core_scene = CoreScene(
            name=scene_resp.name, 
            identification_condition=scene_resp.description or ""
        )
        
        # Build Subscenes
        subscene_map = {}
        for sub_resp in scene_resp.subscenes: # scenes field in SceneGraphResponse is actually list[SubsceneWithConnectionsResponse]
            core_subscene = CoreSubscene(
                name=sub_resp.name,
                subscene_type=SubsceneType(sub_resp.type),
                mandatory=sub_resp.mandatory,
                objective=sub_resp.objective or "",
            )
            # Add connections
            for conn_resp in sub_resp.connections:
                core_connection = CoreConnection(
                    name=conn_resp.name,
                    condition=conn_resp.condition or "",
                    from_subscene=conn_resp.from_subscene,
                    to_subscene=conn_resp.to_subscene,
                )
                core_subscene.add_connection(core_connection)
            
            core_scene.add_subscene(core_subscene)
            subscene_map[sub_resp.name] = core_subscene
            
        core_agent.add_plan(core_scene)

    # Set initial state if provided
    # Note: CoreAgent logic usually starts from the first scene/start subscene 
    # unless we explicitly set current_scene/current_subscene
    
    if current_scene_name:
        for scene in core_agent.scenes:
            if scene.name == current_scene_name:
                core_agent.current_scene = scene
                break
    
    if current_subscene_name and core_agent.current_scene:
        for subscene in core_agent.current_scene.subscenes:
            if subscene.name == current_subscene_name:
                core_agent.current_subscene = subscene
                break

    core_agent.is_started = True
    return core_agent


@router.post("/preview/chat/stream")
async def preview_chat_stream(request: PreviewChatRequest):
    """Streaming stateless chat for preview mode using provided agent definition.
    
    Returns a Server-Sent Events (SSE) stream with events aligned with AgentResponseChunk:
    - reasoning: Chain-of-Thought updates
    - reason: Reason content updates
    - response: Response content updates
    - updated_scenes: Scene graph updates
    - match_connection: Connection match updates
    - error: Error details
    """
    
    async def event_generator():
        try:
            # Build agent from request data
            agent = build_core_agent_from_detail(
                request.agent_detail, 
                request.current_scene_name, 
                request.current_subscene_name
            )
            
            if not agent.model:
                error_event = StreamEvent(
                    type=StreamEventType.ERROR,
                    error="API Key not configured.",
                    create_time=datetime.now(timezone.utc).isoformat()
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Chat stream
            # agent.chat_stream is synchronous, so we iterate it directly
            # but in an async function we might block the event loop.
            # However, for now we assume it's acceptable or we'd need run_in_executor.
            for chunk in agent.chat_stream(request.message):
                # Prepare converted data if needed
                updated_graph = None
                matched_connection = None
                
                if chunk.type == AgentResponseChunkType.UPDATED_SCENES and chunk.updated_scenes:
                    updated_graph = merge_graph_with_input(chunk.updated_scenes, request.agent_detail)
                    
                elif chunk.type == AgentResponseChunkType.MATCH_CONNECTION and chunk.matched_connection:
                     # Convert Core Connection to ConnectionResponse
                     # Simplification: Create a temporary ConnectionResponse
                     # Ideally we should match this against existing connections to get real IDs
                     matched_connection = ConnectionResponse(
                         id=f"preview-{uuid.uuid4().hex[:8]}",
                         name=chunk.matched_connection.name,
                         condition=chunk.matched_connection.condition,
                         from_subscene=chunk.matched_connection.from_subscene,
                         to_subscene=chunk.matched_connection.to_subscene,
                         from_subscene_id=None, # Not critical for preview display usually
                         to_subscene_id=None,
                         scene_id=None,
                         created_at=datetime.now(timezone.utc),
                         updated_at=datetime.now(timezone.utc)
                     )

                # StreamEvent中, REASONING、REASON、RESPONSE、ERROR都是实时stream chunk返回, 只有updated_scenes和matched_connection是在stream积累完成后一次性返回
                event = StreamEvent.from_core_response_chunk(
                    chunk, 
                    create_time=datetime.now(timezone.utc).isoformat(),
                    updated_scenes=updated_graph,
                    matched_connection=matched_connection
                )
                yield f"data: {event.json()}\n\n"
            
        except Exception as e:
            logger.error(f"Error in preview chat stream: {e}")
            logger.error(traceback.format_exc())
            error_event = StreamEvent(
                type=StreamEventType.ERROR,
                error=str(e),
                create_time=datetime.now(timezone.utc).isoformat()
            )
            yield f"data: {error_event.json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
