"""Services for user administration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.api.auth import get_password_hash
from app.models.access import Role
from app.models.user import User
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


class UserService:
    """CRUD-style service for Pivot users."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def has_any_user(self) -> bool:
        """Check whether any user exists in the database."""
        return self.db.exec(select(User).limit(1)).first() is not None

    def list_users(self) -> list[User]:
        """List all users."""
        statement = select(User).order_by(col(User.created_at).desc())
        return list(self.db.exec(statement).all())

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role_id: int,
        email: str | None = None,
    ) -> User:
        """Create one user."""
        role = self.db.get(Role, role_id)
        if role is None:
            raise ValueError("Role not found")
        existing = self.db.exec(select(User).where(User.username == username)).first()
        if existing is not None:
            raise ValueError("Username already exists")
        if email:
            existing_email = self.db.exec(
                select(User).where(User.email == email)
            ).first()
            if existing_email is not None:
                raise ValueError("Email already exists")

        user = User(
            username=username,
            password_hash=get_password_hash(password),
            role_id=role_id,
            status="active",
            email=email,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user_role(self, *, user_id: int, role_id: int) -> User | None:
        """Assign one role to one user."""
        user = self.db.get(User, user_id)
        role = self.db.get(Role, role_id)
        if user is None or role is None:
            return None
        user.role_id = role_id
        user.updated_at = datetime.now(UTC)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_user(
        self,
        *,
        user_id: int,
        role_id: int | None = None,
        status: str | None = None,
        email: str | None = None,
    ) -> User | None:
        """Update administrative user fields."""
        user = self.db.get(User, user_id)
        if user is None:
            return None
        if role_id is not None:
            role = self.db.get(Role, role_id)
            if role is None:
                raise ValueError("Role not found")
            user.role_id = role_id
        if status is not None:
            if status not in {"active", "disabled"}:
                raise ValueError("Unsupported user status")
            user.status = status
        if email is not None:
            user.email = email.strip() or None
        user.updated_at = datetime.now(UTC)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update_password(self, *, user_id: int, new_password: str) -> User | None:
        """Hash and persist a new password for the given user.

        Args:
            user_id: Primary key of the user to update.
            new_password: Plain-text password to hash and store.

        Returns:
            The updated user, or None if the user does not exist.
        """
        user = self.db.get(User, user_id)
        if user is None:
            return None
        user.password_hash = get_password_hash(new_password)
        user.updated_at = datetime.now(UTC)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
