"""Workspace file search API for the `@` file-mention feature."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.agent import Agent
from app.services.sandbox_service import get_sandbox_service
from app.services.session_service import SessionService
from app.services.skill_service import list_allowed_visible_skills
from app.services.workspace_service import WorkspaceService
from fastapi import APIRouter, Depends, HTTPException, Query

if TYPE_CHECKING:
    from app.models.session import Session as SessionModel
    from app.models.user import User
    from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)

router = APIRouter()

# Directories excluded from file search to reduce noise.
_EXCLUDE_PATHS = (
    "-not",
    "-path",
    "*/.git/*",
    "-not",
    "-path",
    "*/node_modules/*",
    "-not",
    "-path",
    "*/__pycache__/*",
    "-not",
    "-path",
    "*/.venv/*",
    "-not",
    "-path",
    "*/skills/*",
)


def _get_owned_session(
    *,
    db: DBSession,
    session_id: str,
    user_id: int,
) -> SessionModel:
    """Return a session owned by the current user or raise 404/403."""
    session = SessionService(db).get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return session


@router.get("/sessions/{session_id}/workspace/search")
def search_workspace_files(
    session_id: str,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Search files in the session's workspace sandbox via ripgrep."""
    user_id = current_user.id
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid user")

    session = _get_owned_session(db=db, session_id=session_id, user_id=user_id)

    if session.workspace_id is None:
        return {"files": []}

    workspace = WorkspaceService(db).get_workspace(session.workspace_id)
    if workspace is None:
        return {"files": []}

    backend_path = WorkspaceService(db).get_workspace_backend_path(workspace)

    # Resolve agent skills for sandbox mount.
    agent = db.get(Agent, session.agent_id)
    skill_mounts = _resolve_skill_mounts(db, user_id, agent) if agent else []

    sandbox = get_sandbox_service()

    try:
        sandbox.create(
            user_id=user_id,
            workspace_id=workspace.workspace_id,
            workspace_backend_path=backend_path,
            skills=skill_mounts,
        )
    except RuntimeError:
        logger.warning(
            "Failed to ensure sandbox for workspace search (session=%s)",
            session_id,
        )
        return {"files": []}

    keyword = q.strip()

    if keyword:
        cmd = [
            "find",
            "/workspace",
            "-iname",
            f"*{keyword}*",
            *_EXCLUDE_PATHS,
            "-type",
            "f",
        ]
    else:
        cmd = [
            "find",
            "/workspace",
            "-maxdepth",
            "2",
            *_EXCLUDE_PATHS,
            "-type",
            "f",
        ]

    cmd.extend(["2>/dev/null"])

    try:
        result = sandbox.exec(
            user_id=user_id,
            workspace_id=workspace.workspace_id,
            workspace_backend_path=backend_path,
            cmd=["sh", "-c", " ".join(cmd) + f" | head -{limit}"],
            skills=skill_mounts,
        )
    except RuntimeError:
        logger.warning("Failed to exec file search in sandbox (session=%s)", session_id)
        return {"files": []}

    if result.exit_code != 0:
        return {"files": []}

    files = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or not line.startswith("/workspace/"):
            continue
        relative = line.removeprefix("/workspace/")
        if not relative:
            continue
        files.append({"path": relative, "name": PurePosixPath(relative).name})
        if len(files) >= limit:
            break

    return {"files": files}


def _resolve_skill_mounts(
    db: DBSession, user_id: int, agent: Agent
) -> list[dict[str, str]]:
    """Return the skill mount list for sandbox creation."""
    allowed = list_allowed_visible_skills(
        db,
        user_id,
        raw_skill_ids=agent.skill_ids,
    )
    return [{"name": skill["name"], "location": skill["location"]} for skill in allowed]
