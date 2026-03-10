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


def _normalize_thinking_mode(thinking: str | None) -> str | None:
    """Normalize and validate LLM thinking mode."""
    if thinking is None:
        return None
    normalized = thinking.strip().lower()
    if not normalized:
        return "auto"
    if normalized not in {"auto", "enabled", "disabled"}:
        raise ValueError("thinking must be one of: auto, enabled, disabled")
    return normalized


class AgentCreate(AppBaseModel):
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    llm_id: int = Field(..., description="LLM configuration ID")
    skill_resolution_llm_id: int | None = Field(
        None, description="Optional LLM ID for skill selection only"
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
    is_active: bool | None = None
    max_iteration: int | None = None
    # JSON-encoded list of tool names, or None to leave unchanged
    tool_ids: str | None = None
    # JSON-encoded list of skill names, or None to leave unchanged
    skill_ids: str | None = None


class AgentResponse(AppBaseModel):
    id: int
    name: str
    description: str | None
    llm_id: int | None
    skill_resolution_llm_id: int | None
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
    thinking: str = Field(
        default="auto",
        description="Thinking mode: 'auto', 'enabled', or 'disabled'",
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

    @field_validator("thinking")
    @classmethod
    def validate_thinking(
        cls,
        thinking: str,
    ) -> str:
        """Validate and normalize thinking mode."""
        normalized = _normalize_thinking_mode(thinking)
        return normalized if normalized is not None else "auto"


class LLMUpdate(AppBaseModel):
    """Schema for updating an existing LLM."""

    name: str | None = None
    endpoint: str | None = None
    model: str | None = None
    api_key: str | None = None
    protocol: str | None = None
    cache_policy: str | None = None
    chat: bool | None = None
    system_role: bool | None = None
    tool_calling: str | None = None
    json_schema: str | None = None
    thinking: str | None = None
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

    @field_validator("thinking")
    @classmethod
    def validate_thinking(
        cls,
        thinking: str | None,
    ) -> str | None:
        """Validate and normalize thinking mode when provided."""
        return _normalize_thinking_mode(thinking)


class LLMResponse(AppBaseModel):
    """Schema for LLM response."""

    id: int
    name: str
    endpoint: str
    model: str
    api_key: str
    protocol: str
    cache_policy: str
    chat: bool
    system_role: bool
    tool_calling: str
    json_schema: str
    thinking: str
    streaming: bool
    image_input: bool
    image_output: bool
    max_context: int
    extra_config: str | None
    created_at: datetime
    updated_at: datetime
