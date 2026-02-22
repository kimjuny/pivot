"""Agent-Tool association model.

This module defines the many-to-many relationship between agents and tools,
allowing each agent to have its own set of callable tools.
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class AgentTool(SQLModel, table=True):
    """Association table linking agents to their available tools.

    This enables per-agent tool configuration, where each agent can only
    call the tools explicitly assigned to it.

    Attributes:
        id: Primary key of the association.
        agent_id: Foreign key to the agent.
        tool_name: Name of the tool (matches tool registry name).
        created_at: UTC timestamp when the association was created.
    """

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    tool_name: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentToolsUpdate(SQLModel):
    """Schema for updating an agent's tool assignments.

    Attributes:
        tool_names: List of tool names to assign to the agent.
            This replaces the current tool list entirely.
    """

    tool_names: list[str]


class AgentToolResponse(SQLModel):
    """Schema for agent tool response.

    Attributes:
        name: Name of the tool.
        description: Description of what the tool does.
        tool_type: Whether the tool is shared (builtin) or private (user-created).
        is_enabled: Whether this tool is enabled for the agent.
    """

    name: str
    description: str
    tool_type: str
    is_enabled: bool
