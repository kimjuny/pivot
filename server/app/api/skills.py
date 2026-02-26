"""API endpoints for markdown skill management.

Skill sources are stored as `.md` files and metadata is extracted from top
front matter (`--- ... ---`) with fields like `name` and `description`.
"""

from typing import Any, Literal

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.services.skill_service import (
    delete_user_skill,
    list_builtin_skills,
    list_user_skills,
    read_shared_skill,
    read_user_skill,
    upsert_user_skill,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

router = APIRouter()


class SkillWriteRequest(BaseModel):
    """Request payload for writing a markdown skill source file."""

    source: str


@router.get("/skills/shared")
async def get_shared_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List shared skills (builtin + user-shared)."""
    builtin = list_builtin_skills()
    user_shared = list_user_skills(current_user.username, "shared")
    return [*builtin, *user_shared]


@router.get("/skills/private")
async def get_private_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List private skills for current user."""
    return list_user_skills(current_user.username, "private")


@router.get("/skills/shared/{skill_name}")
async def get_shared_skill_source(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read shared skill source (user-shared takes precedence over builtin)."""
    try:
        return read_shared_skill(current_user.username, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/skills/{kind}/{skill_name}")
async def get_user_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read a user-owned skill source from private/shared namespace."""
    try:
        return read_user_skill(current_user.username, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/skills/{kind}/{skill_name}")
async def upsert_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    body: SkillWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create or update a user-owned markdown skill."""
    try:
        metadata = upsert_user_skill(current_user.username, kind, skill_name, body.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "name": skill_name,
        "kind": kind,
        "status": "ok",
        "metadata": metadata,
    }


@router.delete("/skills/{kind}/{skill_name}")
async def delete_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a user-owned markdown skill."""
    try:
        delete_user_skill(current_user.username, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"name": skill_name, "kind": kind, "status": "deleted"}
