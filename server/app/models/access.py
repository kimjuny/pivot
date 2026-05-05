"""Access-control models for roles, permissions, groups, and resources."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class AccessLevel(StrEnum):
    """Resource access levels supported by Pivot."""

    USE = "use"
    EDIT = "edit"


class PrincipalType(StrEnum):
    """Principal kinds that can receive resource access."""

    USER = "user"
    GROUP = "group"


class ResourceType(StrEnum):
    """Resource types supported by the generic access table."""

    AGENT = "agent"
    PROJECT = "project"
    WORKSPACE = "workspace"
    SKILL = "skill"
    TOOL = "tool"
    EXTENSION = "extension"
    CHANNEL_BINDING = "channel_binding"
    LLM = "llm"
    MEDIA_GENERATION_PROVIDER = "media_generation_provider"
    WEB_SEARCH_PROVIDER = "web_search_provider"


class UserRole(SQLModel, table=True):
    """A named set of system permissions."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=500)
    is_system: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


Role = UserRole


class PermissionRecord(SQLModel, table=True):
    """One backend-recognized system permission."""

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True, max_length=120)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=500)
    category: str = Field(default="General", index=True, max_length=80)
    is_system: bool = Field(default=True, index=True)


class RolePermission(SQLModel, table=True):
    """Many-to-many link between a role and a permission."""

    role_id: int = Field(foreign_key="userrole.id", primary_key=True)
    permission_id: int = Field(foreign_key="permissionrecord.id", primary_key=True)


class UserGroup(SQLModel, table=True):
    """A lightweight batch-authorization group."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=120)
    description: str = Field(default="", max_length=500)
    created_by_user_id: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GroupMember(SQLModel, table=True):
    """Membership link between a group and a user."""

    group_id: int = Field(foreign_key="usergroup.id", primary_key=True)
    user_id: int = Field(foreign_key="user.id", primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResourceAccess(SQLModel, table=True):
    """Generic use/edit grant for one user or group on one resource."""

    __table_args__ = (
        UniqueConstraint(
            "resource_type",
            "resource_id",
            "principal_type",
            "principal_id",
            "access_level",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    resource_type: ResourceType = Field(index=True)
    resource_id: str = Field(index=True, max_length=255)
    principal_type: PrincipalType = Field(index=True)
    principal_id: str = Field(index=True, max_length=255)
    access_level: AccessLevel = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
