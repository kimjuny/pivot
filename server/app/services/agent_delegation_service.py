"""Service for managing agent-to-agent delegation configurations."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.agent import Agent
from app.models.agent_delegation import AgentDelegation
from sqlmodel import col, select

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession


class AgentDelegationService:
    """CRUD operations for the agent delegation graph.

    Each row in AgentDelegation is a directed edge: caller_agent_id can invoke
    callee_agent_id as a tool during its ReAct loop.
    """

    def __init__(self, db: DBSession) -> None:
        self.db = db

    def list_by_caller(self, caller_agent_id: int) -> list[AgentDelegation]:
        """Return all delegations configured for a given caller agent."""
        return list(
            self.db.exec(
                select(AgentDelegation)
                .where(AgentDelegation.caller_agent_id == caller_agent_id)
                .order_by(col(AgentDelegation.priority))
            )
        )

    def list_enabled_by_caller(self, caller_agent_id: int) -> list[AgentDelegation]:
        """Return enabled delegations for a given caller agent."""
        return list(
            self.db.exec(
                select(AgentDelegation)
                .where(
                    AgentDelegation.caller_agent_id == caller_agent_id,
                    AgentDelegation.enabled == True,  # noqa: E712
                )
                .order_by(col(AgentDelegation.priority))
            )
        )

    def get_by_id(self, delegation_id: int) -> AgentDelegation | None:
        """Return one delegation row by primary key."""
        return self.db.get(AgentDelegation, delegation_id)

    def get_required(self, delegation_id: int) -> AgentDelegation:
        """Return one delegation row or raise ValueError."""
        delegation = self.get_by_id(delegation_id)
        if delegation is None:
            raise ValueError(f"Delegation {delegation_id} not found")
        return delegation

    def resolve_by_alias(
        self, caller_agent_id: int, alias: str
    ) -> AgentDelegation | None:
        """Look up an enabled delegation by its callee alias."""
        rows = self.db.exec(
            select(AgentDelegation).where(
                AgentDelegation.caller_agent_id == caller_agent_id,
                AgentDelegation.callee_alias == alias,
                AgentDelegation.enabled == True,  # noqa: E712
            )
        )
        return rows.first()

    def create(self, **kwargs: object) -> AgentDelegation:
        """Create a new delegation edge.

        Args:
            **kwargs: Fields matching AgentDelegation columns.

        Returns:
            The persisted delegation row.

        Raises:
            ValueError: If a cycle would be created.
        """
        caller_id_raw = kwargs.get("caller_agent_id")
        callee_id_raw = kwargs.get("callee_agent_id")
        caller_id = int(caller_id_raw) if isinstance(caller_id_raw, int | str) else None
        callee_id = int(callee_id_raw) if isinstance(callee_id_raw, int | str) else None
        if caller_id is not None and callee_id is not None:
            if caller_id == callee_id:
                raise ValueError("An agent cannot delegate to itself")
            if not self.validate_no_cycle(caller_id, callee_id):
                raise ValueError("Adding this delegation would create a cycle")
        alias = kwargs.get("callee_alias")
        if caller_id is not None and alias is not None:
            existing = self.resolve_by_alias(caller_id, str(alias))
            if existing is not None:
                raise ValueError(
                    f"Alias '{alias}' is already used for agent {caller_id}"
                )

        delegation = AgentDelegation(**kwargs)  # type: ignore[arg-type]
        self.db.add(delegation)
        self.db.commit()
        self.db.refresh(delegation)
        return delegation

    def update(self, delegation_id: int, **fields: object) -> AgentDelegation:
        """Update selected fields on a delegation row."""
        delegation = self.get_required(delegation_id)
        for key, value in fields.items():
            setattr(delegation, key, value)
        delegation.updated_at = datetime.now(UTC)
        self.db.add(delegation)
        self.db.commit()
        self.db.refresh(delegation)
        return delegation

    def delete(self, delegation_id: int) -> bool:
        """Delete a delegation row. Returns True if deleted."""
        delegation = self.get_by_id(delegation_id)
        if delegation is None:
            return False
        self.db.delete(delegation)
        self.db.commit()
        return True

    def replace_delegations(
        self, caller_agent_id: int, items: list[dict[str, object]]
    ) -> list[AgentDelegation]:
        """Atomically replace all delegations for a caller agent.

        Args:
            caller_agent_id: The agent whose delegations are being replaced.
            items: List of dicts with callee_agent_id, callee_alias, etc.

        Returns:
            The new list of delegation rows.
        """
        existing = self.list_by_caller(caller_agent_id)
        for row in existing:
            self.db.delete(row)

        new_rows: list[AgentDelegation] = []
        for item in items:
            delegation = AgentDelegation(
                caller_agent_id=caller_agent_id,
                callee_agent_id=int(item["callee_agent_id"]),  # type: ignore[arg-type]
                callee_alias=str(item["callee_alias"]),
                pass_mode=str(item.get("pass_mode", "instruction_only")),
                max_timeout_seconds=int(item.get("max_timeout_seconds", 300)),  # type: ignore[arg-type]
                max_iterations_override=int(item["max_iterations_override"])  # type: ignore[arg-type]
                if "max_iterations_override" in item
                and item["max_iterations_override"] is not None
                else None,
                enabled=bool(item.get("enabled", True)),
                priority=int(item.get("priority", 100)),  # type: ignore[arg-type]
            )
            self.db.add(delegation)
            new_rows.append(delegation)

        self.db.commit()
        for row in new_rows:
            self.db.refresh(row)
        return new_rows

    def validate_no_cycle(self, caller_agent_id: int, callee_agent_id: int) -> bool:
        """BFS check: would adding caller→callee create a cycle?

        Walks the existing delegation graph starting from callee_agent_id.
        If we can reach caller_agent_id, adding this edge would create a cycle.
        """
        visited: set[int] = set()
        queue: deque[int] = deque([callee_agent_id])

        while queue:
            current = queue.popleft()
            if current == caller_agent_id:
                return False
            if current in visited:
                continue
            visited.add(current)

            out_edges = self.db.exec(
                select(AgentDelegation.callee_agent_id).where(
                    AgentDelegation.caller_agent_id == current
                )
            )
            for neighbor in out_edges:
                queue.append(neighbor)

        return True

    def build_delegation_prompt_section(self, caller_agent_id: int) -> str:
        """Build the markdown table of delegatable agents for system prompt.

        Returns an empty string if no enabled delegations exist.
        """
        delegations = self.list_enabled_by_caller(caller_agent_id)
        if not delegations:
            return ""

        rows: list[str] = []
        for d in delegations:
            callee = self.db.get(Agent, d.callee_agent_id)
            if callee is None:
                continue
            if not callee.allow_delegation or callee.active_release_id is None:
                continue
            desc = callee.delegation_description or ""
            # Escape pipe characters in description for markdown table
            desc_escaped = desc.replace("|", "\\|")
            rows.append(f"| {d.callee_alias} | {callee.name} | {desc_escaped} |")

        if not rows:
            return ""

        return (
            "You can call other agents via the `delegate_to_agent` tool. "
            "Choose the most appropriate agent based on the task.\n\n"
            "| Identifier | Name | Description |\n"
            "|---|---|---|\n" + "\n".join(rows) + "\n\nExample: delegate_to_agent("
            'agent="research", instruction="Search for...")'
        )
