"""User model for authentication.

This module defines the User model for storing user credentials
and authentication information.
"""

from datetime import datetime, timezone

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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    access_token: str
    token_type: str = "bearer"
