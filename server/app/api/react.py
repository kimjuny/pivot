"""API endpoints for ReAct agent chat stream.

This module provides streaming chat endpoints for the ReAct agent system.
All endpoints require authentication.
"""

import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from time import perf_counter

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.llm import llm as llm_crud
from app.llm.llm_factory import create_llm_from_config
from app.models.agent import Agent
from app.models.react import ReactRecursion, ReactTask
from app.models.user import User
from app.orchestration.react import ReactEngine
from app.orchestration.skills import select_skills
from app.orchestration.tool import get_tool_manager
from app.orchestration.tool.builtin.programmatic_tool_call import (
    make_programmatic_tool_call,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.react import ReactChatRequest, ReactStreamEvent, ReactStreamEventType
from app.services.session_memory_service import SessionMemoryService
from app.services.skill_service import (
    build_selected_skills_prompt_block,
    list_all_skills,
)
from app.services.workspace_service import (
    ensure_agent_workspace,
    load_all_user_tool_metadata,
)
from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlmodel import Session, select

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/react/chat/stream")
async def react_chat_stream(
    request: ReactChatRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    ReAct streaming chat endpoint.

    This endpoint creates a new ReAct task and executes it with streaming updates.
    The stream returns Server-Sent Events (SSE) with the following event types:
    - recursion_start: New recursion cycle started
    - observe: LLM observation
    - thought: LLM reasoning
    - abstract: Brief summary of the recursion cycle
    - action: Action decision
    - tool_call: Tool execution
    - tool_result: Tool execution result
    - plan_update: Plan update from RE_PLAN action
    - reflect: Reflection summary from REFLECT action
    - answer: Final answer from ANSWER action
    - error: Error occurred
    - task_complete: Task completed successfully

    Args:
        request: ReactChatRequest containing agent_id, message, and user
        db: Database session dependency

    Returns:
        StreamingResponse with text/event-stream content
    """

    async def event_generator():
        client_disconnected = False
        task = None

        try:
            # Get agent
            agent = db.get(Agent, request.agent_id)
            if not agent:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={"error": f"Agent {request.agent_id} not found"},
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Get LLM configuration for this agent
            if not agent.llm_id:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={"error": f"Agent {agent.name} has no LLM configured"},
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            llm_config = llm_crud.get(agent.llm_id, db)
            if not llm_config:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={
                        "error": f"LLM configuration with ID {agent.llm_id} not found"
                    },
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Create LLM instance from configuration
            try:
                llm = create_llm_from_config(llm_config)
            except (ValueError, NotImplementedError) as e:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={"error": f"Failed to create LLM instance: {e!s}"},
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Check if this is a resume request for an existing task
            if request.task_id:
                stmt = select(ReactTask).where(ReactTask.task_id == request.task_id)
                existing_task = db.exec(stmt).first()

                if existing_task:
                    # If task is waiting for input, this is a reply to CLARIFY
                    if existing_task.status == "waiting_input":
                        # Find the last recursion (which should be CLARIFY)
                        rec_stmt = (
                            select(ReactRecursion)
                            .where(ReactRecursion.task_id == existing_task.task_id)
                            .order_by(desc(ReactRecursion.iteration_index))
                        )
                        last_rec = db.exec(rec_stmt).first()

                        if last_rec and last_rec.action_type == "CLARIFY":
                            # Update action_output with user's reply
                            try:
                                output = json.loads(last_rec.action_output or "{}")
                            except json.JSONDecodeError:
                                output = {}

                            output["reply"] = request.message
                            last_rec.action_output = json.dumps(
                                output, ensure_ascii=False
                            )
                            last_rec.updated_at = datetime.now(timezone.utc)
                            db.add(last_rec)

                            # Resume task
                            task = existing_task
                            # Status will be updated to 'running' in engine.run_task
                            logger.info(
                                f"Resuming task {task.task_id} with CLARIFY reply"
                            )
                        else:
                            # Fallback if state is inconsistent
                            logger.warning(
                                f"Task {existing_task.task_id} is waiting_input but last recursion is not CLARIFY"
                            )
                            task = existing_task
                    else:
                        # Task exists but not waiting for input? Maybe reviving?
                        # For now, assume we just attach to it
                        task = existing_task
                else:
                    # Requests task_id but not found, create new
                    pass

            if not task:
                # Create ReactTask
                task_id = str(uuid.uuid4())
                task = ReactTask(
                    task_id=task_id,
                    session_id=request.session_id,
                    agent_id=agent.id or 0,
                    user=request.user,
                    user_message=request.message,
                    # Persist in the legacy column while treating it semantically
                    # as task-level user intent.
                    objective=request.message,
                    status="pending",
                    iteration=0,
                    max_iteration=agent.max_iteration,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                db.add(task)
                db.commit()
                db.refresh(task)

            # Ensure task_id is set
            task_id = task.task_id

            # Build a request-scoped ToolManager that merges shared (builtin) tools
            # with the current user's private workspace tools.
            # We copy the shared registry into a fresh instance so the global
            # singleton is never mutated across requests.
            ensure_agent_workspace(current_user.username, agent.id or 0)
            shared_manager = get_tool_manager()
            request_tool_manager = ToolManager()
            for meta in shared_manager.list_tools():
                request_tool_manager.add_entry(meta)

            # Dynamically load private tools from workspace at request time so that
            # tools saved by the user are visible without a server restart.
            private_metas = load_all_user_tool_metadata(current_user.username)
            for meta in private_metas:
                if request_tool_manager.get_tool(meta.name) is None:
                    request_tool_manager.add_entry(meta)
                else:
                    logger.warning(
                        "Private tool '%s' conflicts with a shared tool name and was skipped.",
                        meta.name,
                    )

            # Rebind programmatic_tool_call so its exec sandbox sees the full
            # request-scoped registry (shared + private tools).  The global stub
            # only knows about shared tools; without this, private tools imported
            # inside a snippet raise ModuleNotFoundError.
            ptc_meta = request_tool_manager.get_tool("programmatic_tool_call")
            if ptc_meta is not None:
                full_callables = {
                    m.name: m.func for m in request_tool_manager.list_tools()
                }
                ptc_meta.func = make_programmatic_tool_call(full_callables)

            # Filter the tool registry to only tools the agent is allowed to use.
            # agent.tool_ids is a JSON-encoded list of names, e.g. '["add","test_tool"]'.
            # None means no restriction; '[]' means the agent has no tools.
            if agent.tool_ids is not None:
                try:
                    allowed: set[str] = set(json.loads(agent.tool_ids))
                except (ValueError, TypeError):
                    allowed = set()
                filtered_manager = ToolManager()
                for meta in request_tool_manager.list_tools():
                    if meta.name in allowed:
                        filtered_manager.add_entry(meta)
                request_tool_manager = filtered_manager

            engine = ReactEngine(
                llm=llm,
                tool_manager=request_tool_manager,
                db=db,
                tool_execution_context=ToolExecutionContext(
                    username=current_user.username,
                    agent_id=agent.id or 0,
                ),
            )

            selected_skills: list[str] = []
            selected_skills_text = ""
            total_skill_count = 0
            candidate_skill_count = 0
            resolution_duration_ms = 0
            # Skill resolution is optional and only runs when a resolver LLM is configured.
            if agent.skill_resolution_llm_id:
                skill_start_event = {
                    "type": "skill_resolution_start",
                    "task_id": task_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                yield f"data: {json.dumps(skill_start_event, ensure_ascii=False)}\n\n"
                resolution_started_at = perf_counter()
                try:
                    resolver_llm_config = llm_crud.get(agent.skill_resolution_llm_id, db)
                    if resolver_llm_config:
                        resolver_llm = create_llm_from_config(resolver_llm_config)
                        available_skills = list_all_skills(current_user.username)
                        total_skill_count = len(available_skills)
                        candidate_skill_count = total_skill_count
                        if agent.skill_ids is not None:
                            try:
                                allowed_skills = set(json.loads(agent.skill_ids))
                            except (ValueError, TypeError):
                                allowed_skills = set()
                            available_skills = [
                                item for item in available_skills if item.get("name") in allowed_skills
                            ]
                            candidate_skill_count = len(available_skills)

                        session_memory = {}
                        if task.session_id:
                            session_memory = SessionMemoryService(db).get_full_session_memory_dict(task.session_id)

                        selected_skills = select_skills(
                            llm=resolver_llm,
                            user_intent=request.message,
                            skill_metadata=available_skills,
                            session_memory=session_memory,
                        )
                        selected_skills_text = build_selected_skills_prompt_block(
                            username=current_user.username,
                            selected_skills=selected_skills,
                        )
                        resolution_duration_ms = int(
                            (perf_counter() - resolution_started_at) * 1000
                        )
                        logger.info(
                            "Skill resolution finished: task_id=%s session_id=%s total=%d candidates=%d selected=%d selected_names=%s duration_ms=%d",
                            task_id,
                            task.session_id,
                            total_skill_count,
                            candidate_skill_count,
                            len(selected_skills),
                            selected_skills,
                            resolution_duration_ms,
                        )
                    else:
                        resolution_duration_ms = int(
                            (perf_counter() - resolution_started_at) * 1000
                        )
                        logger.warning(
                            "Skill resolution skipped because resolver LLM not found: task_id=%s resolver_llm_id=%s duration_ms=%d",
                            task_id,
                            agent.skill_resolution_llm_id,
                            resolution_duration_ms,
                        )
                except Exception as skill_err:
                    logger.warning("Skill resolution failed: %s", skill_err)
                    resolution_duration_ms = int(
                        (perf_counter() - resolution_started_at) * 1000
                    )

                skill_result_event = {
                    "type": "skill_resolution_result",
                    "task_id": task_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "count": len(selected_skills),
                        "selected_skills": selected_skills,
                        "total_skill_count": total_skill_count,
                        "candidate_skill_count": candidate_skill_count,
                        "duration_ms": resolution_duration_ms,
                    },
                }
                yield f"data: {json.dumps(skill_result_event, ensure_ascii=False)}\n\n"

            # Execute task and stream events
            async for event_data in engine.run_task(
                task=task,
                selected_skills_text=selected_skills_text,
            ):
                # Check if client disconnected via Request object
                if await raw_request.is_disconnected():
                    logger.info(f"Client disconnected, stopping task {task_id}")
                    client_disconnected = True
                    engine.cancelled = True  # Signal engine to stop
                    break

                # Check if client disconnected via flag
                if client_disconnected:
                    logger.info(f"Client disconnected, stopping task {task_id}")
                    engine.cancelled = True  # Signal engine to stop
                    break

                # Convert event data to ReactStreamEvent
                event_type_str = event_data.get("type", "")
                try:
                    event_type = ReactStreamEventType(event_type_str)
                except ValueError:
                    # Unknown event type, skip
                    logger.warning(f"Unknown event type: {event_type_str}")
                    continue

                event = ReactStreamEvent(
                    type=event_type,
                    task_id=event_data.get("task_id", task_id),
                    trace_id=event_data.get("trace_id"),
                    iteration=event_data.get("iteration", 0),
                    delta=event_data.get("delta"),
                    data=event_data.get("data"),
                    timestamp=datetime.fromisoformat(
                        event_data.get(
                            "timestamp", datetime.now(timezone.utc).isoformat()
                        )
                    ),
                    created_at=event_data.get("created_at"),
                    updated_at=event_data.get("updated_at"),
                    tokens=event_data.get("tokens"),
                    total_tokens=event_data.get("total_tokens"),
                )

                try:
                    yield f"data: {event.json()}\n\n"
                except (
                    GeneratorExit,
                    ConnectionResetError,
                    BrokenPipeError,
                ) as e:
                    # Client disconnected
                    logger.info(f"Client disconnected during yield: {e}")
                    client_disconnected = True
                    break

        except (GeneratorExit, ConnectionResetError, BrokenPipeError) as e:
            # Client disconnected
            logger.info(f"Client disconnected: {e}")
            client_disconnected = True
        except Exception as e:
            logger.error(f"Error in ReAct chat stream: {e}")
            logger.error(traceback.format_exc())
            if not client_disconnected:
                try:
                    error_event = ReactStreamEvent(
                        type=ReactStreamEventType.ERROR,
                        task_id="",
                        trace_id=None,
                        iteration=0,
                        delta=None,
                        data={"error": str(e)},
                        timestamp=datetime.now(timezone.utc),
                    )
                    yield f"data: {error_event.json()}\n\n"
                except (GeneratorExit, ConnectionResetError, BrokenPipeError):
                    pass
        finally:
            # Mark task as cancelled if client disconnected
            if client_disconnected and task:
                task.status = "cancelled"
                task.updated_at = datetime.now(timezone.utc)
                try:
                    db.commit()
                    logger.info(f"Task {task.task_id} marked as cancelled")
                except Exception as e:
                    logger.error(f"Failed to mark task as cancelled: {e}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/react/tasks/{task_id}")
async def get_react_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get ReAct task information by task_id.

    Args:
        task_id: Task UUID
        db: Database session dependency

    Returns:
        ReactTask information
    """
    from app.models.react import ReactTask
    from sqlmodel import select

    stmt = select(ReactTask).where(ReactTask.task_id == task_id)
    task = db.exec(stmt).first()

    if not task:
        return {"error": "Task not found"}, 404

    payload = jsonable_encoder(task)
    payload["user_intent"] = task.user_intent
    # Keep legacy field for older clients.
    payload["objective"] = task.objective
    return payload


@router.get("/react/tasks/{task_id}/recursions")
async def get_task_recursions(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all recursions for a task.

    Args:
        task_id: Task UUID
        db: Database session dependency

    Returns:
        List of recursions
    """
    from app.models.react import ReactRecursion
    from sqlmodel import select

    stmt = (
        select(ReactRecursion)
        .where(ReactRecursion.task_id == task_id)
        .order_by(ReactRecursion.iteration_index)
    )
    recursions = db.exec(stmt).all()

    return list(recursions)


@router.get("/react/tasks/{task_id}/states")
async def get_task_states(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all recursion states for a task.

    This endpoint returns the complete state machine snapshots for each recursion,
    enabling state recovery, debugging, and historical analysis.

    Args:
        task_id: Task UUID
        db: Database session dependency

    Returns:
        List of recursion states with complete state snapshots
    """
    from app.models.react import ReactRecursionState
    from sqlmodel import select

    stmt = (
        select(ReactRecursionState)
        .where(ReactRecursionState.task_id == task_id)
        .order_by(ReactRecursionState.iteration_index)
    )
    states = db.exec(stmt).all()

    return list(states)


@router.get("/react/tasks/{task_id}/states/{iteration_index}")
async def get_task_state_at_iteration(
    task_id: str,
    iteration_index: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get recursion state at a specific iteration.

    This endpoint returns the complete state machine snapshot for a specific
    recursion iteration, useful for debugging or state recovery.

    Args:
        task_id: Task UUID
        iteration_index: Iteration index (0-based)
        db: Database session dependency

    Returns:
        Recursion state at the specified iteration
    """
    from app.models.react import ReactRecursionState
    from sqlmodel import select

    stmt = (
        select(ReactRecursionState)
        .where(ReactRecursionState.task_id == task_id)
        .where(ReactRecursionState.iteration_index == iteration_index)
    )
    state = db.exec(stmt).first()

    if not state:
        return {"error": "State not found"}, 404

    return state
