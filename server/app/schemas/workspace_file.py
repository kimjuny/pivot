"""Schemas for live workspace file read/write APIs."""

from app.schemas.base import AppBaseModel
from pydantic import Field


class WorkspaceFileResponse(AppBaseModel):
    """One live workspace text file returned by the API."""

    session_id: str = Field(..., description="Owning session UUID.")
    workspace_relative_path: str = Field(
        ...,
        description="Path relative to the session or project workspace root.",
    )
    content: str = Field(..., description="Current UTF-8 file content.")


class WorkspaceFileUpdateRequest(AppBaseModel):
    """Mutable payload used to update one live workspace text file."""

    workspace_relative_path: str = Field(
        ...,
        description="Path relative to the session or project workspace root.",
    )
    content: str = Field(..., description="Next UTF-8 file content.")
