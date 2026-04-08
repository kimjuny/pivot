"""API endpoints for live session workspace files."""

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.schemas.workspace_file import WorkspaceFileResponse, WorkspaceFileUpdateRequest
from app.services.workspace_file_service import WorkspaceFileService
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session as DBSession

router = APIRouter()


@router.get(
    "/sessions/{session_id}/workspace-file",
    response_model=WorkspaceFileResponse,
)
async def get_workspace_file(
    session_id: str,
    path: str = Query(..., description="Workspace-relative file path."),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceFileResponse:
    """Read one live UTF-8 workspace file for the current session owner."""
    service = WorkspaceFileService(db)
    try:
        file = service.read_text_file_for_user(
            session_id=session_id,
            username=current_user.username,
            workspace_relative_path=path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.to_response(file)


@router.put(
    "/sessions/{session_id}/workspace-file",
    response_model=WorkspaceFileResponse,
)
async def update_workspace_file(
    session_id: str,
    request: WorkspaceFileUpdateRequest,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WorkspaceFileResponse:
    """Write one live UTF-8 workspace file for the current session owner."""
    service = WorkspaceFileService(db)
    try:
        file = service.write_text_file_for_user(
            session_id=session_id,
            username=current_user.username,
            workspace_relative_path=request.workspace_relative_path,
            content=request.content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.to_response(file)
