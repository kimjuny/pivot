"""Tool models for user-created tools.

This module defines models and schemas for managing user-created tools,
including database models for metadata tracking and request/response schemas.
"""

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Field, SQLModel


class UserTool(SQLModel, table=True):
    """User-created tool stored in database for metadata tracking.

    The actual tool source code is stored in the filesystem under
    server/workspace/{username}/tools/{tool_name}.py

    Attributes:
        id: Primary key.
        name: Unique tool name (also used as filename).
        description: Tool description for LLM consumption.
        owner_id: ID of the user who created this tool.
        created_at: UTC timestamp when tool was created.
        updated_at: UTC timestamp when tool was last modified.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=100)
    description: str = Field(default="")
    owner_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCreate(SQLModel):
    """Schema for creating a new tool.

    Only source_code is required. The name and description are
    automatically extracted from the @tool decorator in the source code.

    Attributes:
        source_code: Python source code containing @tool decorated function.
    """

    source_code: str


class ToolUpdate(SQLModel):
    """Schema for updating an existing tool.

    Only source_code is required. The description is automatically
    extracted from the @tool decorator in the source code.

    Attributes:
        source_code: Updated Python source code.
    """

    source_code: str | None = None


class ToolResponse(SQLModel):
    """Schema for tool API responses.

    Attributes:
        name: Tool name.
        description: Tool description.
        parameters: JSON Schema of tool parameters.
        tool_type: "shared" or "private".
        owner_id: Owner user ID (None for shared tools).
        owner_username: Owner username (None for shared tools).
        can_edit: Whether current user can edit this tool.
        can_delete: Whether current user can delete this tool.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    tool_type: str  # "shared" | "private"
    owner_id: int | None
    owner_username: str | None
    can_edit: bool
    can_delete: bool


class ToolSourceResponse(SQLModel):
    """Schema for tool source code response.

    Attributes:
        name: Tool name.
        source_code: Full Python source code.
        tool_type: "shared" or "private".
    """

    name: str
    source_code: str
    tool_type: str
