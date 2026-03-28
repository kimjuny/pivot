import json
from datetime import datetime

from app.schemas.base import AppBaseModel
from pydantic import ConfigDict, Field, field_validator


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
    skill_resolution_llm_id: int | None = Field(
        None, description="Optional LLM ID for skill selection only"
    )
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
        default=30, description="Maximum iterations for ReAct recursion"
    )


class AgentUpdate(AppBaseModel):
    name: str | None = None
    description: str | None = None
    llm_id: int | None = None
    skill_resolution_llm_id: int | None = None
    session_idle_timeout_minutes: int | None = Field(default=None, ge=1)
    sandbox_timeout_seconds: int | None = Field(default=None, ge=1)
    compact_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None
    max_iteration: int | None = None
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
    skill_resolution_llm_id: int | None
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


class SceneCreate(AppBaseModel):
    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    agent_id: int | None = Field(None, description="Agent ID")


class SceneUpdate(AppBaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SceneResponse(AppBaseModel):
    id: int
    name: str
    description: str | None
    agent_id: int | None
    created_at: datetime
    updated_at: datetime


class SubsceneCreate(AppBaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(
        default="inactive", description="Subscene state: active, inactive"
    )
    description: str | None = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: str | None = Field(None, description="Subscene objective")


class SubsceneUpdate(AppBaseModel):
    name: str | None = None
    type: str | None = None
    state: str | None = None
    description: str | None = None
    mandatory: bool | None = None
    objective: str | None = None


class SubsceneResponse(AppBaseModel):
    id: int
    name: str
    type: str
    state: str
    description: str | None
    mandatory: bool
    objective: str | None
    scene_id: int
    created_at: datetime
    updated_at: datetime


class ConnectionCreate(AppBaseModel):
    name: str = Field(..., description="Connection name")
    condition: str | None = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    from_subscene_id: int | None = Field(None, description="Source subscene ID")
    to_subscene_id: int | None = Field(None, description="Target subscene ID")
    scene_id: int | None = Field(None, description="Scene ID")


class ConnectionUpdate(AppBaseModel):
    name: str | None = None
    condition: str | None = None
    from_subscene: str | None = None
    to_subscene: str | None = None
    from_subscene_id: int | None = None
    to_subscene_id: int | None = None
    scene_id: int | None = None


class ConnectionResponse(AppBaseModel):
    id: int | str
    name: str
    condition: str | None
    from_subscene: str
    to_subscene: str
    from_subscene_id: int | str | None
    to_subscene_id: int | str | None
    scene_id: int | str | None
    created_at: datetime
    updated_at: datetime


class SubsceneWithConnectionsResponse(AppBaseModel):
    id: int | str | None
    name: str
    type: str
    state: str
    description: str | None
    mandatory: bool
    objective: str | None
    scene_id: int | str | None
    connections: list[ConnectionResponse]
    created_at: datetime
    updated_at: datetime


class SceneGraphResponse(AppBaseModel):
    id: int | str
    name: str
    description: str | None
    state: str
    agent_id: int | str
    subscenes: list[SubsceneWithConnectionsResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


class AgentDetailResponse(AgentResponse):
    """Agent response with full details including scenes and their graphs."""

    scenes: list[SceneGraphResponse] = Field(default_factory=list)


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


class SceneGraphUpdate(AppBaseModel):
    """Schema for bulk updating scene graph data."""

    subscenes: list[dict] = Field(
        ..., description="List of subscenes with their connections"
    )
    agent_id: int | None = Field(None, description="Agent ID")


class ConnectionGraphItem(AppBaseModel):
    """Schema for a connection within a subscene update."""

    name: str = Field(default="", description="Connection name")
    condition: str | None = Field(None, description="Condition for transition")
    to_subscene: str = Field(..., description="Target subscene name")


class SubsceneGraphItem(AppBaseModel):
    """Schema for a subscene within a graph update."""

    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Type: start, normal, end")
    state: str = Field(default="inactive", description="State: active, inactive")
    description: str | None = Field(None, description="Description of the subscene")
    mandatory: bool = Field(default=False, description="Is completion mandatory")
    objective: str | None = Field(None, description="Objective of the subscene")
    connections: list[ConnectionGraphItem] = Field(
        default_factory=list,
        description="Outbound connections",
    )


class SceneWithGraphUpdate(AppBaseModel):
    """Schema for scene update including nested graph."""

    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    graph: list[SubsceneGraphItem] | None = Field(
        None, description="Scene graph data (subscenes and connections)"
    )


class AgentSceneListUpdate(AppBaseModel):
    """Schema for bulk updating agent scenes list with optional graph content."""

    scenes: list[SceneWithGraphUpdate] = Field(
        ..., description="List of scenes to update"
    )


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
