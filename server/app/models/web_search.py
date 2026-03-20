"""Database models for agent-scoped web search provider bindings."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class AgentWebSearchBinding(SQLModel, table=True):
    """One configured web-search provider attached to a specific agent.

    Attributes:
        id: Primary key of the binding.
        agent_id: Agent that owns this configured provider binding.
        provider_key: Stable provider identifier, such as ``tavily`` or ``baidu``.
        enabled: Whether the provider is available to the agent at runtime.
        auth_config: JSON-encoded secret payload for the provider.
        runtime_config: JSON-encoded non-secret provider options.
        last_health_status: Latest connection-check outcome.
        last_health_message: Human-readable health details.
        last_health_check_at: UTC timestamp of the most recent health check.
        created_at: UTC timestamp when the binding was created.
        updated_at: UTC timestamp when the binding was last updated.
    """

    __table_args__ = (UniqueConstraint("agent_id", "provider_key"),)

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    provider_key: str = Field(index=True, max_length=100)
    enabled: bool = Field(default=True)
    auth_config: str = Field(default="{}")
    runtime_config: str = Field(default="{}")
    last_health_status: str | None = Field(default=None, max_length=32)
    last_health_message: str | None = Field(default=None, max_length=500)
    last_health_check_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
