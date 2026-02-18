"""API endpoints for Session management.

This module provides REST endpoints for managing conversation sessions
and their associated memory.
"""

import json
import logging
from datetime import timezone

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.schemas.session import (
    ChatHistoryResponse,
    FullSessionHistoryResponse,
    RecursionDetail,
    SessionCreate,
    SessionListItem,
    SessionListResponse,
    SessionMemoryResponse,
    SessionResponse,
    TaskMessage,
)
from app.services.session_memory_service import SessionMemoryService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    request: SessionCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionResponse:
    """Create a new conversation session.

    Creates a new session with empty memory for the specified agent.

    Args:
        request: Session creation request with agent_id.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Created session information.
    """
    service = SessionMemoryService(db)
    session = service.create_session(
        agent_id=request.agent_id,
        user=current_user.username,
    )

    return SessionResponse(
        id=session.id or 0,
        session_id=session.session_id,
        agent_id=session.agent_id,
        user=session.user,
        status=session.status,
        subject=json.loads(session.subject) if session.subject else None,
        object=json.loads(session.object) if session.object else None,
        created_at=session.created_at.replace(tzinfo=timezone.utc).isoformat(),
        updated_at=session.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    )


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
    service = SessionMemoryService(db)
    sessions = service.get_sessions_by_user(
        user=current_user.username,
        agent_id=agent_id,
        limit=limit,
    )

    session_items = []
    for session in sessions:
        # Get message count from chat history
        try:
            history = json.loads(session.chat_history or '{"messages": []}')
            message_count = len(history.get("messages", []))
        except json.JSONDecodeError:
            message_count = 0

        # Get subject content string
        subject_str = None
        if session.subject:
            try:
                subject_data = json.loads(session.subject)
                subject_str = subject_data.get("content")
            except json.JSONDecodeError:
                pass

        session_items.append(
            SessionListItem(
                session_id=session.session_id,
                agent_id=session.agent_id,
                status=session.status,
                subject=subject_str,
                created_at=session.created_at.replace(tzinfo=timezone.utc).isoformat(),
                updated_at=session.updated_at.replace(tzinfo=timezone.utc).isoformat(),
                message_count=message_count,
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
    service = SessionMemoryService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    return SessionResponse(
        id=session.id or 0,
        session_id=session.session_id,
        agent_id=session.agent_id,
        user=session.user,
        status=session.status,
        subject=json.loads(session.subject) if session.subject else None,
        object=json.loads(session.object) if session.object else None,
        created_at=session.created_at.replace(tzinfo=timezone.utc).isoformat(),
        updated_at=session.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    )


@router.get("/sessions/{session_id}/memory", response_model=SessionMemoryResponse)
async def get_session_memory(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SessionMemoryResponse:
    """Get full session memory by session_id.

    Returns the complete session memory structure as described
    in context_template.md section 8.2.

    Args:
        session_id: UUID of the session.
        db: Database session dependency.
        current_user: Authenticated user.

    Returns:
        Complete session memory structure.

    Raises:
        HTTPException: If session not found or access denied.
    """
    service = SessionMemoryService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    memory_dict = service.get_full_session_memory_dict(session_id)

    return SessionMemoryResponse(**memory_dict)


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
    service = SessionMemoryService(db)
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


@router.get("/sessions/{session_id}/full-history", response_model=FullSessionHistoryResponse)
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
    service = SessionMemoryService(db)
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
                thought=r["thought"],
                abstract=r["abstract"],
                action_type=r["action_type"],
                action_output=r["action_output"],
                tool_call_results=r["tool_call_results"],
                status=r["status"],
                prompt_tokens=r["prompt_tokens"],
                completion_tokens=r["completion_tokens"],
                total_tokens=r["total_tokens"],
                created_at=r["created_at"].replace(tzinfo=timezone.utc).isoformat(),
                updated_at=r["updated_at"].replace(tzinfo=timezone.utc).isoformat(),
            )
            for r in task_data["recursions"]
        ]

        tasks.append(TaskMessage(
            task_id=task_data["task_id"],
            user_message=task_data["user_message"],
            agent_answer=task_data["agent_answer"],
            status=task_data["status"],
            total_tokens=task_data["total_tokens"],
            recursions=recursions,
            created_at=task_data["created_at"].replace(tzinfo=timezone.utc).isoformat(),
            updated_at=task_data["updated_at"].replace(tzinfo=timezone.utc).isoformat(),
        ))

    return FullSessionHistoryResponse(
        session_id=session_id,
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
    service = SessionMemoryService(db)
    session = service.get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if session.user != current_user.username:
        raise HTTPException(status_code=403, detail="Access denied")

    if service.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete session")
