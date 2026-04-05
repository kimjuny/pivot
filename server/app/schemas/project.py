"""Schemas for project CRUD APIs."""

from app.schemas.base import AppBaseModel
from pydantic import Field


class ProjectCreate(AppBaseModel):
    """Request schema for creating a project."""

    agent_id: int = Field(..., description="Agent ID that owns the project")
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(AppBaseModel):
    """Request schema for updating a project."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectResponse(AppBaseModel):
    """Response schema for one project."""

    id: int
    project_id: str
    agent_id: int
    name: str
    description: str | None = None
    workspace_id: str
    created_at: str
    updated_at: str


class ProjectListResponse(AppBaseModel):
    """Response schema for project listings."""

    projects: list[ProjectResponse]
    total: int
