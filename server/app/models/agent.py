from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Agent(SQLModel, table=True):
    """Agent model representing an AI agent configuration."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = Field(default=None)
    llm_id: int | None = Field(default=None, foreign_key="llm.id", index=True)
    session_idle_timeout_minutes: int = Field(
        default=15,
        description=(
            "Minutes of inactivity before the client starts a new chat session"
        ),
    )
    sandbox_timeout_seconds: int = Field(
        default=60,
        description=(
            "Maximum seconds to wait for sandbox-manager responses for this agent"
        ),
    )
    compact_threshold_percent: int = Field(
        default=60,
        description=(
            "Context-window percentage that triggers automatic runtime compaction"
        ),
    )
    active_release_id: int | None = Field(
        default=None,
        index=True,
        description=(
            "Published release used for newly created end-user sessions. "
            "None means the agent is not yet available to end users."
        ),
    )
    serving_enabled: bool = Field(
        default=True,
        description="Whether this agent currently accepts end-user traffic.",
    )
    model_name: str | None = Field(
        default=None, description="Deprecated: Use llm_id instead"
    )
    is_active: bool = Field(default=True)
    max_iteration: int = Field(
        default=50, description="Maximum iterations for ReAct recursion"
    )
    tool_ids: str | None = Field(
        default=None,
        description="JSON array of allowed tool names. None = all tools; '[]' = none.",
    )
    skill_ids: str | None = Field(
        default=None,
        description=(
            "JSON array of allowed globally unique skill names. "
            "None = all visible skills; '[]' = none."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
