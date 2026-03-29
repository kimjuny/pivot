"""Studio Operations API — admin-scoped session inspection endpoints."""

from datetime import UTC
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.models.agent_release import AgentRelease
from app.models.react import ReactTask
from app.models.user import User
from app.schemas.session import (
    CurrentPlanRecursionSummary,
    CurrentPlanStep,
    PendingUserActionPayload,
    RecursionDetail,
    TaskMessage,
)
from app.services.session_service import SessionService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session as DBSession, col, func, select

router = APIRouter()


def _resolve_agent_names(db: DBSession, agent_ids: list[int]) -> dict[int, str]:
    """Batch-resolve agent names for a list of agent IDs."""
    if not agent_ids:
        return {}
    stmt = select(Agent).where(col(Agent.id).in_(agent_ids))
    return {
        agent.id: agent.name for agent in db.exec(stmt).all() if agent.id is not None
    }


def _resolve_release_versions(db: DBSession, release_ids: list[int]) -> dict[int, int]:
    """Batch-resolve release version numbers for a list of release IDs."""
    if not release_ids:
        return {}
    stmt = select(AgentRelease).where(col(AgentRelease.id).in_(release_ids))
    return {
        release.id: release.version
        for release in db.exec(stmt).all()
        if release.id is not None
    }


def _resolve_task_counts(db: DBSession, session_ids: list[str]) -> dict[str, int]:
    """Count ReactTask rows per session UUID."""
    if not session_ids:
        return {}
    # SQLAlchemy's select() with grouped columns doesn't fully satisfy
    # pyright's strict type checking for nullable columns.
    stmt = (
        select(ReactTask.session_id, func.count(ReactTask.id))  # type: ignore[reportArgumentType, reportCallIssue]
        .where(col(ReactTask.session_id).in_(session_ids))
        .group_by(ReactTask.session_id)
    )
    return {
        session_id: count
        for session_id, count in db.exec(stmt).all()
        if session_id is not None
    }


@router.get("/operations/sessions")
async def list_operations_sessions(
    agent_id: int | None = None,
    status: str | None = None,
    session_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all sessions across users for Studio Operations.

    Args:
        agent_id: Optional agent filter.
        status: Optional session status filter.
        session_type: Optional session type filter.
        page: 1-based page number.
        page_size: Items per page (max 100).
        db: Database session.
        current_user: Authenticated admin user.

    Returns:
        Paginated session list with agent name, release version, and task count.
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    service = SessionService(db)
    sessions, total = service.list_sessions_for_operations(
        agent_id=agent_id,
        status=status,
        session_type=session_type,
        page=page,
        page_size=page_size,
    )

    # Batch-resolve enrichment fields
    agent_ids = list({s.agent_id for s in sessions})
    release_ids = list({s.release_id for s in sessions if s.release_id is not None})
    session_ids = [s.session_id for s in sessions]

    agent_names = _resolve_agent_names(db, agent_ids)
    release_versions = _resolve_release_versions(db, release_ids)
    task_counts = _resolve_task_counts(db, session_ids)

    items = []
    for session in sessions:
        items.append(
            {
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "agent_name": agent_names.get(session.agent_id, "Unknown"),
                "release_id": session.release_id,
                "release_version": (
                    release_versions.get(session.release_id)
                    if session.release_id is not None
                    else None
                ),
                "type": session.type,
                "user": session.user,
                "status": session.status,
                "title": session.title,
                "task_count": task_counts.get(session.session_id, 0),
                "created_at": session.created_at.replace(tzinfo=UTC).isoformat(),
                "updated_at": session.updated_at.replace(tzinfo=UTC).isoformat(),
            }
        )

    return {
        "sessions": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/operations/sessions/{session_id}")
async def get_operations_session_detail(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single session with its full conversation history for Operations.

    Unlike the user-scoped endpoint, this does not check session.user ownership.

    Args:
        session_id: UUID of the session to inspect.
        db: Database session.
        current_user: Authenticated admin user.

    Returns:
        Session metadata and full task/recursion conversation history.
    """
    service = SessionService(db)
    session = service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Resolve agent name and release version
    agent_name = "Unknown"
    agent = db.get(Agent, session.agent_id)
    if agent is not None:
        agent_name = agent.name

    release_version: int | None = None
    if session.release_id is not None:
        release = db.get(AgentRelease, session.release_id)
        if release is not None:
            release_version = release.version

    # Reuse the existing full-history serialization
    tasks_data = service.get_full_session_history(session_id)
    tasks = []
    for task_data in tasks_data:
        recursions = [
            RecursionDetail(
                iteration=r["iteration"],
                trace_id=r["trace_id"],
                observe=r["observe"],
                thinking=r["thinking"],
                reason=r["reason"],
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

    return {
        "session": {
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "agent_name": agent_name,
            "release_version": release_version,
            "type": session.type,
            "user": session.user,
            "status": session.status,
            "title": session.title,
            "created_at": session.created_at.replace(tzinfo=UTC).isoformat(),
            "updated_at": session.updated_at.replace(tzinfo=UTC).isoformat(),
        },
        "tasks": [t.model_dump() for t in tasks],
    }
