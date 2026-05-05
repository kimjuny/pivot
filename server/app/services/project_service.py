"""Service layer for shared project workspaces."""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import UTC, datetime

from app.models.access import AccessLevel, PrincipalType, ResourceType
from app.models.project import Project
from app.models.user import User
from app.services.access_service import AccessService
from app.services.sandbox_service import get_sandbox_service
from app.services.workspace_service import WorkspaceService
from sqlmodel import Session as DBSession, col, select


class ProjectService:
    """CRUD operations for user-owned projects."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Active database session.
        """
        self.db = db

    def get_project(self, project_id: str) -> Project | None:
        """Return one project by public identifier."""
        statement = select(Project).where(Project.project_id == project_id)
        return self.db.exec(statement).first()

    def _owner_user_id(self, project: Project) -> int | None:
        """Return the owning user's id for one project."""
        owner = self.db.exec(select(User).where(User.username == project.user)).first()
        return owner.id if owner is not None else None

    def has_project_access(
        self,
        *,
        user: User,
        project: Project,
        access_level: AccessLevel,
    ) -> bool:
        """Return whether a user can use or edit one project."""
        return AccessService(self.db).has_resource_access(
            user=user,
            resource_type=ResourceType.PROJECT,
            resource_id=project.project_id,
            access_level=access_level,
            creator_user_id=self._owner_user_id(project),
        )

    def require_project_access(
        self,
        *,
        user: User,
        project: Project,
        access_level: AccessLevel,
    ) -> None:
        """Raise unless a user can use or edit one project."""
        AccessService(self.db).require_resource_access(
            user=user,
            resource_type=ResourceType.PROJECT,
            resource_id=project.project_id,
            access_level=access_level,
            creator_user_id=self._owner_user_id(project),
        )

    def list_projects(self, *, user: User, agent_id: int) -> list[Project]:
        """List projects the user can use for one agent."""
        statement = (
            select(Project)
            .where(Project.agent_id == agent_id)
            .order_by(col(Project.updated_at).desc(), col(Project.created_at).desc())
        )
        return [
            project
            for project in self.db.exec(statement).all()
            if self.has_project_access(
                user=user,
                project=project,
                access_level=AccessLevel.USE,
            )
        ]

    def create_project(
        self,
        *,
        agent_id: int,
        username: str,
        name: str,
        description: str | None = None,
    ) -> Project:
        """Create a project and its shared workspace.

        Args:
            agent_id: Owning agent identifier.
            username: Owner username.
            name: Project display name.
            description: Optional project note.

        Returns:
            Persisted project row.
        """
        trimmed_name = name.strip()
        if not trimmed_name:
            raise ValueError("Project name cannot be empty.")

        now = datetime.now(UTC)
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=agent_id,
            username=username,
            scope="project_shared",
            project_id=str(uuid.uuid4()),
        )
        project = Project(
            project_id=workspace.project_id or str(uuid.uuid4()),
            agent_id=agent_id,
            user=username,
            name=trimmed_name,
            description=description.strip() if description else None,
            workspace_id=workspace.workspace_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        owner = self.db.exec(select(User).where(User.username == username)).first()
        if owner is not None and owner.id is not None:
            access_service = AccessService(self.db)
            for resource_type, resource_id in (
                (ResourceType.PROJECT, project.project_id),
                (ResourceType.WORKSPACE, project.workspace_id),
            ):
                for access_level in (AccessLevel.USE, AccessLevel.EDIT):
                    access_service.grant_access(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        principal_type=PrincipalType.USER,
                        principal_id=owner.id,
                        access_level=access_level,
                    )
        return project

    def update_project(
        self,
        project_id: str,
        *,
        user: User,
        name: str | None = None,
        description: str | None = None,
    ) -> Project | None:
        """Update project metadata for one editable project."""
        project = self.get_project(project_id)
        if project is None:
            return None
        self.require_project_access(
            user=user,
            project=project,
            access_level=AccessLevel.EDIT,
        )

        has_changes = False
        if name is not None:
            trimmed_name = name.strip()
            if not trimmed_name:
                raise ValueError("Project name cannot be empty.")
            if project.name != trimmed_name:
                project.name = trimmed_name
                has_changes = True

        if description is not None:
            next_description = description.strip() or None
            if project.description != next_description:
                project.description = next_description
                has_changes = True

        if has_changes:
            project.updated_at = datetime.now(UTC)
            self.db.add(project)
            self.db.commit()
            self.db.refresh(project)
        return project

    def set_project_access(
        self,
        *,
        project: Project,
        use_user_ids: set[int],
        use_group_ids: set[int],
        edit_user_ids: set[int],
        edit_group_ids: set[int],
    ) -> None:
        """Replace selected project access and mirror it to its workspace."""
        owner_id = self._owner_user_id(project)
        if owner_id is not None:
            use_user_ids = set(use_user_ids)
            edit_user_ids = set(edit_user_ids)
            use_user_ids.add(owner_id)
            edit_user_ids.add(owner_id)

        access_service = AccessService(self.db)
        for resource_type, resource_id in (
            (ResourceType.PROJECT, project.project_id),
            (ResourceType.WORKSPACE, project.workspace_id),
        ):
            access_service._replace_resource_grants_in_session(
                resource_type=resource_type,
                resource_id=resource_id,
                access_level=AccessLevel.USE,
                user_ids=use_user_ids,
                group_ids=use_group_ids,
            )
            access_service._replace_resource_grants_in_session(
                resource_type=resource_type,
                resource_id=resource_id,
                access_level=AccessLevel.EDIT,
                user_ids=edit_user_ids,
                group_ids=edit_group_ids,
            )
        project.updated_at = datetime.now(UTC)
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

    def delete_project(self, project_id: str, *, user: User) -> bool:
        """Delete a project, its child sessions, and its shared workspace."""
        project = self.get_project(project_id)
        if project is None:
            return False
        self.require_project_access(
            user=user,
            project=project,
            access_level=AccessLevel.EDIT,
        )

        from app.models.session import Session
        from app.services.session_service import SessionService

        sessions = list(
            self.db.exec(
                select(Session).where(Session.project_id == project.project_id)
            ).all()
        )
        session_service = SessionService(self.db)
        for session in sessions:
            session_service.delete_session(
                session.session_id,
                delete_workspace=False,
            )

        workspace_service = WorkspaceService(self.db)
        workspace = workspace_service.get_workspace(project.workspace_id)
        if workspace is not None:
            with suppress(RuntimeError):
                get_sandbox_service().destroy(
                    username=workspace.user,
                    workspace_id=workspace.workspace_id,
                    workspace_backend_path=workspace_service.get_workspace_backend_path(
                        workspace
                    ),
                )

        WorkspaceService(self.db).delete_workspace(project.workspace_id)
        access_service = AccessService(self.db)
        access_service._delete_resource_grants_in_session(
            resource_type=ResourceType.PROJECT,
            resource_id=project.project_id,
        )
        access_service._delete_resource_grants_in_session(
            resource_type=ResourceType.WORKSPACE,
            resource_id=project.workspace_id,
        )
        self.db.delete(project)
        self.db.commit()
        return True
