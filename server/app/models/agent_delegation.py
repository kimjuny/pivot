from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class AgentDelegation(SQLModel, table=True):
    """Defines which agents this agent can delegate to and how.

    Each row represents a directed edge in the delegation graph: caller_agent_id
    can invoke callee_agent_id as a tool during its ReAct loop.
    """

    id: int | None = Field(default=None, primary_key=True)
    caller_agent_id: int = Field(
        foreign_key="agent.id",
        index=True,
        description="The agent that can initiate this delegation",
    )
    callee_agent_id: int = Field(
        foreign_key="agent.id",
        index=True,
        description="The agent being called (the delegate)",
    )
    callee_alias: str = Field(
        description=(
            "Short identifier used as the agent parameter value in "
            "delegate_to_agent tool calls. Must be unique per caller agent."
        ),
    )
    pass_mode: str = Field(
        default="instruction_only",
        description="instruction_only | with_context",
    )
    max_timeout_seconds: int = Field(
        default=300,
        description="Maximum wall-clock seconds for the delegated task",
    )
    max_iterations_override: int | None = Field(
        default=None,
        description=(
            "Override callee's max_iteration for delegated calls. "
            "None means use the callee's own setting."
        ),
    )
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
