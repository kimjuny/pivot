"""Services for resource-level use/edit access checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.access import (
    AccessLevel,
    GroupMember,
    PrincipalType,
    ResourceAccess,
    ResourceType,
    Role,
)
from app.models.agent import Agent
from fastapi import HTTPException, status
from sqlmodel import col, select

if TYPE_CHECKING:
    from app.models.user import User
    from sqlmodel import Session as DBSession


class AccessService:
    """Manage generic resource grants and access decisions."""

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def is_admin(self, user: User) -> bool:
        """Return whether a user has the built-in admin role."""
        role = self.db.get(Role, user.role_id)
        return bool(
            user.status == "active" and role is not None and role.key == "admin"
        )

    def grant_access(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
        principal_type: PrincipalType,
        principal_id: int | str,
        access_level: AccessLevel,
    ) -> ResourceAccess:
        """Create one grant if it does not already exist."""
        resource_id_text = str(resource_id)
        principal_id_text = str(principal_id)
        existing = self.db.exec(
            select(ResourceAccess).where(
                ResourceAccess.resource_type == resource_type,
                ResourceAccess.resource_id == resource_id_text,
                ResourceAccess.principal_type == principal_type,
                ResourceAccess.principal_id == principal_id_text,
                ResourceAccess.access_level == access_level,
            )
        ).first()
        if existing is not None:
            return existing

        grant = ResourceAccess(
            resource_type=resource_type,
            resource_id=resource_id_text,
            principal_type=principal_type,
            principal_id=principal_id_text,
            access_level=access_level,
        )
        self.db.add(grant)
        self.db.commit()
        self.db.refresh(grant)
        return grant

    def list_resource_grants(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
        access_level: AccessLevel | None = None,
    ) -> list[ResourceAccess]:
        """List direct grants for one resource."""
        statement = select(ResourceAccess).where(
            ResourceAccess.resource_type == resource_type,
            ResourceAccess.resource_id == str(resource_id),
        )
        if access_level is not None:
            statement = statement.where(ResourceAccess.access_level == access_level)
        return list(self.db.exec(statement).all())

    def replace_resource_grants(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
        access_level: AccessLevel,
        user_ids: set[int],
        group_ids: set[int],
    ) -> list[ResourceAccess]:
        """Replace all direct grants for one resource and access level."""
        grants = self._replace_resource_grants_in_session(
            resource_type=resource_type,
            resource_id=resource_id,
            access_level=access_level,
            user_ids=user_ids,
            group_ids=group_ids,
        )
        self.db.commit()
        for grant in grants:
            self.db.refresh(grant)
        return grants

    def delete_resource_grants(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
    ) -> None:
        """Delete every direct grant for one resource."""
        self._delete_resource_grants_in_session(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        self.db.commit()

    def _delete_resource_grants_in_session(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
    ) -> None:
        """Stage direct grant deletion in the current DB session."""
        for grant in self.list_resource_grants(
            resource_type=resource_type,
            resource_id=resource_id,
        ):
            self.db.delete(grant)

    def _replace_resource_grants_in_session(
        self,
        *,
        resource_type: ResourceType,
        resource_id: int | str,
        access_level: AccessLevel,
        user_ids: set[int],
        group_ids: set[int],
    ) -> list[ResourceAccess]:
        """Stage direct grant replacements in the current DB session."""
        existing = self.list_resource_grants(
            resource_type=resource_type,
            resource_id=resource_id,
            access_level=access_level,
        )
        for grant in existing:
            self.db.delete(grant)
        self.db.flush()

        grants: list[ResourceAccess] = []
        for user_id in sorted(user_ids):
            grants.append(
                ResourceAccess(
                    resource_type=resource_type,
                    resource_id=str(resource_id),
                    principal_type=PrincipalType.USER,
                    principal_id=str(user_id),
                    access_level=access_level,
                )
            )
        for group_id in sorted(group_ids):
            grants.append(
                ResourceAccess(
                    resource_type=resource_type,
                    resource_id=str(resource_id),
                    principal_type=PrincipalType.GROUP,
                    principal_id=str(group_id),
                    access_level=access_level,
                )
            )

        for grant in grants:
            self.db.add(grant)
        return grants

    def grant_creator_edit(self, *, agent: Agent, user: User) -> None:
        """Grant creator edit access for a newly created agent."""
        if agent.id is None or user.id is None:
            raise ValueError("Agent and user must be persisted before granting access.")
        agent.created_by_user_id = user.id
        agent.updated_at = datetime.now(UTC)
        self.db.add(agent)
        self.db.commit()
        self.grant_access(
            resource_type=ResourceType.AGENT,
            resource_id=agent.id,
            principal_type=PrincipalType.USER,
            principal_id=user.id,
            access_level=AccessLevel.EDIT,
        )

    def set_agent_access(
        self,
        *,
        agent: Agent,
        use_scope: str,
        use_user_ids: set[int],
        use_group_ids: set[int],
        edit_user_ids: set[int],
        edit_group_ids: set[int],
    ) -> None:
        """Replace use/edit access for one agent."""
        if agent.id is None:
            raise ValueError("Agent must be persisted before access can be updated.")
        if use_scope not in {"all", "selected"}:
            raise ValueError("use_scope must be 'all' or 'selected'.")

        creator_id = agent.created_by_user_id
        if creator_id is not None:
            edit_user_ids = set(edit_user_ids)
            edit_user_ids.add(creator_id)
            if use_scope == "selected":
                use_user_ids = set(use_user_ids)
                use_user_ids.add(creator_id)

        agent.use_scope = use_scope
        agent.updated_at = datetime.now(UTC)
        self.db.add(agent)

        self._replace_resource_grants_in_session(
            resource_type=ResourceType.AGENT,
            resource_id=agent.id,
            access_level=AccessLevel.USE,
            user_ids=use_user_ids if use_scope == "selected" else set(),
            group_ids=use_group_ids if use_scope == "selected" else set(),
        )
        self._replace_resource_grants_in_session(
            resource_type=ResourceType.AGENT,
            resource_id=agent.id,
            access_level=AccessLevel.EDIT,
            user_ids=edit_user_ids,
            group_ids=edit_group_ids,
        )
        self.db.commit()
        self.db.refresh(agent)

    def _user_group_ids(self, user: User) -> list[str]:
        if user.id is None:
            return []
        rows = self.db.exec(
            select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        ).all()
        return [str(group_id) for group_id in rows]

    def _grant_levels_for_user(
        self,
        *,
        user: User,
        resource_type: ResourceType,
        resource_id: int | str,
    ) -> set[AccessLevel]:
        if user.id is None:
            return set()

        user_principal = (PrincipalType.USER, str(user.id))
        group_ids = self._user_group_ids(user)
        group_principals = {(PrincipalType.GROUP, group_id) for group_id in group_ids}

        statement = select(ResourceAccess).where(
            ResourceAccess.resource_type == resource_type,
            ResourceAccess.resource_id == str(resource_id),
        )
        levels: set[AccessLevel] = set()
        for grant in self.db.exec(statement).all():
            principal = (grant.principal_type, grant.principal_id)
            if principal == user_principal or principal in group_principals:
                levels.add(grant.access_level)
        return levels

    def has_agent_access(
        self,
        *,
        user: User,
        agent: Agent,
        access_level: AccessLevel,
    ) -> bool:
        """Return whether a user may use or edit one agent."""
        return self.has_resource_access(
            user=user,
            resource_type=ResourceType.AGENT,
            resource_id=agent.id,
            access_level=access_level,
            creator_user_id=agent.created_by_user_id,
            use_scope=agent.use_scope,
        )

    def has_resource_access(
        self,
        *,
        user: User,
        resource_type: ResourceType,
        resource_id: int | str | None,
        access_level: AccessLevel,
        creator_user_id: int | None = None,
        use_scope: str = "selected",
    ) -> bool:
        """Return whether a user may use or edit one generic resource."""
        if user.status != "active":
            return False
        if self.is_admin(user):
            return True
        if resource_id is None:
            return False
        if user.id is not None and creator_user_id == user.id:
            return True
        if access_level == AccessLevel.USE and use_scope == "all":
            return True

        grants = self._grant_levels_for_user(
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        if AccessLevel.EDIT in grants:
            return True
        return access_level == AccessLevel.USE and AccessLevel.USE in grants

    def require_resource_access(
        self,
        *,
        user: User,
        resource_type: ResourceType,
        resource_id: int | str | None,
        access_level: AccessLevel,
        creator_user_id: int | None = None,
        use_scope: str = "selected",
    ) -> None:
        """Raise 403 unless the user has access to one generic resource."""
        if self.has_resource_access(
            user=user,
            resource_type=resource_type,
            resource_id=resource_id,
            access_level=access_level,
            creator_user_id=creator_user_id,
            use_scope=use_scope,
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    def require_agent_access(
        self,
        *,
        user: User,
        agent: Agent,
        access_level: AccessLevel,
    ) -> None:
        """Raise 403 unless the user has agent access."""
        if self.has_agent_access(user=user, agent=agent, access_level=access_level):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    def list_accessible_agents(
        self,
        *,
        user: User,
        access_level: AccessLevel,
        require_published: bool = False,
        require_serving: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Agent]:
        """List agents the user can use or edit."""
        statement = select(Agent).order_by(col(Agent.updated_at).desc())
        if require_published:
            statement = statement.where(col(Agent.active_release_id).is_not(None))
        if require_serving:
            statement = statement.where(col(Agent.serving_enabled).is_(True))

        agents = list(self.db.exec(statement).all())
        visible = [
            agent
            for agent in agents
            if self.has_agent_access(
                user=user,
                agent=agent,
                access_level=access_level,
            )
        ]
        return visible[skip : skip + limit]
