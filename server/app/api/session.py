"""API endpoints for session management."""

from datetime import UTC

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.session import Session
from app.models.user import User
from app.schemas.session import (
    ChatHistoryResponse,
    CurrentPlanRecursionSummary,
    CurrentPlanStep,
    FullSessionHistoryResponse,
    RecursionDetail,
    SessionCreate,
    SessionListItem,
    SessionListResponse,
    SessionResponse,
    SessionUpdate,
    TaskMessage,
)
from app.services.session_service import (
    SESSION_METADATA_UNSET,
    SessionService,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session as DBSession

router = APIRouter()


def _build_session_response(session: Session) -> SessionResponse:
    """Serialize one session row into the API response contract."""
    return SessionResponse(
        id=session.id or 0,
        session_id=session.session_id,
        agent_id=session.agent_id,
        user=session.user,
        status=session.status,
        title=session.title,
        is_pinned=session.is_pinned,
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
    service = SessionService(db)
    session = service.create_session(
        agent_id=request.agent_id,
        user=current_user.username,
    )

    return _build_session_response(session)


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    agent_id: int | None = None,
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
    service = SessionService(db)
    sessions = service.get_sessions_by_user(
        user=current_user.username,
        agent_id=agent_id,
        limit=limit,
    )

    session_items = []
    for session in sessions:
        session_items.append(
            SessionListItem(
                session_id=session.session_id,
                agent_id=session.agent_id,
                status=session.status,
                title=session.title,
                is_pinned=session.is_pinned,
                created_at=session.created_at.replace(tzinfo=UTC).isoformat(),
                updated_at=session.updated_at.replace(tzinfo=UTC).isoformat(),
            )
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

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    return _build_session_response(session)


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

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

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

    return _build_session_response(updated_session)


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

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

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
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FullSessionHistoryResponse:
    """Get full session history with recursion details.

    Returns all tasks for a session with their complete recursion details,
    suitable for rendering the full conversation history in the UI.

    Args:
        session_id: UUID of the session.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Full session history with tasks and recursions.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    tasks_data = service.get_full_session_history(session_id)

    # Convert to response schema
    tasks = []
    for task_data in tasks_data:
        recursions = [
            RecursionDetail(
                iteration=r["iteration"],
                trace_id=r["trace_id"],
                observe=r["observe"],
                thinking=r["thinking"],
                thought=r["thought"],
                abstract=r["abstract"],
                summary=r["summary"],
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
                agent_answer=task_data["agent_answer"],
                status=task_data["status"],
                total_tokens=task_data["total_tokens"],
                skill_selection_result=task_data.get("skill_selection_result"),
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
                                summary=entry.get("summary", ""),
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
        last_event_id=service.get_last_task_event_id(session_id),
        resume_from_event_id=service.get_resume_from_task_event_id(session_id),
        tasks=tasks,
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

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    if service.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete session")
