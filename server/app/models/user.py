"""User model for authentication.

This module defines the User model for storing user credentials
and authentication information.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    """User model for authentication.

    Attributes:
        id: Primary key of the user.
        username: Unique username for login.
        password_hash: Hashed password for authentication.
        created_at: UTC timestamp when the user was created.
        updated_at: UTC timestamp when the user was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=50)
    password_hash: str = Field(max_length=255)
    role_id: int = Field(foreign_key="userrole.id", index=True)
    status: str = Field(default="active", index=True, max_length=32)
    email: str | None = Field(default=None, index=True, unique=True, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserLogin(SQLModel):
    """Schema for user login request.

    Attributes:
        username: Username for authentication.
        password: Plain text password for authentication.
    """

    username: str
    password: str


class UserResponse(SQLModel):
    """Schema for user response.

    Attributes:
        id: User ID.
        username: Username.
        access_token: JWT access token.
        token_type: Type of token (e.g., "bearer").
    """

    id: int
    username: str
    role: str
    permissions: list[str]
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(SQLModel):
    """Schema for the current authenticated user."""

    id: int
    username: str
    role: str
    permissions: list[str]


class SetupRequest(SQLModel):
    """Schema for the initial admin setup request."""

    username: str
    password: str
    email: str | None = None
    time_zone: str | None = None
    language: str | None = None


class SetupStatusResponse(SQLModel):
    """Schema for the setup status check response."""

    needs_setup: bool


class ChangePasswordRequest(SQLModel):
    """Schema for an authenticated user changing their own password."""

    current_password: str
    new_password: str
