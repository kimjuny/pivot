from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


class LLM(SQLModel, table=True):
    """LLM model representing a Large Language Model configuration.

    Attributes:
        id: Primary key of the LLM.
        name: Unique logical name for the LLM in the platform.
        endpoint: HTTP API Base URL for the LLM service.
        model: Model identifier passed to the API.
        api_key: Authentication credential for the LLM (encrypted storage recommended).
        protocol: Protocol specification (e.g., 'openai_chat_v1', 'anthropic_messages_v1').
        chat: Whether the model supports multi-turn conversation with message roles.
        system_role: Whether the model truly distinguishes system role with higher priority.
        tool_calling: Tool calling support level ('native', 'prompt', 'none').
        json_schema: JSON output reliability ('strong', 'weak', 'none').
        streaming: Whether the model supports streaming responses.
        max_context: Maximum context token limit.
        created_at: UTC timestamp when the LLM was created.
        updated_at: UTC timestamp when the LLM was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    endpoint: str = Field(description="HTTP API Base URL")
    model: str = Field(description="Model identifier for API")
    api_key: str = Field(description="Authentication credential (should be encrypted)")
    protocol: str = Field(
        default="openai_compatible",
        description="Protocol specification ('openai_compatible' or 'anthropic_compatible')",
    )
    chat: bool = Field(
        default=True, description="Supports multi-turn conversation with message roles"
    )
    system_role: bool = Field(
        default=True, description="Distinguishes system role with higher priority"
    )
    tool_calling: str = Field(
        default="native",
        description="Tool calling support: 'native', 'prompt', or 'none'",
    )
    json_schema: str = Field(
        default="strong",
        description="JSON output reliability: 'strong', 'weak', or 'none'",
    )
    streaming: bool = Field(default=True, description="Supports streaming responses")
    max_context: int = Field(default=128000, description="Maximum context token limit")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
