"""API endpoints for markdown skill management."""

from typing import Any, Literal

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.services.skill_service import (
    delete_user_skill,
    install_github_skill,
    list_private_skills,
    list_shared_skills,
    probe_github_skill_import,
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


class GitHubSkillProbeRequest(BaseModel):
    """Request payload for probing a GitHub repository for skills."""

    github_url: str
    ref: str | None = None


class GitHubSkillImportRequest(BaseModel):
    """Request payload for installing one skill from GitHub."""

    github_url: str
    ref: str
    ref_type: Literal["branch", "tag"]
    kind: Literal["private", "shared"]
    remote_directory_name: str
    skill_name: str


@router.get("/skills/shared")
async def get_shared_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List shared skills visible to the current user."""
    return list_shared_skills(db, current_user.username)


@router.get("/skills/private")
async def get_private_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List private skills for current user."""
    return list_private_skills(db, current_user.username)


@router.get("/skills/shared/{skill_name}")
async def get_shared_skill_source(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read one shared skill source visible to the current user."""
    try:
        return read_shared_skill(db, current_user.username, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        return read_user_skill(db, current_user.username, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
        metadata = upsert_user_skill(db, current_user, kind, skill_name, body.source)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "name": skill_name,
        "kind": kind,
        "status": "ok",
        "metadata": metadata,
    }


@router.post("/skills/import/github/probe")
async def probe_github_skill(
    body: GitHubSkillProbeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Probe a public GitHub repository for importable skills."""
    try:
        return probe_github_skill_import(
            db,
            current_user,
            body.github_url,
            ref=body.ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/import/github")
async def import_github_skill(
    body: GitHubSkillImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Install one skill folder from a public GitHub repository."""
    try:
        metadata = install_github_skill(
            db,
            current_user,
            github_url=body.github_url,
            ref=body.ref,
            ref_type=body.ref_type,
            kind=body.kind,
            remote_directory_name=body.remote_directory_name,
            skill_name=body.skill_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "imported", "metadata": metadata}


@router.delete("/skills/{kind}/{skill_name}")
async def delete_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a user-owned markdown skill."""
    try:
        delete_user_skill(db, current_user, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"name": skill_name, "kind": kind, "status": "deleted"}
