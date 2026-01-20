import json
import logging
import os
import traceback
from typing import Any

from app.api.chat import convert_db_to_core_scene
from app.api.dependencies import get_db
from app.crud import build as build_crud
from app.crud.agent import agent as agent_crud
from app.crud.connection import connection as connection_crud
from app.crud.scene import scene as scene_crud
from app.crud.subscene import subscene as subscene_crud
from app.schemas.build import BuildChatRequest, BuildChatResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.agent.agent import Agent as CoreAgent
from core.agent.builder import AgentBuilder
from core.agent.system_prompt import get_build_prompt
from core.llm.doubao_llm import DoubaoLLM

logger = logging.getLogger(__name__)

router = APIRouter()


def get_agent_builder() -> AgentBuilder:
    """Initialize AgentBuilder with LLM."""
    api_key = os.getenv("DOUBAO_SEED_API_KEY")
    if not api_key:
        logger.warning("DOUBAO_SEED_API_KEY not set")
        # In production, this should likely raise an error or use a mock
        # For now, we proceed but LLM calls will fail if not handled
        raise HTTPException(status_code=500, detail="LLM API key not configured")

    llm = DoubaoLLM(api_key=api_key, timeout=120)
    return AgentBuilder(llm)


def reconstruct_builder_history(
    builder: AgentBuilder,
    history_items: list[Any],
    initial_agent_dict: dict[str, Any] | None = None,
):
    """
    Reconstruct the conversation history for the AgentBuilder.

    Args:
        builder: The AgentBuilder instance.
        history_items: List of BuildHistory items from DB.
        initial_agent_dict: The initial agent state if this is the start of a session (or to be injected).
    """
    # 1. Start with System Prompt
    # If there is history, we assume the first turn established the system prompt.
    # However, AgentBuilder logic injects system prompt if history is empty.
    # So we should manually set the first history item as the system prompt
    # if we are restoring a session.

    # But wait, AgentBuilder.build() checks `if not self.history`.
    # If we populate self.history, it won't inject system prompt.
    # So we must manually inject the system prompt as the first item.

    # We need to know what the "initial agent" was at the start of the session to generate the correct system prompt.
    # But we don't store the "initial agent" explicitly in the session, only snapshots in history.
    # For simplicity, if we are reloading history, we can assume the system prompt was generic OR
    # we can try to grab the very first user message's context.

    # Better approach: Always inject a generic system prompt at the start of history reconstruction,
    # or the specific one if we know we are modifying a specific agent from the start.

    # Strategy:
    # 1. Clear builder history.
    # 2. Inject System Prompt.
    # 3. Append all DB history items.

    builder.clear_history()

    # Inject System Prompt
    # If we have an initial_agent_dict passed (e.g. from the very first request params stored somewhere?),
    # we would use it. But for restored sessions, we might just use a generic one
    # or the one implied by the flow.
    # A safe bet for a restored session is to use the `initial_agent_dict` if provided (e.g. if we are "continuing"
    # a modification session, maybe we should use the LATEST snapshot as the "existing agent" context?
    # No, the history contains the flow.
    # Let's use a generic prompt if we are restoring, or if we have `initial_agent_dict` use that.

    system_msg = get_build_prompt(existing_agent=initial_agent_dict)
    builder.history.append(system_msg)

    for item in history_items:
        msg = {"role": item.role, "content": item.content}
        builder.history.append(msg)


