"""Service helpers for live workspace file access scoped to one session."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.session import Session as SessionModel
from app.schemas.workspace_file import WorkspaceFileResponse
from app.services.workspace_runtime_file_service import WorkspaceRuntimeFileService
from app.services.workspace_service import WorkspaceService
from app.services.workspace_storage_service import WorkspaceStorageService
from sqlmodel import Session as DBSession, select


@dataclass(frozen=True, slots=True)
class WorkspaceTextFile:
    """One live text file addressable through a session workspace."""

    session_id: str
    workspace_relative_path: str
    content: str


class WorkspaceFileService:
    """Read and write live workspace files through session-owned runtimes."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with one database session."""
        self.db = db

    def read_text_file_for_user(
        self,
        *,
        session_id: str,
        username: str,
        workspace_relative_path: str,
    ) -> WorkspaceTextFile:
        """Return one live UTF-8 workspace file for the owning user."""
        session_row, mount_spec = self._resolve_session_mount_spec(
            session_id=session_id,
            username=username,
        )
        content = WorkspaceRuntimeFileService().read_text_file(
            username=username,
            mount_spec=mount_spec,
            workspace_relative_path=workspace_relative_path,
        )
        return WorkspaceTextFile(
            session_id=session_row.session_id,
            workspace_relative_path=workspace_relative_path,
            content=content,
        )

    def write_text_file_for_user(
        self,
        *,
        session_id: str,
        username: str,
        workspace_relative_path: str,
        content: str,
    ) -> WorkspaceTextFile:
        """Persist one UTF-8 workspace file back into the live runtime."""
        session_row, mount_spec = self._resolve_session_mount_spec(
            session_id=session_id,
            username=username,
        )
        WorkspaceRuntimeFileService().write_text_file(
            username=username,
            mount_spec=mount_spec,
            workspace_relative_path=workspace_relative_path,
            content=content,
        )
        return WorkspaceTextFile(
            session_id=session_row.session_id,
            workspace_relative_path=workspace_relative_path,
            content=content,
        )

    @staticmethod
    def to_response(file: WorkspaceTextFile) -> WorkspaceFileResponse:
        """Serialize one live workspace file payload for the API layer."""
        return WorkspaceFileResponse(
            session_id=file.session_id,
            workspace_relative_path=file.workspace_relative_path,
            content=file.content,
        )

    def _resolve_session_mount_spec(
        self,
        *,
        session_id: str,
        username: str,
    ):
        """Resolve one owned session into its runtime mount specification."""
        session_row = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == session_id)
        ).first()
        if session_row is None or session_row.user != username:
            raise ValueError("Session not found.")
        if session_row.workspace_id is None:
            raise ValueError("Session does not have an active workspace.")

        workspace = WorkspaceService(self.db).get_workspace(session_row.workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found.")

        return session_row, WorkspaceStorageService().build_mount_spec(workspace)
