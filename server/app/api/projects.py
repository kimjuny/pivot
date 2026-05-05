"""API endpoints for project-backed shared workspaces."""

from datetime import UTC

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel, PrincipalType, ResourceAccess, ResourceType
from app.models.project import Project
from app.models.user import User
from app.schemas.project import (
    ProjectAccessGroupOption,
    ProjectAccessOptionsResponse,
    ProjectAccessResponse,
    ProjectAccessUpdate,
    ProjectAccessUserOption,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.group_service import GroupService
from app.services.project_service import ProjectService
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session as DBSession

router = APIRouter()


def _require_agent_use_access(
    db: DBSession,
    user: User,
    agent_id: int,
) -> None:
    try:
        agent = AgentService(db).get_required_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    AccessService(db).require_agent_access(
        user=user,
        agent=agent,
        access_level=AccessLevel.USE,
    )


def _build_project_response(
    db: DBSession,
    project: Project,
    user: User,
) -> ProjectResponse:
    """Serialize one project row into the public API response."""
    return ProjectResponse(
        id=project.id or 0,
        project_id=project.project_id,
        agent_id=project.agent_id,
        name=project.name,
        description=project.description,
        workspace_id=project.workspace_id,
        can_edit=ProjectService(db).has_project_access(
            user=user,
            project=project,
            access_level=AccessLevel.EDIT,
        ),
        created_at=project.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=project.updated_at.replace(tzinfo=UTC).isoformat(),
    )


def _grant_principal_ids(
    grants: list[ResourceAccess],
    principal_type: PrincipalType,
) -> list[int]:
    principal_ids: list[int] = []
    for grant in grants:
        if grant.principal_type == principal_type:
            principal_ids.append(int(grant.principal_id))
    return sorted(principal_ids)


def _serialize_project_access(
    project_id: str,
    grants: list[ResourceAccess],
) -> ProjectAccessResponse:
    use_grants = [grant for grant in grants if grant.access_level == AccessLevel.USE]
    edit_grants = [grant for grant in grants if grant.access_level == AccessLevel.EDIT]
    return ProjectAccessResponse(
        project_id=project_id,
        use_user_ids=_grant_principal_ids(use_grants, PrincipalType.USER),
        use_group_ids=_grant_principal_ids(use_grants, PrincipalType.GROUP),
        edit_user_ids=_grant_principal_ids(edit_grants, PrincipalType.USER),
        edit_group_ids=_grant_principal_ids(edit_grants, PrincipalType.GROUP),
    )


def _serialize_project_access_options(
    db: DBSession,
    users: list[User],
) -> ProjectAccessOptionsResponse:
    group_service = GroupService(db)
    member_counts = group_service.get_member_count_by_group_id()
    return ProjectAccessOptionsResponse(
        users=[
            ProjectAccessUserOption(
                id=user.id or 0,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
            )
            for user in users
            if user.id is not None and user.status == "active"
        ],
        groups=[
            ProjectAccessGroupOption(
                id=group.id or 0,
                name=group.name,
                description=group.description,
                member_count=member_counts.get(group.id or 0, 0),
            )
            for group in group_service.list_groups()
            if group.id is not None
        ],
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    agent_id: int,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectListResponse:
    """List projects for the current user and one agent."""
    _require_agent_use_access(db, current_user, agent_id)
    projects = ProjectService(db).list_projects(
        user=current_user,
        agent_id=agent_id,
    )
    responses = [
        _build_project_response(db, project, current_user) for project in projects
    ]
    return ProjectListResponse(projects=responses, total=len(responses))


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    request: ProjectCreate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectResponse:
    """Create one project plus its shared workspace."""
    _require_agent_use_access(db, current_user, request.agent_id)
    try:
        project = ProjectService(db).create_project(
            agent_id=request.agent_id,
            username=current_user.username,
            name=request.name,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_project_response(db, project, current_user)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    request: ProjectUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectResponse:
    """Update one editable project's metadata."""
    service = ProjectService(db)
    existing_project = service.get_project(project_id)
    if existing_project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_agent_use_access(db, current_user, existing_project.agent_id)
    try:
        project = service.update_project(
            project_id,
            user=current_user,
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
    return _build_project_response(db, project, current_user)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> Response:
    """Hard-delete one editable project and all of its sessions."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_agent_use_access(db, current_user, project.agent_id)
    if not service.delete_project(project_id, user=current_user):
        raise HTTPException(status_code=404, detail="Project not found")
    return Response(status_code=204)


@router.get(
    "/projects/{project_id}/access-options",
    response_model=ProjectAccessOptionsResponse,
)
async def get_project_access_options(
    project_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectAccessOptionsResponse:
    """Return selectable principals for one project access editor."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_agent_use_access(db, current_user, project.agent_id)
    service.require_project_access(
        user=current_user,
        project=project,
        access_level=AccessLevel.EDIT,
    )
    return _serialize_project_access_options(db, UserService(db).list_users())


@router.get("/projects/{project_id}/access", response_model=ProjectAccessResponse)
async def get_project_access(
    project_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectAccessResponse:
    """Return direct use/edit grants for one project."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_agent_use_access(db, current_user, project.agent_id)
    service.require_project_access(
        user=current_user,
        project=project,
        access_level=AccessLevel.EDIT,
    )
    return _serialize_project_access(
        project_id=project_id,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.PROJECT,
            resource_id=project_id,
        ),
    )


@router.put("/projects/{project_id}/access", response_model=ProjectAccessResponse)
async def update_project_access(
    project_id: str,
    payload: ProjectAccessUpdate,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ProjectAccessResponse:
    """Replace direct use/edit grants for one project."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_agent_use_access(db, current_user, project.agent_id)
    service.require_project_access(
        user=current_user,
        project=project,
        access_level=AccessLevel.EDIT,
    )
    service.set_project_access(
        project=project,
        use_user_ids=set(payload.use_user_ids),
        use_group_ids=set(payload.use_group_ids),
        edit_user_ids=set(payload.edit_user_ids),
        edit_group_ids=set(payload.edit_group_ids),
    )
    return _serialize_project_access(
        project_id=project_id,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.PROJECT,
            resource_id=project_id,
        ),
    )
