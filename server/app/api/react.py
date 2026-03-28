"""API endpoints for reconnectable ReAct task execution and observation."""

import asyncio
import logging

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.models.react import ReactRecursion, ReactTask
from app.models.session import Session as ConversationSession
from app.models.user import User
from app.schemas.react import (
    ReactChatRequest,
    ReactContextUsageRequest,
    ReactContextUsageResponse,
    ReactPendingUserActionRequest,
    ReactSessionRuntimeDebugResponse,
    ReactStreamEvent,
    ReactTaskCancelResponse,
    ReactTaskStartResponse,
)
from app.services.agent_service import AgentService
from app.services.react_context_service import ReactContextUsageService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.react_task_supervisor import (
    ReactTaskLaunchRequest,
    get_react_task_supervisor,
)
from app.services.session_service import SessionService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_runtime_agent_for_request(
    *,
    db: Session,
    request: ReactChatRequest,
    username: str,
) -> tuple[Agent, ConversationSession | None]:
    """Resolve the agent and optional session targeted by one runtime request.

    Why: runtime execution needs one shared gate that enforces ownership for
    resumed sessions and blocks further interaction when an agent has been
    disabled for end users.
    """
    agent_service = AgentService(db)
    session_service = SessionService(db)

    session_row: ConversationSession | None = None
    if request.session_id is not None:
        session_row = session_service.get_session(request.session_id)
        if session_row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if session_row.user != username:
            raise HTTPException(status_code=403, detail="Access denied")
        if session_row.agent_id != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Session does not belong to the requested agent",
            )
    elif request.task_id is not None:
        task = db.exec(
            select(ReactTask).where(ReactTask.task_id == request.task_id)
        ).first()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.user != username:
            raise HTTPException(status_code=403, detail="Access denied")
        if task.agent_id != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Task does not belong to the requested agent",
            )
        if task.session_id is not None:
            session_row = session_service.get_session(task.session_id)
            if session_row is None:
                raise HTTPException(status_code=404, detail="Session not found")

    try:
        if session_row is not None and session_row.type == "studio_test":
            agent = agent_service.get_required_agent(request.agent_id)
        else:
            agent = agent_service.require_interaction_enabled(request.agent_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return agent, session_row


async def _stream_supervisor_events(
    *,
    raw_request: Request,
    session_id: str,
    after_id: int,
    task_id: str | None = None,
) -> StreamingResponse:
    """Stream persisted and live task events for one session."""
    supervisor = get_react_task_supervisor()

    async def event_generator():
        cursor = after_id
        subscriber = await supervisor.subscribe(session_id=session_id, task_id=task_id)
        try:
            for payload in supervisor.list_events(
                session_id=session_id,
                after_id=cursor,
                task_id=task_id,
            ):
                event_id = payload.get("event_id")
                if isinstance(event_id, int):
                    cursor = max(cursor, event_id)
                yield f"data: {ReactStreamEvent(**payload).json()}\n\n"

            while True:
                if await raw_request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=15.0
                    )
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                event_id = payload.get("event_id")
                if isinstance(event_id, int) and event_id <= cursor:
                    continue
                if isinstance(event_id, int):
                    cursor = event_id
                yield f"data: {ReactStreamEvent(**payload).json()}\n\n"
        finally:
            await supervisor.unsubscribe(session_id=session_id, subscriber=subscriber)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/react/tasks", response_model=ReactTaskStartResponse)
