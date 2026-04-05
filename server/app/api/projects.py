"""API endpoints for project-backed shared workspaces."""

from datetime import UTC

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project_service import ProjectService
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session as DBSession

router = APIRouter()


def _build_project_response(project: Project) -> ProjectResponse:
    """Serialize one project row into the public API response."""
    return ProjectResponse(
        id=project.id or 0,
        project_id=project.project_id,
        agent_id=project.agent_id,
        name=project.name,
        description=project.description,
        workspace_id=project.workspace_id,
        created_at=project.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=project.updated_at.replace(tzinfo=UTC).isoformat(),
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    agent_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectListResponse:
    """List projects for the current user and one agent."""
    projects = ProjectService(db).list_projects(
        username=current_user.username,
        agent_id=agent_id,
    )
    responses = [_build_project_response(project) for project in projects]
    return ProjectListResponse(projects=responses, total=len(responses))


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    request: ProjectCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """Create one project plus its shared workspace."""
    try:
        project = ProjectService(db).create_project(
            agent_id=request.agent_id,
            username=current_user.username,
            name=request.name,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_project_response(project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: ProjectUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    """Update one owned project's metadata."""
    try:
        project = ProjectService(db).update_project(
            project_id,
            username=current_user.username,
            name=request.name if "name" in request.model_fields_set else None,
            description=(
                request.description
                if "description" in request.model_fields_set
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _build_project_response(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Hard-delete one owned project and all of its sessions."""
    if not ProjectService(db).delete_project(
        project_id, username=current_user.username
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)
