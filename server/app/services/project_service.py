"""Service layer for shared project workspaces."""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import UTC, datetime

from app.models.project import Project
from app.services.sandbox_service import get_sandbox_service
from app.services.workspace_service import WorkspaceService
from app.services.workspace_storage_service import WorkspaceStorageService
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

    def get_owned_project(self, project_id: str, username: str) -> Project | None:
        """Return one project only when it belongs to the given user."""
        statement = select(Project).where(
            Project.project_id == project_id,
            Project.user == username,
        )
        return self.db.exec(statement).first()

    def list_projects(self, *, username: str, agent_id: int) -> list[Project]:
        """List projects for one user-agent pair."""
        statement = (
            select(Project)
            .where(Project.user == username, Project.agent_id == agent_id)
            .order_by(col(Project.updated_at).desc(), col(Project.created_at).desc())
        )
        return list(self.db.exec(statement).all())

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
        return project

    def update_project(
        self,
        project_id: str,
        *,
        username: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Project | None:
        """Update project metadata for one owned project."""
        project = self.get_owned_project(project_id, username)
        if project is None:
            return None

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

    def delete_project(self, project_id: str, *, username: str) -> bool:
        """Delete a project, its child sessions, and its shared workspace."""
        project = self.get_owned_project(project_id, username)
        if project is None:
            return False

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
                    mount_spec=WorkspaceStorageService().build_mount_spec(workspace),
                )

        WorkspaceService(self.db).delete_workspace(project.workspace_id)
        self.db.delete(project)
        self.db.commit()
        return True
