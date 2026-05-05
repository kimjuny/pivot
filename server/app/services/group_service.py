"""Services for lightweight authorization groups."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.access import GroupMember, PrincipalType, ResourceAccess, UserGroup
from app.models.user import User
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


class GroupService:
    """CRUD-style service for groups and memberships."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def list_groups(self) -> list[UserGroup]:
        """List all groups."""
        statement = select(UserGroup).order_by(col(UserGroup.name))
        return list(self.db.exec(statement).all())

    def get_group(self, group_id: int) -> UserGroup | None:
        """Return one group by id."""
        return self.db.get(UserGroup, group_id)

    def get_member_count_by_group_id(self) -> dict[int, int]:
        """Return member counts keyed by group id."""
        counts: dict[int, int] = {}
        for row in self.db.exec(select(GroupMember)).all():
            counts[row.group_id] = counts.get(row.group_id, 0) + 1
        return counts

    def list_members(self, group_id: int) -> list[User]:
        """List users in one group."""
        member_user_ids = [
            row.user_id
            for row in self.db.exec(
                select(GroupMember).where(GroupMember.group_id == group_id)
            ).all()
        ]
        if not member_user_ids:
            return []
        statement = (
            select(User)
            .where(col(User.id).in_(member_user_ids))
            .order_by(col(User.username))
        )
        return list(self.db.exec(statement).all())

    def create_group(
        self,
        *,
        name: str,
        description: str = "",
        created_by_user_id: int | None = None,
    ) -> UserGroup:
        """Create one group."""
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Group name is required")
        existing = self.db.exec(
            select(UserGroup).where(UserGroup.name == normalized_name)
        ).first()
        if existing is not None:
            raise ValueError("Group name already exists")

        group = UserGroup(
            name=normalized_name,
            description=description.strip(),
            created_by_user_id=created_by_user_id,
        )
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return group

    def update_group(
        self,
        *,
        group_id: int,
        name: str | None = None,
        description: str | None = None,
    ) -> UserGroup | None:
        """Update editable group metadata."""
        group = self.db.get(UserGroup, group_id)
        if group is None:
            return None
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise ValueError("Group name is required")
            existing = self.db.exec(
                select(UserGroup).where(UserGroup.name == normalized_name)
            ).first()
            if existing is not None and existing.id != group_id:
                raise ValueError("Group name already exists")
            group.name = normalized_name
        if description is not None:
            group.description = description.strip()
        group.updated_at = datetime.now(UTC)
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return group

    def replace_members(self, *, group_id: int, user_ids: set[int]) -> list[User]:
        """Replace all members for one group."""
        group = self.db.get(UserGroup, group_id)
        if group is None:
            raise ValueError("Group not found")

        users = list(self.db.exec(select(User).where(col(User.id).in_(user_ids))).all())
        found_user_ids = {user.id for user in users if user.id is not None}
        missing_user_ids = user_ids - found_user_ids
        if missing_user_ids:
            raise ValueError("User not found")

        existing = self.db.exec(
            select(GroupMember).where(GroupMember.group_id == group_id)
        ).all()
        for row in existing:
            self.db.delete(row)
        self.db.flush()
        for user_id in sorted(user_ids):
            self.db.add(GroupMember(group_id=group_id, user_id=user_id))

        group.updated_at = datetime.now(UTC)
        self.db.add(group)
        self.db.commit()
        self.db.refresh(group)
        return self.list_members(group_id)

    def delete_group(self, group_id: int) -> bool:
        """Delete one group and its direct grants."""
        group = self.db.get(UserGroup, group_id)
        if group is None:
            return False
        for row in self.db.exec(
            select(GroupMember).where(GroupMember.group_id == group_id)
        ).all():
            self.db.delete(row)
        for grant in self.db.exec(
            select(ResourceAccess).where(
                ResourceAccess.principal_type == PrincipalType.GROUP,
                ResourceAccess.principal_id == str(group_id),
            )
        ).all():
            self.db.delete(grant)
        self.db.delete(group)
        self.db.commit()
        return True
