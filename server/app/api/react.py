"""API endpoints for ReAct agent chat stream.

This module provides streaming chat endpoints for the ReAct agent system.
All endpoints require authentication.
"""

import asyncio
import json
import logging
import traceback
import uuid
from datetime import UTC, datetime
from time import perf_counter

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.llm import llm as llm_crud
from app.llm.llm_factory import create_llm_from_config
from app.models.agent import Agent
from app.models.react import ReactRecursion, ReactTask
from app.models.user import User
from app.orchestration.react import ReactEngine
from app.orchestration.skills import select_skills_with_usage
from app.orchestration.tool import get_tool_manager
from app.orchestration.tool.builtin.programmatic_tool_call import (
    make_programmatic_tool_call,
)
from app.orchestration.tool.manager import ToolExecutionContext, ToolManager
from app.schemas.react import (
    ReactChatRequest,
    ReactContextUsageRequest,
    ReactContextUsageResponse,
    ReactStreamEvent,
    ReactStreamEventType,
)
from app.services.file_service import FileService
from app.services.react_context_service import ReactContextUsageService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.session_memory_service import SessionMemoryService
from app.services.skill_service import (
    build_selected_skills_prompt_block,
    build_skill_mounts,
    list_visible_skills,
)
from app.services.workspace_service import (
    ensure_agent_workspace,
    load_all_user_tool_metadata,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlmodel import Session, col, select

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_name_allowlist(raw_json: str | None) -> set[str] | None:
    """Parse optional JSON allowlist string into a normalized name set.

    Args:
        raw_json: JSON string from model field. ``None``/blank means unrestricted.

    Returns:
        ``None`` when unrestricted; otherwise a set of allowed names.
    """
    if raw_json is None:
        return None

    text = raw_json.strip()
    if text == "":
        return None

    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return set()

    if not isinstance(parsed, list):
        return set()

    result: set[str] = set()
    for item in parsed:
        if isinstance(item, str):
            normalized = item.strip()
            if normalized:
                result.add(normalized)
    return result


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
    - token_rate: Realtime estimated output token rate during streaming
    - observe: LLM observation
    - thought: LLM reasoning
    - abstract: Brief summary of the recursion cycle
    - summary: User-facing progress summary for the recursion
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
        turn_files = []
        turn_file_blocks = []

        try:
            runtime_service = ReactRuntimeService(db)
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
                    timestamp=datetime.now(UTC),
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
                    timestamp=datetime.now(UTC),
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
                    timestamp=datetime.now(UTC),
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
                    timestamp=datetime.now(UTC),
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
                            .order_by(desc(col(ReactRecursion.iteration_index)))
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
                            last_rec.updated_at = datetime.now(UTC)
                            db.add(last_rec)
                            runtime_service.set_next_action_result(
                                existing_task,
                                [{"result": output}],
                            )

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
                    user_intent=request.message,
                    status="pending",
                    iteration=0,
                    max_iteration=agent.max_iteration,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                db.add(task)
                db.commit()
                db.refresh(task)

            # Ensure task_id is set
            task_id = task.task_id

            if request.file_ids:
                file_service = FileService(db)
                try:
                    attached_files = file_service.attach_files_to_task(
                        file_ids=request.file_ids,
                        username=current_user.username,
                        session_id=task.session_id,
                        task_id=task_id,
                    )
                except ValueError as err:
                    error_event = ReactStreamEvent(
                        type=ReactStreamEventType.ERROR,
                        task_id=task_id,
                        trace_id=None,
                        iteration=task.iteration,
                        delta=None,
                        data={"error": str(err)},
                        timestamp=datetime.now(UTC),
                    )
                    yield f"data: {error_event.json()}\n\n"
                    return

                turn_files = file_service.build_history_items([task_id]).get(
                    task_id, []
                )
                turn_file_blocks = [
                    content_block
                    for item in file_service.preprocess_files(attached_files)
                    for content_block in item.content_blocks
                ]

            if agent.skill_resolution_llm_id:
                skill_start_event = {
                    "type": "skill_resolution_start",
                    "task_id": task_id,
                    "iteration": task.iteration,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                yield f"data: {json.dumps(skill_start_event, ensure_ascii=False)}\n\n"
                # Yield control so the start event is flushed before any blocking work.
                await asyncio.sleep(0)

            available_skills = list_visible_skills(db, current_user.username)
            total_skill_count = len(available_skills)
            allowed_skills = _parse_name_allowlist(agent.skill_ids)
            if allowed_skills is not None:
                available_skills = [
                    item
                    for item in available_skills
                    if item.get("name") in allowed_skills
                ]
            candidate_skill_count = len(available_skills)
            allowed_skill_names: list[str] = []
            seen_skill_names: set[str] = set()
            for skill_item in available_skills:
                skill_name = skill_item.get("name")
                if (
                    not isinstance(skill_name, str)
                    or not skill_name
                    or skill_name in seen_skill_names
                ):
                    continue
                seen_skill_names.add(skill_name)
                allowed_skill_names.append(skill_name)

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
            allowed_tools = _parse_name_allowlist(agent.tool_ids)
            if allowed_tools is not None:
                filtered_manager = ToolManager()
                for meta in request_tool_manager.list_tools():
                    if meta.name in allowed_tools:
                        filtered_manager.add_entry(meta)
                request_tool_manager = filtered_manager

            allowed_skill_mounts = build_skill_mounts(
                db,
                current_user.username,
                allowed_skill_names,
            )

            # Warm up sandbox with the full allowed skill set so skill mounts are
            # ready before the first sandbox tool call in this task.
            try:
                from app.services.sandbox_service import get_sandbox_service

                get_sandbox_service().create(
                    username=current_user.username,
                    agent_id=agent.id or 0,
                    skills=allowed_skill_mounts,
                )
            except Exception as exc:
                logger.warning(
                    "Sandbox pre-create failed task_id=%s username=%s agent_id=%d err=%s",
                    task_id,
                    current_user.username,
                    agent.id or 0,
                    exc,
                )

            engine = ReactEngine(
                llm=llm,
                tool_manager=request_tool_manager,
                db=db,
                tool_execution_context=ToolExecutionContext(
                    username=current_user.username,
                    agent_id=agent.id or 0,
                    allowed_skills=tuple(allowed_skill_mounts),
                ),
                stream_llm_responses=bool(llm_config.streaming),
            )

            selected_skills: list[str] = []
            skill_resolution_tokens: dict[str, int] | None = None
            selected_skills_text = ""
            resolution_duration_ms = 0
            # Skill resolution is optional and only runs when a resolver LLM is configured.
            if agent.skill_resolution_llm_id:
                resolution_started_at = perf_counter()
                try:
                    resolver_llm_config = llm_crud.get(
                        agent.skill_resolution_llm_id, db
                    )
                    if resolver_llm_config:
                        resolver_llm = create_llm_from_config(resolver_llm_config)
                        session_memory = {}
                        if task.session_id:
                            session_memory = SessionMemoryService(
                                db
                            ).get_full_session_memory_dict(task.session_id)

                        selection_result = await run_in_threadpool(
                            select_skills_with_usage,
                            resolver_llm,
                            request.message,
                            available_skills,
                            session_memory,
                        )
                        raw_selected_skills = selection_result.get(
                            "selected_skills", []
                        )
                        if isinstance(raw_selected_skills, list):
                            selected_skills = [
                                item
                                for item in raw_selected_skills
                                if isinstance(item, str)
                            ]
                        else:
                            selected_skills = []
                        skill_resolution_tokens = selection_result.get("tokens")
                        selected_skills_text = build_selected_skills_prompt_block(
                            session=db,
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
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "count": len(selected_skills),
                        "selected_skills": selected_skills,
                        "total_skill_count": total_skill_count,
                        "candidate_skill_count": candidate_skill_count,
                        "duration_ms": resolution_duration_ms,
                        "tokens": skill_resolution_tokens,
                    },
                }
                task.skill_selection_result = json.dumps(
                    skill_result_event["data"],
                    ensure_ascii=False,
                )
                task.updated_at = datetime.now(UTC)
                db.add(task)
                db.commit()
                yield f"data: {json.dumps(skill_result_event, ensure_ascii=False)}\n\n"

            # Execute task and stream events
            async for event_data in engine.run_task(
                task=task,
                selected_skills_text=selected_skills_text,
                turn_user_message=request.message,
                turn_files=turn_files,
                turn_file_blocks=turn_file_blocks,
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
                        event_data.get("timestamp", datetime.now(UTC).isoformat())
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
                        timestamp=datetime.now(UTC),
                    )
                    yield f"data: {error_event.json()}\n\n"
                except (GeneratorExit, ConnectionResetError, BrokenPipeError):
                    pass
        finally:
            # Mark task as cancelled if client disconnected
            if client_disconnected and task:
                task.status = "cancelled"
                task.updated_at = datetime.now(UTC)
                try:
                    db.commit()
                    logger.info(f"Task {task.task_id} marked as cancelled")
                except Exception as e:
                    logger.error(f"Failed to mark task as cancelled: {e}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/react/context-usage",
    response_model=ReactContextUsageResponse,
)
async def estimate_react_context_usage(
    request: ReactContextUsageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Estimate the prompt-context usage for the current chat composer.

    Args:
        request: Context-estimation request payload.
        db: Database session dependency.
        current_user: Authenticated user requesting the estimate.

    Returns:
        Estimated prompt-window usage for the requested chat surface.

    Raises:
        HTTPException: If the agent, task, or uploaded files cannot be resolved.
    """
    service = ReactContextUsageService(db)
    try:
        return service.estimate(
            agent_id=request.agent_id,
            username=current_user.username,
            session_id=request.session_id,
            task_id=request.task_id,
            draft_message=request.draft_message,
            file_ids=request.file_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        .order_by(col(ReactRecursion.iteration_index))
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
        .order_by(col(ReactRecursionState.iteration_index))
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