async def start_react_task(
    request: ReactChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactTaskStartResponse:
    """Queue one ReAct task for background execution."""
    if request.message is None or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="message is required")
    _resolve_runtime_agent_for_request(
        db=db,
        request=request,
        username=current_user.username,
    )

    supervisor = get_react_task_supervisor()
    try:
        launch_result = await supervisor.start_task(
            ReactTaskLaunchRequest(
                agent_id=request.agent_id,
                message=request.message,
                username=current_user.username,
                session_id=request.session_id,
                file_ids=request.file_ids,
                web_search_provider=request.web_search_provider,
                thinking_mode=request.thinking_mode,
                task_id=request.task_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReactTaskStartResponse(
        task_id=launch_result.task_id,
        session_id=launch_result.session_id,
        status=launch_result.status,
        cursor_before_start=launch_result.cursor_before_start,
    )


@router.post(
    "/react/tasks/{task_id}/user-action", response_model=ReactTaskStartResponse
)
async def submit_react_user_action(
    task_id: str,
    request: ReactPendingUserActionRequest,
    current_user: User = Depends(get_current_user),
) -> ReactTaskStartResponse:
    """Submit one structured approve/reject decision for a waiting task."""
    supervisor = get_react_task_supervisor()
    try:
        launch_result = await supervisor.submit_pending_user_action(
            task_id=task_id,
            username=current_user.username,
            decision=request.decision,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReactTaskStartResponse(
        task_id=launch_result.task_id,
        session_id=launch_result.session_id,
        status=launch_result.status,
        cursor_before_start=launch_result.cursor_before_start,
    )


@router.post("/react/tasks/{task_id}/cancel", response_model=ReactTaskCancelResponse)
async def cancel_react_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> ReactTaskCancelResponse:
    """Request cancellation for one running ReAct task."""
    supervisor = get_react_task_supervisor()
    task = supervisor.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    cancel_requested = await supervisor.request_cancel(task_id)
    refreshed_task = supervisor.get_task(task_id)
    if refreshed_task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return ReactTaskCancelResponse(
        task_id=task_id,
        status=refreshed_task.status,
        cancel_requested=cancel_requested
        or refreshed_task.cancel_requested_at is not None,
    )


@router.get("/react/sessions/{session_id}/events/stream")
async def stream_react_session_events(
    session_id: str,
    raw_request: Request,
    after_id: int = 0,
    task_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream reconnectable ReAct task events for one session."""
    from app.services.session_service import SessionService

    session = SessionService(db).get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    return await _stream_supervisor_events(
        raw_request=raw_request,
        session_id=session_id,
        after_id=after_id,
        task_id=task_id,
    )


@router.post("/react/chat/stream")
async def react_chat_stream(
    request: ReactChatRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compatibility stream that starts a task then tails its events."""
    session_id = request.session_id
    if session_id is None:
        raise HTTPException(
            status_code=400,
            detail="session_id is required for reconnectable chat streaming",
        )
    _resolve_runtime_agent_for_request(
        db=db,
        request=request,
        username=current_user.username,
    )

    supervisor = get_react_task_supervisor()
    if request.message is None or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="message is required")
    try:
        launch_result = await supervisor.start_task(
            ReactTaskLaunchRequest(
                agent_id=request.agent_id,
                message=request.message,
                username=current_user.username,
                session_id=session_id,
                file_ids=request.file_ids,
                web_search_provider=request.web_search_provider,
                thinking_mode=request.thinking_mode,
                task_id=request.task_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _stream_supervisor_events(
        raw_request=raw_request,
        session_id=session_id,
        after_id=launch_result.cursor_before_start,
        task_id=launch_result.task_id,
    )


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
            session_type=request.session_type,
            test_snapshot=(
                request.test_snapshot.model_dump()
                if request.test_snapshot is not None
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/react/sessions/{session_id}/runtime-debug",
    response_model=ReactSessionRuntimeDebugResponse,
)
async def get_react_session_runtime_debug(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactSessionRuntimeDebugResponse:
    """Return the persisted runtime-window debug snapshot for one session."""
    from app.services.session_service import SessionService

    session = SessionService(db).get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    payload = ReactRuntimeService(db).build_runtime_debug_payload(session_id)
    return ReactSessionRuntimeDebugResponse(**payload)


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

    stmt = (
        select(ReactRecursionState)
        .where(ReactRecursionState.task_id == task_id)
        .where(ReactRecursionState.iteration_index == iteration_index)
    )
    state = db.exec(stmt).first()

    if not state:
        return {"error": "State not found"}, 404

    return state
