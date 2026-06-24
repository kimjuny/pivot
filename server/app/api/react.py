"""API endpoints for reconnectable ReAct task execution and observation."""

import asyncio
import logging

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.access import AccessLevel
from app.models.agent import Agent
from app.models.react import ReactRecursion, ReactTask
from app.models.session import Session as ConversationSession
from app.models.user import User
from app.schemas.react import (
    EditPlanRequest,
    ReactChatRequest,
    ReactContextUsageRequest,
    ReactContextUsageResponse,
    ReactMidTaskInputRequest,
    ReactMidTaskInputResponse,
    ReactPendingUserActionRequest,
    ReactRuntimeSkillItem,
    ReactRuntimeSkillsRequest,
    ReactSessionCompactRequest,
    ReactSessionCompactResponse,
    ReactSessionRuntimeDebugResponse,
    ReactStreamEvent,
    ReactTaskCancelResponse,
    ReactTaskStartResponse,
    TaskEditRequest,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.permission_service import PermissionService
from app.services.react_compact_service import ReactCompactService
from app.services.react_context_service import ReactContextUsageService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.react_task_supervisor import (
    ReactTaskLaunchRequest,
    get_react_task_supervisor,
)
from app.services.sandbox_service import get_sandbox_service
from app.services.session_service import SessionService
from app.services.workspace_service import WorkspaceService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlmodel import Session, col, select

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


def _session_access_level(session_type: str) -> AccessLevel:
    """Return the agent access level required for one runtime session type."""
    return AccessLevel.EDIT if session_type == "studio_test" else AccessLevel.USE


def _require_runtime_permission(
    *,
    db: Session,
    user: User,
    session_type: str,
) -> None:
    """Require the system-level entry permission for one runtime surface."""
    required_permission = (
        Permission.AGENTS_MANAGE
        if session_type == "studio_test"
        else Permission.CLIENT_ACCESS
    )
    PermissionService(db).require_permissions(user, (required_permission,))


def _require_agent_runtime_access(
    *,
    db: Session,
    user: User,
    agent: Agent,
    session_type: str,
) -> None:
    """Require the caller to still have access to the runtime agent surface."""
    AccessService(db).require_agent_access(
        user=user,
        agent=agent,
        access_level=_session_access_level(session_type),
    )


def _get_owned_task(
    *,
    db: Session,
    task_id: str,
    user: User,
) -> ReactTask:
    """Load one task row and require ownership."""
    task = db.exec(select(ReactTask).where(ReactTask.task_id == task_id)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return task


def _get_owned_session(
    *,
    db: Session,
    session_id: str,
    user: User,
) -> ConversationSession:
    """Load one session row and require ownership."""
    session = SessionService(db).get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return session


def _resolve_runtime_agent_for_request(
    *,
    db: Session,
    request: ReactChatRequest,
    user: User,
) -> tuple[Agent, ConversationSession | None]:
    """Resolve the agent and optional session targeted by one runtime request.

    Why: runtime execution needs one shared gate that enforces ownership for
    resumed sessions and blocks further interaction when an agent has been
    disabled for end users.
    """
    agent_service = AgentService(db)
    session_row: ConversationSession | None = None
    if request.session_id is not None:
        session_row = _get_owned_session(
            db=db,
            session_id=request.session_id,
            user=user,
        )
        if session_row.agent_id != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Session does not belong to the requested agent",
            )
    elif request.task_id is not None:
        task = _get_owned_task(
            db=db,
            task_id=request.task_id,
            user=user,
        )
        if task.agent_id != request.agent_id:
            raise HTTPException(
                status_code=400,
                detail="Task does not belong to the requested agent",
            )
        if task.session_id is not None:
            session_row = _get_owned_session(
                db=db,
                session_id=task.session_id,
                user=user,
            )

    try:
        if session_row is not None and session_row.type == "studio_test":
            agent = agent_service.get_required_agent(request.agent_id)
        else:
            agent = agent_service.require_interaction_enabled(request.agent_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    if session_row is not None and SessionService.is_session_stale(
        session_row, agent.active_release_id
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_stale",
                "message": (
                    "Agent has been republished. Migrate this session or "
                    "start a new one."
                ),
                "latest_release_id": agent.active_release_id,
            },
        )

    _require_runtime_permission(
        db=db,
        user=user,
        session_type=session_row.type if session_row is not None else "client",
    )
    _require_agent_runtime_access(
        db=db,
        user=user,
        agent=agent,
        session_type=session_row.type if session_row is not None else "client",
    )
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
                yield f"data: {ReactStreamEvent(**payload).model_dump_json()}\n\n"

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
                yield f"data: {ReactStreamEvent(**payload).model_dump_json()}\n\n"
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
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    if request.message is None or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="message is required")
    _resolve_runtime_agent_for_request(
        db=db,
        request=request,
        user=current_user,
    )

    supervisor = get_react_task_supervisor()
    try:
        launch_result = await supervisor.start_task(
            ReactTaskLaunchRequest(
                agent_id=request.agent_id,
                message=request.message,
                user_id=current_user.id,
                session_id=request.session_id,
                file_ids=request.file_ids,
                web_search_provider=request.web_search_provider,
                thinking_enabled=request.thinking_enabled,
                mandatory_skill_names=request.mandatory_skill_names,
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


@router.post("/react/tasks/{task_id}/edit", response_model=ReactTaskStartResponse)
async def edit_react_task(
    task_id: str,
    request: TaskEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactTaskStartResponse:
    """Edit a completed task: rewind conversation to that point and resubmit."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")

    task = _get_owned_task(db=db, task_id=task_id, user=current_user)

    if task.status not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot edit task with status '{task.status}'",
        )
    if not task.session_id:
        raise HTTPException(
            status_code=400,
            detail="Task has no associated session",
        )

    session = _get_owned_session(db=db, session_id=task.session_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = session.type
    _require_runtime_permission(db=db, user=current_user, session_type=session_type)
    _require_agent_runtime_access(
        db=db, user=current_user, agent=agent, session_type=session_type
    )

    if session.runtime_status == "running":
        raise HTTPException(
            status_code=409,
            detail="Cannot edit while a task is running",
        )

    # Restore sandbox files when full rewind is requested.
    if request.rewind_scope == "full":
        if not task.sandbox_checkpoint_hash:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot undo file changes: no sandbox checkpoint exists for "
                    "this task. The checkpoint may have failed when the task "
                    "started. Use 'Rewind conversation only' instead."
                ),
            )
        if session.workspace_id:
            workspace = WorkspaceService(db).get_workspace(session.workspace_id)
            if workspace is not None:
                workspace_backend_path = WorkspaceService(
                    db
                ).get_workspace_backend_path(workspace)
                try:
                    get_sandbox_service().restore(
                        user_id=current_user.id,
                        workspace_id=workspace.workspace_id,
                        workspace_backend_path=workspace_backend_path,
                        commit_hash=task.sandbox_checkpoint_hash,
                    )
                except Exception as exc:
                    logger.warning(
                        "sandbox.restore failed for edit task=%s hash=%s: %s",
                        task_id,
                        task.sandbox_checkpoint_hash[:12],
                        exc,
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to restore sandbox: {exc}",
                    ) from exc

    SessionService(db).rewind_tasks_from(
        session_id=session.session_id,
        from_task_id=task.task_id,
    )

    supervisor = get_react_task_supervisor()
    try:
        launch_result = await supervisor.start_task(
            ReactTaskLaunchRequest(
                agent_id=task.agent_id,
                message=request.new_message,
                user_id=current_user.id,
                session_id=session.session_id,
                file_ids=[],
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactTaskStartResponse:
    """Submit one structured approve/reject decision for a waiting task."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session_type,
    )

    supervisor = get_react_task_supervisor()
    try:
        launch_result = await supervisor.submit_pending_user_action(
            task_id=task_id,
            user_id=current_user.id,
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
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    supervisor = get_react_task_supervisor()
    task = supervisor.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != current_user.id:
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


@router.post(
    "/react/tasks/{task_id}/mid-task-input",
    response_model=ReactMidTaskInputResponse,
)
async def submit_mid_task_input(
    task_id: str,
    request: ReactMidTaskInputRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactMidTaskInputResponse:
    """Inject a user message into the next iteration of a running task."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    if task.status != "running":
        raise HTTPException(
            status_code=409,
            detail=f"Task is not running (status={task.status})",
        )
    if not task.session_id:
        raise HTTPException(
            status_code=400,
            detail="Task has no session to enqueue input into",
        )

    from app.services.session_task_queue_service import SessionTaskQueueService

    queue_svc = SessionTaskQueueService(db)
    item = queue_svc.enqueue(
        session_id=task.session_id,
        queue_type="immediate_insert",
        source="user_input",
        prompt=request.message,
    )
    return ReactMidTaskInputResponse(
        queue_id=item.queue_id,
        status=item.status,
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
    session = _get_owned_session(db=db, session_id=session_id, user=current_user)
    agent = AgentService(db).get_required_agent(session.agent_id)
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session.type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session.type,
    )

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
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    session_id = request.session_id
    if session_id is None:
        raise HTTPException(
            status_code=400,
            detail="session_id is required for reconnectable chat streaming",
        )
    _resolve_runtime_agent_for_request(
        db=db,
        request=request,
        user=current_user,
    )

    supervisor = get_react_task_supervisor()
    if request.message is None or request.message.strip() == "":
        raise HTTPException(status_code=400, detail="message is required")
    try:
        launch_result = await supervisor.start_task(
            ReactTaskLaunchRequest(
                agent_id=request.agent_id,
                message=request.message,
                user_id=current_user.id,
                session_id=session_id,
                file_ids=request.file_ids,
                web_search_provider=request.web_search_provider,
                thinking_enabled=request.thinking_enabled,
                mandatory_skill_names=request.mandatory_skill_names,
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
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    agent = AgentService(db).get_required_agent(request.agent_id)
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=request.session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=request.session_type,
    )
    service = ReactContextUsageService(db)
    try:
        return service.estimate(
            agent_id=request.agent_id,
            user_id=current_user.id,
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
            mandatory_skill_names=request.mandatory_skill_names,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/react/runtime-skills",
    response_model=list[ReactRuntimeSkillItem],
)
async def list_react_runtime_skills(
    request: ReactRuntimeSkillsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, str]]:
    """List the skills currently visible to one chat runtime."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    agent = AgentService(db).get_required_agent(request.agent_id)
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=request.session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=request.session_type,
    )
    service = ReactContextUsageService(db)
    try:
        return service.list_runtime_skills(
            agent_id=request.agent_id,
            user_id=current_user.id,
            session_id=request.session_id,
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
    session = _get_owned_session(db=db, session_id=session_id, user=current_user)
    agent = AgentService(db).get_required_agent(session.agent_id)
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session.type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session.type,
    )

    payload = ReactRuntimeService(db).build_runtime_debug_payload(session_id)
    return ReactSessionRuntimeDebugResponse(**payload)


@router.post(
    "/react/sessions/{session_id}/compact",
    response_model=ReactSessionCompactResponse,
)
async def compact_react_session(
    session_id: str,
    request: ReactSessionCompactRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReactSessionCompactResponse:
    """Execute one user-triggered compact pass for an idle session runtime."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    session = _get_owned_session(db=db, session_id=session_id, user=current_user)
    agent = AgentService(db).get_required_agent(session.agent_id)
    if SessionService.is_session_stale(session, agent.active_release_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_stale",
                "message": (
                    "Agent has been republished. Migrate this session or start a new one."
                ),
                "latest_release_id": agent.active_release_id,
            },
        )
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session.type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session.type,
    )

    service = ReactCompactService(db)
    try:
        payload = await service.compact_session(
            session_id=session_id,
            user_instruction=request.instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReactSessionCompactResponse(**payload)


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
    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session_type,
    )

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
    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session_type,
    )

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

    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session_type,
    )

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

    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(
        db=db,
        user=current_user,
        session_type=session_type,
    )
    _require_agent_runtime_access(
        db=db,
        user=current_user,
        agent=agent,
        session_type=session_type,
    )

    stmt = (
        select(ReactRecursionState)
        .where(ReactRecursionState.task_id == task_id)
        .where(ReactRecursionState.iteration_index == iteration_index)
    )
    state = db.exec(stmt).first()

    if not state:
        return {"error": "State not found"}, 404

    return state


# ---------------------------------------------------------------------------
# Plan API — read and edit plan files for a task
# ---------------------------------------------------------------------------


@router.get("/react/tasks/{task_id}/plan")
async def get_task_plan(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the plan Markdown content and structured steps for a task.

    Reads from ``{workspace}/.pivot/plans/{task_id}.md`` and ``.json``.
    """
    from app.orchestration.react.plan_files import (
        plan_exists,
        read_plan_text,
        read_steps,
    )

    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(db=db, user=current_user, session_type=session_type)
    _require_agent_runtime_access(
        db=db, user=current_user, agent=agent, session_type=session_type
    )

    workspace_path = _resolve_task_workspace_path(db, task)
    if not workspace_path or not plan_exists(workspace_path, task_id):
        return {"plan_text": None, "steps": []}

    return {
        "plan_text": read_plan_text(workspace_path, task_id),
        "steps": read_steps(workspace_path, task_id),
    }


@router.put("/react/tasks/{task_id}/plan")
async def edit_task_plan(
    task_id: str,
    body: EditPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Overwrite the plan Markdown content (user-edited plan from review panel).

    Only writes the ``.md`` file; the structured ``.json`` steps remain
    unchanged.  The agent re-reads the file on the next recursion.
    """
    from app.orchestration.react.plan_files import plan_exists, write_plan_text

    task = _get_owned_task(db=db, task_id=task_id, user=current_user)
    agent = AgentService(db).get_required_agent(task.agent_id)
    session_type = "client"
    if task.session_id is not None:
        session = _get_owned_session(
            db=db, session_id=task.session_id, user=current_user
        )
        session_type = session.type
    _require_runtime_permission(db=db, user=current_user, session_type=session_type)
    _require_agent_runtime_access(
        db=db, user=current_user, agent=agent, session_type=session_type
    )

    workspace_path = _resolve_task_workspace_path(db, task)
    if not workspace_path or not plan_exists(workspace_path, task_id):
        return {"success": False, "error": "No plan found for this task"}

    write_plan_text(workspace_path, task_id, body.plan_text)

    return {"success": True}


def _resolve_task_workspace_path(db, task: ReactTask) -> str | None:
    """Resolve the backend workspace path for a task's session."""
    from app.services.workspace_service import WorkspaceService

    if not task.session_id:
        return None
    session = db.exec(
        select(ConversationSession).where(
            ConversationSession.session_id == task.session_id
        )
    ).first()
    if not session or not session.workspace_id:
        return None
    workspace = WorkspaceService(db).get_workspace(session.workspace_id)
    if not workspace:
        return None
    return WorkspaceService(db).get_workspace_backend_path(workspace)
