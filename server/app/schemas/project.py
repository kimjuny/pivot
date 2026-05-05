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
    can_edit: bool
    created_at: str
    updated_at: str


class ProjectListResponse(AppBaseModel):
    """Response schema for project listings."""

    projects: list[ProjectResponse]
    total: int


class ProjectAccessUpdate(AppBaseModel):
    """Payload for replacing one project's selected access."""

    use_user_ids: list[int] = Field(default_factory=list)
    use_group_ids: list[int] = Field(default_factory=list)
    edit_user_ids: list[int] = Field(default_factory=list)
    edit_group_ids: list[int] = Field(default_factory=list)


class ProjectAccessResponse(AppBaseModel):
    """Direct use/edit grants for one project."""

    project_id: str
    use_user_ids: list[int] = Field(default_factory=list)
    use_group_ids: list[int] = Field(default_factory=list)
    edit_user_ids: list[int] = Field(default_factory=list)
    edit_group_ids: list[int] = Field(default_factory=list)


class ProjectAccessUserOption(AppBaseModel):
    """User option shown in one project's access editor."""

    id: int
    username: str
    display_name: str | None
    email: str | None


class ProjectAccessGroupOption(AppBaseModel):
    """Group option shown in one project's access editor."""

    id: int
    name: str
    description: str
    member_count: int


class ProjectAccessOptionsResponse(AppBaseModel):
    """Assignable principals for one project's access editor."""

    users: list[ProjectAccessUserOption] = Field(default_factory=list)
    groups: list[ProjectAccessGroupOption] = Field(default_factory=list)
