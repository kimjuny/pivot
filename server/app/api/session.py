"""API endpoints for session management."""

from datetime import UTC
from typing import Literal, cast

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.access import AccessLevel
from app.models.channel import AgentChannelBinding, ChannelSession
from app.models.session import Session
from app.models.user import User
from app.schemas.session import (
    ChatHistoryResponse,
    CurrentPlanRecursionSummary,
    CurrentPlanStep,
    FullSessionHistoryResponse,
    PendingUserActionPayload,
    RecursionDetail,
    SessionCreate,
    SessionListItem,
    SessionListResponse,
    SessionMigrateResponse,
    SessionResponse,
    SessionUpdate,
    TaskMessage,
    TaskSummary,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.permission_service import PermissionService
from app.services.provider_registry_service import ProviderRegistryService
from app.services.session_service import (
    SESSION_METADATA_UNSET,
    SessionService,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DBSession, col, select

router = APIRouter()


def enrich_sessions_with_channel_info(
    db: DBSession,
    session_ids: list[str],
    session_items: list[SessionListItem],
) -> None:
    """Batch-enrich SessionListItem objects with channel_key and channel_logo_url."""
    if not session_ids:
        return
    channel_session_rows = list(
        db.exec(
            select(ChannelSession).where(
                col(ChannelSession.pivot_session_id).in_(session_ids)
            )
        ).all()
    )
    if not channel_session_rows:
        return
    binding_ids = list({cs.channel_binding_id for cs in channel_session_rows})
    bindings = list(
        db.exec(
            select(AgentChannelBinding).where(
                col(AgentChannelBinding.id).in_(binding_ids)
            )
        ).all()
    )
    binding_map = {b.id: b for b in bindings}

    # Resolve logo_url per unique channel_key (one provider-registry call, not N).
    unique_keys = {b.channel_key for b in bindings}
    logo_url_map: dict[str, str | None] = {}
    registry = ProviderRegistryService(db)
    providers = registry.list_channel_providers()
    for provider in providers:
        if provider.manifest.key in unique_keys:
            logo_url_map[provider.manifest.key] = provider.manifest.logo_url

    session_channel_map: dict[str, tuple[str, str | None]] = {}
    for cs in channel_session_rows:
        binding = binding_map.get(cs.channel_binding_id)
        if binding:
            session_channel_map[cs.pivot_session_id] = (
                binding.channel_key,
                logo_url_map.get(binding.channel_key),
            )
    for item in session_items:
        ch = session_channel_map.get(item.session_id)
        if ch:
            item.channel_key = ch[0]
            item.channel_logo_url = ch[1]


def _session_access_level(
    session_type: Literal["client", "studio_test"],
) -> AccessLevel:
    """Return the agent access level required for one session type."""
    return AccessLevel.EDIT if session_type == "studio_test" else AccessLevel.USE


def _require_session_permission(
    db: DBSession,
    user: User,
    session_type: Literal["client", "studio_test"],
) -> None:
    required_permission = (
        Permission.AGENTS_MANAGE
        if session_type == "studio_test"
        else Permission.CLIENT_ACCESS
    )
    PermissionService(db).require_permissions(user, (required_permission,))


def _require_session_access(
    db: DBSession,
    user: User,
    session: Session,
) -> None:
    """Require both entry permission and agent access for one session row."""
    session_type = cast("Literal['client', 'studio_test']", session.type)
    _require_session_permission(db, user, session_type)
    agent = AgentService(db).get_required_agent(session.agent_id)
    AccessService(db).require_agent_access(
        user=user,
        agent=agent,
        access_level=_session_access_level(session_type),
    )


def _build_session_response(
    session: Session,
    *,
    test_workspace_hash: str | None = None,
    latest_release_id: int | None = None,
    is_stale: bool = False,
) -> SessionResponse:
    """Serialize one session row into the API response contract."""
    return SessionResponse(
        id=session.id or 0,
        session_id=session.session_id,
        agent_id=session.agent_id,
        type=cast("Literal['client', 'studio_test']", session.type),
        release_id=session.release_id,
        latest_release_id=latest_release_id,
        is_stale=is_stale,
        project_id=session.project_id,
        workspace_id=session.workspace_id,
        workspace_scope=SessionService.get_workspace_scope(session),
        test_workspace_hash=test_workspace_hash,
        user_id=session.user_id,
        status=session.status,
        runtime_status=session.runtime_status,
        title=session.title,
        is_pinned=session.is_pinned,
        migrated_to_session_id=session.migrated_to_session_id,
        created_at=session.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=session.updated_at.replace(tzinfo=UTC).isoformat(),
    )


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: SessionCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    """Create a new conversation session.

    Creates a new session for the specified agent.

    Args:
        request: Session creation request with agent_id.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Created session information.
    """
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    service = SessionService(db)
    try:
        _require_session_permission(db, current_user, request.type)
        agent = AgentService(db).get_required_agent(request.agent_id)
        AccessService(db).require_agent_access(
            user=current_user,
            agent=agent,
            access_level=(
                AccessLevel.EDIT if request.type == "studio_test" else AccessLevel.USE
            ),
        )
        test_snapshot_id: int | None = None
        if request.type == "studio_test":
            if request.test_snapshot is None:
                raise HTTPException(
                    status_code=400,
                    detail="studio_test sessions require test_snapshot",
                )
            test_snapshot = AgentSnapshotService(db).create_test_snapshot(
                request.agent_id,
                working_copy_snapshot=request.test_snapshot.model_dump(),
                created_by_user_id=current_user.id,
            )
            test_snapshot_id = test_snapshot.id
        session = service.create_session(
            agent_id=request.agent_id,
            user_id=current_user.id,
            project_id=request.project_id,
            session_type=request.type,
            test_snapshot_id=test_snapshot_id,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409
        if "not found" in detail:
            status_code = 404
        raise HTTPException(status_code=status_code, detail=detail) from exc

    test_workspace_hash = None
    if request.type == "studio_test" and test_snapshot_id is not None:
        test_workspace_hash = service.get_test_workspace_hashes([test_snapshot_id]).get(
            test_snapshot_id
        )

    latest_release_id = service.get_agent_active_release_ids([session.agent_id]).get(
        session.agent_id
    )
    return _build_session_response(
        session,
        test_workspace_hash=test_workspace_hash,
        latest_release_id=latest_release_id,
        is_stale=service.is_session_stale(session, latest_release_id),
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    agent_id: int | None = None,
    session_type: Literal["client", "studio_test"] | None = None,
    limit: int = 50,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionListResponse:
    """List all sessions for the current user.

    Args:
        agent_id: Optional filter by agent ID.
        limit: Maximum number of sessions to return.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        List of sessions with brief information.
    """
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="User not authenticated")
    if session_type is not None:
        _require_session_permission(db, current_user, session_type)
    else:
        PermissionService(db).require_permissions(
            current_user,
            (Permission.CLIENT_ACCESS,),
        )
    service = SessionService(db)
    sessions = service.get_sessions_by_user(
        user_id=current_user.id,
        agent_id=agent_id,
        session_type=session_type,
        limit=limit,
    )
    visible_sessions: list[Session] = []
    for session in sessions:
        try:
            _require_session_access(db, current_user, session)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        visible_sessions.append(session)
    test_snapshot_hashes = service.get_test_workspace_hashes(
        [
            session.test_snapshot_id
            for session in visible_sessions
            if session.test_snapshot_id is not None
        ]
    )
    active_release_ids = service.get_agent_active_release_ids(
        [session.agent_id for session in visible_sessions]
    )
    session_items = []
    for session in visible_sessions:
        latest_release_id = active_release_ids.get(session.agent_id)
        session_items.append(
            SessionListItem(
                session_id=session.session_id,
                agent_id=session.agent_id,
                type=cast("Literal['client', 'studio_test']", session.type),
                release_id=session.release_id,
                latest_release_id=latest_release_id,
                is_stale=service.is_session_stale(session, latest_release_id),
                migrated_to_session_id=session.migrated_to_session_id,
                project_id=session.project_id,
                workspace_id=session.workspace_id,
                workspace_scope=service.get_workspace_scope(session),
                test_workspace_hash=(
                    test_snapshot_hashes.get(session.test_snapshot_id or 0)
                    if session.test_snapshot_id is not None
                    else None
                ),
                status=session.status,
                runtime_status=session.runtime_status,
                title=session.title,
                is_pinned=session.is_pinned,
                created_at=session.created_at.replace(tzinfo=UTC).isoformat(),
                updated_at=session.updated_at.replace(tzinfo=UTC).isoformat(),
            )
        )

    # Batch-enrich sessions with channel info (ChannelSession → AgentChannelBinding → manifest)
    enrich_sessions_with_channel_info(
        db,
        [s.session_id for s in visible_sessions],
        session_items,
    )

    return SessionListResponse(
        sessions=session_items,
        total=len(session_items),
    )


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    """Get session information by session_id.

    Args:
        session_id: UUID of the session.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Session information.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    test_workspace_hash = None
    if session.test_snapshot_id is not None:
        test_workspace_hash = service.get_test_workspace_hashes(
            [session.test_snapshot_id]
        ).get(session.test_snapshot_id)
    latest_release_id = service.get_agent_active_release_ids([session.agent_id]).get(
        session.agent_id
    )
    return _build_session_response(
        session,
        test_workspace_hash=test_workspace_hash,
        latest_release_id=latest_release_id,
        is_stale=service.is_session_stale(session, latest_release_id),
    )


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: str,
    request: SessionUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    """Update user-managed session metadata such as title and pin state.

    Args:
        session_id: UUID of the session.
        request: Partial metadata update request from the chat sidebar.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Updated session information.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    updated_session = service.update_session_metadata(
        session_id,
        title=(
            request.title
            if "title" in request.model_fields_set
            else SESSION_METADATA_UNSET
        ),
        is_pinned=(
            request.is_pinned
            if "is_pinned" in request.model_fields_set
            else SESSION_METADATA_UNSET
        ),
    )
    if updated_session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    test_workspace_hash = None
    if updated_session.test_snapshot_id is not None:
        test_workspace_hash = service.get_test_workspace_hashes(
            [updated_session.test_snapshot_id]
        ).get(updated_session.test_snapshot_id)

    latest_release_id = service.get_agent_active_release_ids(
        [updated_session.agent_id]
    ).get(updated_session.agent_id)
    return _build_session_response(
        updated_session,
        test_workspace_hash=test_workspace_hash,
        latest_release_id=latest_release_id,
        is_stale=service.is_session_stale(updated_session, latest_release_id),
    )


@router.get("/sessions/{session_id}/history", response_model=ChatHistoryResponse)
async def get_session_history(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatHistoryResponse:
    """Get chat history for a session.

    Args:
        session_id: UUID of the session.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Chat history with all messages.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    messages = service.get_chat_history(session_id)

    from app.schemas.session import ChatHistoryMessage

    return ChatHistoryResponse(
        version=1,
        messages=[ChatHistoryMessage(**msg) for msg in messages],
    )


@router.get(
    "/sessions/{session_id}/full-history", response_model=FullSessionHistoryResponse
)
async def get_full_session_history(
    session_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    before_task_id: str | None = Query(default=None),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FullSessionHistoryResponse:
    """Get paginated session history with recursion details.

    Returns the latest tasks for a session with their complete recursion
    details, plus lightweight summaries of all tasks for anchor navigation.

    Args:
        session_id: UUID of the session.
        limit: Max number of full tasks to return.
        before_task_id: Cursor to load tasks older than this task.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Paginated session history with summaries, tasks and recursions.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    history_result = service.get_full_session_history(
        session_id, limit=limit, before_task_id=before_task_id
    )
    summaries_raw = service.get_task_summaries(session_id)

    # Convert summaries
    task_summaries = [
        TaskSummary(
            task_id=s["task_id"],
            preview=s["preview"],
            status=s["status"],
            created_at=s["created_at"].replace(tzinfo=UTC).isoformat(),
        )
        for s in summaries_raw
    ]

    # Convert tasks
    tasks = []
    for task_data in history_result["tasks"]:
        recursions = [
            RecursionDetail(
                iteration=r["iteration"],
                trace_id=r["trace_id"],
                input_message_json=r["input_message_json"],
                thinking=r["thinking"],
                message=r["message"],
                action_type=r["action_type"],
                action_output=r["action_output"],
                tool_call_results=r["tool_call_results"],
                status=r["status"],
                error_log=r["error_log"],
                prompt_tokens=r["prompt_tokens"],
                completion_tokens=r["completion_tokens"],
                total_tokens=r["total_tokens"],
                cached_input_tokens=r["cached_input_tokens"],
                created_at=r["created_at"].replace(tzinfo=UTC).isoformat(),
                updated_at=r["updated_at"].replace(tzinfo=UTC).isoformat(),
            )
            for r in task_data["recursions"]
        ]

        tasks.append(
            TaskMessage(
                task_id=task_data["task_id"],
                user_message=task_data["user_message"],
                files=task_data.get("files", []),
                assistant_attachments=task_data.get("assistant_attachments", []),
                agent_answer=task_data["agent_answer"],
                status=task_data["status"],
                total_tokens=task_data["total_tokens"],
                pending_user_action=(
                    PendingUserActionPayload.model_validate(
                        task_data["pending_user_action"]
                    )
                    if isinstance(task_data.get("pending_user_action"), dict)
                    else None
                ),
                current_plan=[
                    CurrentPlanStep(
                        step_id=step["step_id"],
                        general_goal=step["general_goal"],
                        specific_description=step["specific_description"],
                        completion_criteria=step["completion_criteria"],
                        status=step["status"],
                        recursion_history=[
                            CurrentPlanRecursionSummary(
                                iteration=entry.get("iteration"),
                                message=entry.get("message", ""),
                            )
                            for entry in step.get("recursion_history", [])
                            if isinstance(entry, dict)
                        ],
                    )
                    for step in task_data.get("current_plan", [])
                    if isinstance(step, dict)
                ],
                recursions=recursions,
                created_at=task_data["created_at"].replace(tzinfo=UTC).isoformat(),
                updated_at=task_data["updated_at"].replace(tzinfo=UTC).isoformat(),
            )
        )

    return FullSessionHistoryResponse(
        session_id=session_id,
        total_task_count=history_result["total_task_count"],
        has_more_older=history_result["has_more_older"],
        task_summaries=task_summaries,
        tasks=tasks,
        last_event_id=service.get_last_task_event_id(session_id),
        resume_from_event_id=service.get_resume_from_task_event_id(session_id),
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a session and its associated data.

    Args:
        session_id: UUID of the session.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Success message.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    if service.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete session")


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
async def close_session(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    """Mark a session as closed while preserving its history and workspace.

    Why: stale sessions need a non-destructive exit so the user can still
    review the previous conversation after switching to a new release.
    """
    service = SessionService(db)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    service.update_session_status(session_id, "closed")
    updated_session = service.get_session(session_id)
    if updated_session is None:
        raise HTTPException(status_code=500, detail="Failed to close session")

    test_workspace_hash = None
    if updated_session.test_snapshot_id is not None:
        test_workspace_hash = service.get_test_workspace_hashes(
            [updated_session.test_snapshot_id]
        ).get(updated_session.test_snapshot_id)
    latest_release_id = service.get_agent_active_release_ids(
        [updated_session.agent_id]
    ).get(updated_session.agent_id)
    return _build_session_response(
        updated_session,
        test_workspace_hash=test_workspace_hash,
        latest_release_id=latest_release_id,
        is_stale=service.is_session_stale(updated_session, latest_release_id),
    )


@router.post("/sessions/{session_id}/migrate", response_model=SessionMigrateResponse)
async def migrate_session(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionMigrateResponse:
    """Migrate a stale client session onto the agent's latest release.

    Creates a new session pinned to ``agent.active_release_id``, copies
    workspace contents for session-private workspaces, and marks the old
    session closed (history preserved).
    """
    service = SessionService(db)
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    _require_session_access(db, current_user, session)

    try:
        new_session = service.migrate_stale_session(session_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return SessionMigrateResponse(
        old_session_id=session_id,
        new_session_id=new_session.session_id,
        new_release_id=new_session.release_id,
    )
