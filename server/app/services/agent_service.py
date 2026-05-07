"""Reusable service helpers for persisted agent state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.agent import Agent
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


OPEN_CLIENT_STATE = "open"
PAUSED_CLIENT_STATE = "paused"
DRAINING_CLIENT_STATE = "draining_for_upgrade"
UPGRADE_REQUIRED_CLIENT_STATE = "upgrade_required"
VALID_CLIENT_STATES = {
    OPEN_CLIENT_STATE,
    PAUSED_CLIENT_STATE,
    DRAINING_CLIENT_STATE,
    UPGRADE_REQUIRED_CLIENT_STATE,
}


class AgentService:
    """Provide reusable CRUD-like operations over persisted agent rows.

    Why: agent availability and release activation are now platform-level
    concerns shared by Studio publishing, session creation, and runtime
    request gating. Centralizing these writes keeps API handlers thin and
    avoids duplicating persistence rules across call sites.
    """

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with one database session.

        Args:
            db: Database session used for persistence operations.
        """
        self.db = db

    def get_agent(self, agent_id: int) -> Agent | None:
        """Return one agent row when it exists.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching agent row, or ``None`` when absent.
        """
        return self.db.get(Agent, agent_id)

    def get_required_agent(self, agent_id: int) -> Agent:
        """Return one agent row or raise when it does not exist.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching agent row.

        Raises:
            ValueError: If the agent does not exist.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent

    def update_agent_fields(self, agent_id: int, **fields: object) -> Agent:
        """Persist one partial update onto an agent row.

        Args:
            agent_id: Stable agent identifier.
            **fields: Field values to write onto the row.

        Returns:
            The refreshed updated agent row.

        Raises:
            ValueError: If the agent does not exist.
        """
        agent = self.get_required_agent(agent_id)
        for key, value in fields.items():
            setattr(agent, key, value)
        agent.updated_at = datetime.now(UTC)
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def set_active_release(
        self,
        agent_id: int,
        release_id: int | None,
    ) -> Agent:
        """Update the release used by default for new end-user sessions.

        Args:
            agent_id: Stable agent identifier.
            release_id: Published release identifier, or ``None`` to clear it.

        Returns:
            The refreshed updated agent row.
        """
        return self.update_agent_fields(agent_id, active_release_id=release_id)

    def set_client_state(
        self,
        agent_id: int,
        client_state: str,
    ) -> Agent:
        """Update one agent's end-user availability state.

        Args:
            agent_id: Stable agent identifier.
            client_state: Desired end-user availability state.

        Returns:
            The refreshed updated agent row.
        """
        if client_state not in VALID_CLIENT_STATES:
            raise ValueError(f"Unsupported client state '{client_state}'")
        return self.update_agent_fields(agent_id, client_state=client_state)

    def require_session_creation_ready(self, agent_id: int) -> Agent:
        """Return one agent that is ready to accept a new user session.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching agent row.

        Raises:
            ValueError: If the agent does not exist, has no active release, or is
                currently disabled for end-user traffic.
        """
        agent = self.get_required_agent(agent_id)
        if agent.active_release_id is None:
            raise ValueError("Agent is not published for end users yet")
        if agent.client_state != OPEN_CLIENT_STATE:
            if agent.client_state == PAUSED_CLIENT_STATE:
                raise ValueError("Agent is currently paused for end users")
            if agent.client_state == DRAINING_CLIENT_STATE:
                raise ValueError("Agent is preparing for an upgrade")
            if agent.client_state == UPGRADE_REQUIRED_CLIENT_STATE:
                raise ValueError("Agent is awaiting a new published release")
            raise ValueError("Agent is currently unavailable for end users")
        return agent

    def list_consumer_visible_agents(self) -> list[Agent]:
        """List agents currently visible in the end-user product.

        Returns:
            Agent rows that have a published active release and are enabled for
            end-user traffic.
        """
        statement = (
            select(Agent)
            .where(col(Agent.active_release_id).is_not(None))
            .where(col(Agent.client_state) == OPEN_CLIENT_STATE)
            .order_by(col(Agent.updated_at).desc())
        )
        return list(self.db.exec(statement).all())

    def get_consumer_visible_agent(self, agent_id: int) -> Agent | None:
        """Return one agent only when it is visible in Consumer.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching visible agent, or ``None`` when absent or unavailable.
        """
        statement = (
            select(Agent)
            .where(Agent.id == agent_id)
            .where(col(Agent.active_release_id).is_not(None))
            .where(col(Agent.client_state) == OPEN_CLIENT_STATE)
        )
        return self.db.exec(statement).first()

    def require_consumer_visible_agent(self, agent_id: int) -> Agent:
        """Return one Consumer-visible agent or raise.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching visible agent row.

        Raises:
            ValueError: If the agent is not available to end users.
        """
        agent = self.get_consumer_visible_agent(agent_id)
        if agent is None:
            raise ValueError("Agent is not available to end users")
        return agent

    def require_interaction_enabled(self, agent_id: int) -> Agent:
        """Return one agent when runtime interaction is still allowed.

        Args:
            agent_id: Stable agent identifier.

        Returns:
            The matching agent row.

        Raises:
            ValueError: If the agent does not exist or is disabled.
        """
        agent = self.get_required_agent(agent_id)
        if agent.client_state != OPEN_CLIENT_STATE:
            if agent.client_state == PAUSED_CLIENT_STATE:
                raise ValueError("This agent is temporarily paused")
            if agent.client_state == DRAINING_CLIENT_STATE:
                raise ValueError("This agent is preparing for an upgrade")
            if agent.client_state == UPGRADE_REQUIRED_CLIENT_STATE:
                raise ValueError("This agent requires a new published release")
            raise ValueError("This agent is temporarily unavailable")
        return agent
