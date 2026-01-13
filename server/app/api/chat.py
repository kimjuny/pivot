"""API endpoints for agent chat and chat history management.

This module provides endpoints for chatting with agents and managing
chat history, including conversation state persistence.
"""
import json
import logging
import os
import traceback
from datetime import timezone

from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.crud.chat_history import chat_history as chat_history_crud
from app.crud.connection import connection as connection_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from core.agent.agent import Agent as CoreAgent
from core.agent.plan.connection import Connection as CoreConnection
from core.agent.plan.scene import Scene as CoreScene
from core.agent.plan.subscene import Subscene as CoreSubscene, SubsceneType
from core.llm.doubao_llm import DoubaoLLM
from server.websocket import manager

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


def convert_db_to_core_scene(db_scene, db_subscenes, db_connections):
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
            objective=db_subscene.objective
        )

        # Get all connections for this subscene
        subscene_connections = [
            CoreConnection(
                name=conn.name,
                condition=conn.condition,
                from_subscene=conn.from_subscene,
                to_subscene=conn.to_subscene
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
        name=db_scene.name,
        identification_condition=db_scene.description
    )

    # Add subscenes to scene
    for core_subscene in core_subscenes:
        core_scene.add_subscene(core_subscene)

    return core_scene


class ChatRequest(BaseModel):
    """Schema for chat request.

    Attributes:
        message: The user's message.
        user: The username of the user (default: preview-user).
    """
    message: str = Field(..., description="User message")
    user: str = Field(default="preview-user", description="Username of the user")


@router.post("/agents/{agent_id}/chat")
async def chat_with_agent_by_id(
    agent_id: int,
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """Chat with specific agent by loading its configuration from database.

    This endpoint:
    1. Loads chat history and finds latest update_scene
    2. Loads agent configuration from database
    3. Converts database models to core models
    4. Creates and initializes agent instance
    5. Prints scene graph for verification
    6. Stores user message in chat history
    7. Chats with the agent
    8. Stores agent response in chat history
    9. Returns response to frontend with updated graph

    Args:
        agent_id: The ID of the agent to chat with.
        request: Chat request containing message and user.
        db: Database session.

    Returns:
        Agent response with reasoning and updated scene graph.

    Raises:
        HTTPException: If agent or scenes are not found (404), or if an error occurs (500).
    """
    logger.info(f"Received chat request for agent {agent_id} from user {request.user}: {request.message[:50]}...")

    # Get agent from database
    db_agent = agent_crud.get(agent_id, db)
    if not db_agent:
        logger.warning(f"Agent {agent_id} not found")
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get scenes for this agent
    db_scenes = scene_crud.get_by_agent_id(agent_id, db)
    if not db_scenes or len(db_scenes) == 0:
        logger.warning(f"No scenes found for agent {agent_id}")
        raise HTTPException(status_code=404, detail="No scenes found for this agent")

    # Use the first scene
    db_scene = db_scenes[0]

    # Get all subscenes for this scene
    db_subscenes = subscene_crud.get_by_scene_id(db_scene.id, db)

    # Get all connections for this scene
    db_connections = []
    for db_subscene in db_subscenes:
        connections = connection_crud.get_by_from_subscene(db_subscene.name, db)
        db_connections.extend(connections)

    logger.info(f"Loaded {len(db_subscenes)} subscenes and {len(db_connections)} connections from database")

    # Check if there's a latest update_scene in chat history
    latest_update_scene = chat_history_crud.get_latest_update_scene(agent_id, request.user, db)
    if latest_update_scene:
        logger.info("Found latest update_scene in chat history, loading saved scene state")
        try:
            # Parse the update_scene JSON to restore scene state
            json.loads(latest_update_scene)
            # TODO: Implement logic to restore scene state from saved data
            # For now, we'll use the default scene
            logger.warning("Scene state restoration not fully implemented, using default scene")
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse update_scene JSON: {latest_update_scene}")

    # Convert database models to core models
    core_scene = convert_db_to_core_scene(db_scene, db_subscenes, db_connections)

    # Store user message in chat history
    logger.info("Storing user message in chat history...")
    user_message = chat_history_crud.create_user_message(
        agent_id=agent_id,
        user=request.user,
        message=request.message,
        session=db
    )

    # Create agent instance
    agent = CoreAgent()

    # Set LLM model
    api_key = os.getenv("DOUBAO_SEED_API_KEY")
    if not api_key:
        logger.warning("DOUBAO_SEED_API_KEY not set, using mock response")
        # Return mock response for testing
        return {
            "response": "I understand you want to sleep. Let me help you relax and prepare for a good night's rest.",
            "reason": "User expressed desire to sleep, suggesting relaxation techniques",
            "graph": None,
            "create_time": user_message.create_time.replace(tzinfo=timezone.utc).isoformat()
        }

    llm_model = DoubaoLLM(api_key=api_key)
    agent.set_model(llm_model)

    # Add scene to agent
    agent.add_plan(core_scene)

    # Start agent
    agent.is_started = True

    # Print scene graph for verification
    logger.info("Printing scene graph for verification...")
    agent.print_scene_graph()

    try:
        # Get response from agent
        logger.info("Getting response from agent...")
        response = agent.chat(request.message)
        first_choice = response.first()

        # Parse response content to extract only response and reason
        response_content = first_choice.message.content
        logger.info(f"Agent response received: {response_content[:100]}...")

        try:
            parsed_response = json.loads(response_content)

            # Extract only the fields we need
            chat_response = parsed_response.get("response", "")
            reason = parsed_response.get("reason", "")
            logger.info("Parsed response and reason")
        except json.JSONDecodeError:
            # Fallback if response is not JSON format
            chat_response = first_choice.message.content
            reason = ""
            logger.warning("Response is not in JSON format, using raw content")

        # Get current scene graph
        logger.info("Getting current scene graph...")
        scene_graph = {
            "scenes": [scene.to_dict() for scene in agent.scenes],
            "current_scene": agent.current_scene.name if agent.current_scene else None,
            "current_subscene": agent.current_subscene.name if agent.current_subscene else None
        }
        logger.info(f"Current scene: {scene_graph['current_scene']}, Current subscene: {scene_graph['current_subscene']}")

        # Store agent message in chat history with update_scene
        logger.info("Storing agent message in chat history...")
        agent_message = chat_history_crud.create_agent_message(
            agent_id=agent_id,
            user=request.user,
            message=chat_response,
            reason=reason,
            update_scene=json.dumps(scene_graph),
            session=db
        )

        # Broadcast update to all connected WebSocket clients
        logger.info("Broadcasting scene update via WebSocket...")
        await manager.broadcast({
            "type": "scene_update",
            "data": scene_graph
        })

        logger.info("Chat request completed successfully")
        return {
            "response": chat_response,
            "reason": reason,
            "graph": scene_graph,
            "create_time": agent_message.create_time.replace(tzinfo=timezone.utc).isoformat()
        }
    except HTTPException:
        raise
    except Exception as e:
        # Check if it's an API key related error
        error_str = str(e).lower()
        if "api key" in error_str or "authentication" in error_str or "unauthorized" in error_str:
            logger.warning(f"API key error detected: {e!s}, returning mock response")
            return {
                "response": "I understand your request. Due to a configuration issue with the API, I'm providing a simulated response to assist you.",
                "reason": "API key error - returning mock response",
                "graph": None
            }
        logger.error(f"Error chatting with agent: {e!s}")
        logger.error(f"Exception traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error chatting with agent: {e!s}") from e


@router.get("/agents/{agent_id}/chat-history")
async def get_chat_history(
    agent_id: int,
    user: str = "preview-user",
    db: Session = Depends(get_db)
):
    """Get chat history for a specific agent and user.

    Args:
        agent_id: Agent ID
        user: Username of the user (default: preview-user)
        db: Database session

    Returns:
        List of chat history with latest graph state

    Raises:
        HTTPException: If agent or scenes are not found (404).
    """
    logger.info(f"Getting chat history for agent {agent_id} and user {user}...")

    # Get agent from database
    db_agent = agent_crud.get(agent_id, db)
    if not db_agent:
        logger.warning(f"Agent {agent_id} not found")
        raise HTTPException(status_code=404, detail="Agent not found")

    # Get chat history
    chat_history_list = chat_history_crud.get_by_agent_and_user(agent_id, user, db)

    # Get latest update_scene
    latest_update_scene = chat_history_crud.get_latest_update_scene(agent_id, user, db)

    # Get default scene graph
    db_scenes = scene_crud.get_by_agent_id(agent_id, db)
    if not db_scenes or len(db_scenes) == 0:
        logger.warning(f"No scenes found for agent {agent_id}")
        raise HTTPException(status_code=404, detail="No scenes found for this agent")

    db_scene = db_scenes[0]
    db_subscenes = subscene_crud.get_by_scene_id(db_scene.id, db)

    # Get all connections for this scene
    db_connections = []
    for db_subscene in db_subscenes:
        connections = connection_crud.get_by_from_subscene(db_subscene.name, db)
        db_connections.extend(connections)

    # Convert database models to core models
    core_scene = convert_db_to_core_scene(db_scene, db_subscenes, db_connections)

    # Get default scene graph
    default_scene_graph = {
        "scenes": [scene.to_dict() for scene in core_scene.subscenes],
        "current_scene": core_scene.name,
        "current_subscene": None
    }

    # Parse latest update_scene if exists
    latest_graph = None
    if latest_update_scene:
        try:
            latest_graph = json.loads(latest_update_scene)
            logger.info("Found latest update_scene in chat history")
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse latest update_scene: {latest_update_scene}")

    # Prepare response
    response_data = []
    for history_item in chat_history_list:
        # Return ISO format UTC time with timezone indicator to ensure proper parsing
        iso_time = history_item.create_time.replace(tzinfo=timezone.utc).isoformat()

        # Determine if this item has graph
        graph = None
        if history_item.update_scene:
            try:
                graph = json.loads(history_item.update_scene)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse update_scene for history item {history_item.id}")

        response_data.append({
            "id": history_item.id,
            "agent_id": history_item.agent_id,
            "user": history_item.user,
            "role": history_item.role,
            "message": history_item.message,
            "reason": history_item.reason,
            "update_scene": history_item.update_scene,
            "create_time": iso_time,
            "graph": graph
        })

    logger.info(f"Returning {len(response_data)} chat history items")
    return {
        "history": response_data,
        "latest_graph": latest_graph if latest_graph else default_scene_graph
    }


@router.delete("/agents/{agent_id}/chat-history")
async def clear_chat_history(
    agent_id: int,
    user: str = "preview-user",
    db: Session = Depends(get_db)
):
    """Clear chat history for a specific agent and user.

    Args:
        agent_id: Agent ID
        user: Username of the user (default: preview-user)
        db: Database session

    Returns:
        Success message

    Raises:
        HTTPException: If agent is not found (404).
    """
    logger.info(f"Clearing chat history for agent {agent_id} and user {user}...")

    # Get agent from database
    db_agent = agent_crud.get(agent_id, db)
    if not db_agent:
        logger.warning(f"Agent {agent_id} not found")
        raise HTTPException(status_code=404, detail="Agent not found")

    # Delete all chat history for this agent and user
    success = chat_history_crud.delete_by_agent_and_user(agent_id, user, db)

    if success:
        logger.info(f"Successfully cleared chat history for agent {agent_id} and user {user}")
        return {
            "message": "Chat history cleared successfully",
            "agent_id": agent_id,
            "user": user
        }
    else:
        logger.warning(f"No chat history found for agent {agent_id} and user {user}")
        return {
            "message": "No chat history found to clear",
            "agent_id": agent_id,
            "user": user
        }
