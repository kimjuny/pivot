import json
from datetime import datetime

from app.schemas.base import AppBaseModel
from pydantic import Field, field_validator


def _normalize_extra_config(extra_config: str | None) -> str | None:
    """Normalize and validate LLM extra_config payload.

    Args:
        extra_config: JSON string provided by API caller.

    Returns:
        Canonical JSON string for object payloads, or None when blank.

    Raises:
        ValueError: If value is not valid JSON or not a JSON object.
    """
    if extra_config is None:
        return None
    stripped = extra_config.strip()
    if not stripped:
        return None

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("extra_config must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("extra_config must be a JSON object")
    return json.dumps(parsed, separators=(",", ":"))


class AgentCreate(AppBaseModel):
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    llm_id: int = Field(..., description="LLM configuration ID")
    session_idle_timeout_minutes: int = Field(
        default=15,
        ge=1,
        description="Minutes of inactivity before a new chat session is created",
    )
    sandbox_timeout_seconds: int = Field(
        default=60,
        ge=1,
        description="Maximum seconds to wait for sandbox-manager responses",
    )
    compact_threshold_percent: int = Field(
        default=60,
        ge=1,
        le=100,
        description="Context percentage that triggers automatic compaction",
    )
    is_active: bool = Field(default=True, description="Whether agent is active")
    max_iteration: int = Field(
        default=50, ge=1, description="Maximum iterations for ReAct recursion"
    )


class AgentUpdate(AppBaseModel):
    name: str | None = None
    description: str | None = None
    llm_id: int | None = None
    session_idle_timeout_minutes: int | None = Field(default=None, ge=1)
    sandbox_timeout_seconds: int | None = Field(default=None, ge=1)
    compact_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None
    max_iteration: int | None = Field(default=None, ge=1)
    # JSON-encoded list of tool names, or None to leave unchanged
    tool_ids: str | None = None
    # JSON-encoded list of globally unique skill names, or None to leave unchanged
    skill_ids: str | None = None


class AgentServingUpdate(AppBaseModel):
    """Schema for updating whether an agent serves end-user traffic."""

    serving_enabled: bool = Field(
        ...,
        description="Whether this agent currently accepts end-user traffic",
    )


class AgentResponse(AppBaseModel):
    id: int
    name: str
    description: str | None
    llm_id: int | None
    session_idle_timeout_minutes: int
    sandbox_timeout_seconds: int
    compact_threshold_percent: int
    active_release_id: int | None
    active_release_version: int | None = None
    serving_enabled: bool
    model_name: str | None
    is_active: bool
    max_iteration: int
    tool_ids: str | None
    skill_ids: str | None
    created_at: datetime
    updated_at: datetime


class AgentReleaseResponse(AppBaseModel):
    """Published immutable release metadata for one agent."""

    id: int
    version: int
    release_note: str | None
    change_summary: list[str] = Field(default_factory=list)
    published_by: str | None
    created_at: datetime


class AgentSavedDraftInfoResponse(AppBaseModel):
    """Current saved-draft metadata for one agent."""

    saved_at: datetime
    saved_by: str | None
    snapshot_hash: str


class AgentDraftStateResponse(AppBaseModel):
    """Toolbar-facing draft/release state for one agent."""

    saved_draft: AgentSavedDraftInfoResponse
    latest_release: AgentReleaseResponse | None
    has_publishable_changes: bool
    publish_summary: list[str] = Field(default_factory=list)
    release_history: list[AgentReleaseResponse] = Field(default_factory=list)


class AgentPublishRequest(AppBaseModel):
    """Payload for publishing the current saved draft as a release."""

    release_note: str | None = Field(default=None, max_length=4000)


class LLMCreate(AppBaseModel):
    """Schema for creating a new LLM."""

    name: str = Field(..., description="Unique logical name for the LLM")
    endpoint: str = Field(..., description="HTTP API Base URL")
    model: str = Field(..., description="Model identifier for API")
    api_key: str = Field(..., description="Authentication credential")
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

    @field_validator("extra_config")
    @classmethod
    def validate_extra_config(
        cls,
        extra_config: str | None,
    ) -> str | None:
        """Validate that extra_config is a JSON object string."""
        return _normalize_extra_config(extra_config)


class LLMUpdate(AppBaseModel):
    """Schema for updating an existing LLM."""

    name: str | None = None
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    protocol: str | None = None
    cache_policy: str | None = None
    thinking_policy: str | None = None
    thinking_effort: str | None = None
    thinking_budget_tokens: int | None = None
    streaming: bool | None = None
    image_input: bool | None = None
    image_output: bool | None = None
    max_context: int | None = None
    extra_config: str | None = None

    @field_validator("extra_config")
    @classmethod
    def validate_extra_config(
        cls,
        extra_config: str | None,
    ) -> str | None:
        """Validate that extra_config is a JSON object string."""
        return _normalize_extra_config(extra_config)


class LLMResponse(AppBaseModel):
    """Schema for LLM response."""

    id: int
    name: str
    endpoint: str
    model: str
    api_key: str
    protocol: str
    cache_policy: str
    thinking_policy: str
    thinking_effort: str | None
    thinking_budget_tokens: int | None
    streaming: bool
    image_input: bool
    image_output: bool
    max_context: int
    extra_config: str | None
    created_at: datetime
    updated_at: datetime
