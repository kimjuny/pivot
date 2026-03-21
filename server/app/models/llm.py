from datetime import UTC, datetime
from typing import Any

from sqlmodel import Field, SQLModel


class LLM(SQLModel, table=True):
    """LLM model representing a Large Language Model configuration.

    Attributes:
        id: Primary key of the LLM.
        name: Unique logical name for the LLM in the platform.
        endpoint: HTTP API Base URL for the LLM service.
        model: Model identifier passed to the API.
        api_key: Authentication credential for the LLM (encrypted storage recommended).
        protocol: Protocol specification
            (e.g., 'openai_completion_llm', 'openai_response_llm').
        cache_policy: Protocol-specific cache strategy.
        thinking_policy: Protocol-specific thinking strategy used for the
            chat-level Thinking mode toggle.
        thinking_effort: Optional effort tier for effort-based thinking policies.
        thinking_budget_tokens: Optional token budget for extended thinking.
        streaming: Whether the model supports streaming responses.
        image_input: Whether the model accepts user-supplied image inputs.
        image_output: Whether the model can produce image outputs.
        max_context: Maximum context token limit.
        extra_config: Additional kwargs to pass to LLM API calls (JSON format).
            Example: {"extra_body": {"reasoning_split": true}, "temperature": 0.7}
        created_at: UTC timestamp when the LLM was created.
        updated_at: UTC timestamp when the LLM was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    endpoint: str = Field(description="HTTP API Base URL")
    model: str = Field(description="Model identifier for API")
    api_key: str = Field(description="Authentication credential (should be encrypted)")
    protocol: str = Field(
        default="openai_completion_llm",
        description=(
            "Protocol specification "
            "('openai_completion_llm', 'openai_response_llm', or 'anthropic_compatible')"
        ),
    )
    cache_policy: str = Field(
        default="none",
        description="Cache policy selected for this protocol",
    )
    thinking_policy: str = Field(
        default="auto",
        description="Thinking policy selected for this protocol",
    )
    thinking_effort: str | None = Field(
        default=None,
        description="Optional effort tier for effort-based thinking policies",
    )
    thinking_budget_tokens: int | None = Field(
        default=None,
        description="Optional budget token count for extended thinking policies",
    )
    streaming: bool = Field(default=True, description="Supports streaming responses")
    image_input: bool = Field(
        default=False,
        description="Accepts user-supplied image inputs",
    )
    image_output: bool = Field(
        default=False,
        description="Can produce image outputs",
    )
    max_context: int = Field(default=128000, description="Maximum context token limit")
    extra_config: str | None = Field(
        default=None,
        description="Additional kwargs for API calls (JSON format). E.g.: {'extra_body': {'reasoning_split': true}}",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_extra_config(self) -> dict[str, Any]:
        """Parse and return the extra_config as a dictionary.

        Returns:
            Dictionary of extra configuration parameters, or empty dict if not set.
        """
        import json

        if not self.extra_config:
            return {}
        try:
            parsed = json.loads(self.extra_config)
            # Keep kwargs contract stable for LLM clients.
            if isinstance(parsed, dict):
                return parsed
            return {}
        except json.JSONDecodeError:
            return {}