@router.post("/build/chat", response_model=BuildChatResponse)
async def chat_build(request: BuildChatRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Chat endpoint for building/modifying agents.
    """
    logger.info(f"Received build chat request. Session: {request.session_id}")

    # 1. Handle Session
    if request.session_id:
        session = build_crud.get_session(db, request.session_id)
        if not session:
            # If ID provided but not found, create new (or error? Let's create new for robustness)
            logger.info(f"Session {request.session_id} not found, creating new.")
            session = build_crud.create_session(db)
    else:
        session = build_crud.create_session(db)

    session_id = session.id

    # 2. Load History
    history_items = build_crud.get_session_history(db, session_id)

    # 3. Determine Context Agent
    # If this is a new session AND agent_id is provided, we load that agent to start modification.
    initial_agent = None
    if not history_items and request.agent_id:
        # Load agent from DB
        try:
            agent_id_int = int(request.agent_id)
            db_agent = agent_crud.get(agent_id_int, db)
            if db_agent:
                # Convert to CoreAgent to get dict
                # We need to load scenes too
                db_scenes = scene_crud.get_by_agent_id(agent_id_int, db)
                if db_scenes:
                    db_scene = db_scenes[0]
                    db_subscenes = subscene_crud.get_by_scene_id(db_scene.id, db)
                    db_connections = []
                    for sub in db_subscenes:
                        conns = connection_crud.get_by_from_subscene(sub.name, db)
                        db_connections.extend(conns)

                    core_scene = convert_db_to_core_scene(
                        db_scene, db_subscenes, db_connections
                    )

                    core_agent = CoreAgent(
                        name=db_agent.name, description=db_agent.description or ""
                    )
                    core_agent.add_plan(core_scene)
                    initial_agent = core_agent
        except Exception as e:
            logger.error(f"Failed to load initial agent {request.agent_id}: {e}")
            # Proceed without initial agent if failed

    # 4. Initialize Builder & Restore State
    try:
        builder = get_agent_builder()
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Failed to init builder: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Reconstruct history
    # If we have initial_agent, we pass it to reconstruct_builder_history to generate the correct system prompt
    # Note: If history_items exist, initial_agent should be ignored for system prompt generation
    # because the system prompt is already "established" by the first turn logic.
    # However, `reconstruct_builder_history` clears history and re-adds system prompt.
    # So we need to be careful.

    # Simple logic:
    # If history is empty, `builder.build` will handle system prompt injection.
    # If history exists, we manually populate `builder.history`.

    if history_items:
        # Reconstruct manually
        # We need the original system prompt. Ideally, we should store the system prompt in history too,
        # or just use a generic one.
        # For now, let's use a generic one for restoration.
        reconstruct_builder_history(builder, history_items, initial_agent_dict=None)

    # 5. Call Builder
    # If this is the first turn (no history), we pass `initial_agent` to `build`.
    # If it's subsequent turns, `initial_agent` param in `build` is less critical as context is in history,
    # BUT `build` logic appends current agent context if provided.
    # Since we are stateless, we don't have the "current agent" object in memory from previous turn.
    # We should reconstruct the "current agent" from the last `agent_snapshot` in history if available.

    current_agent_context = initial_agent
    if history_items:
        # Try to find the last assistant message with a snapshot
        for item in reversed(history_items):
            if item.role == "assistant" and item.agent_snapshot:
                try:
                    data = json.loads(item.agent_snapshot)
                    current_agent_context = CoreAgent.from_dict(data)
                    break
                except Exception:
                    pass

    try:
        # Execute Build
        result = builder.build(request.content, agent=current_agent_context)

        # 6. Save History
        # Save User Message
        build_crud.add_history(db, session_id, "user", request.content)

        # Save Assistant Message
        # We store the FULL content (JSON string usually, or whatever builder returns as content?
        # Wait, builder.build returns a Result object, but the internal LLM history has the raw content string.
        # We should store the raw content in history to match LLM conversation,
        # OR we construct a nice message.
        # `builder.history[-1]` contains the assistant's last raw message.

        assistant_raw_content = builder.history[-1]["content"]

        agent_snapshot_json = json.dumps(result.agent.to_dict(), ensure_ascii=False)

        build_crud.add_history(
            db,
            session_id,
            "assistant",
            assistant_raw_content,
            agent_snapshot=agent_snapshot_json,
        )

        return {
            "session_id": session_id,
            "response": result.response,
            "reason": result.reason,
            "updated_agent": result.agent.to_dict(),
        }

    except Exception as e:
        logger.error(f"Build failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Build failed: {e!s}") from e
