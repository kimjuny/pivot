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

    def ensure_default_admin(self) -> User:
        """Create or update the development default admin user."""
        admin_role = self.db.exec(select(Role).where(Role.key == "admin")).first()
        if admin_role is None or admin_role.id is None:
            raise RuntimeError("Default admin role has not been seeded.")

        user = self.db.exec(select(User).where(User.username == "default")).first()
        if user is None:
            user = User(
                username="default",
                password_hash=get_password_hash("123456"),
                role_id=admin_role.id,
                status="active",
                display_name="Default Admin",
            )
        else:
            user.role_id = admin_role.id
            user.status = "active"
            user.updated_at = datetime.now(UTC)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

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
        display_name: str | None = None,
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
            display_name=display_name,
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
        display_name: str | None = None,
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
        if display_name is not None:
            user.display_name = display_name.strip() or None
        if email is not None:
            user.email = email.strip() or None
        user.updated_at = datetime.now(UTC)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
