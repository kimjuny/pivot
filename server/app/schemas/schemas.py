from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.agent.base.stream import AgentResponseChunk


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    model_name: str | None = Field(None, description="Model name")
    is_active: bool = Field(default=True, description="Whether agent is active")


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model_name: str | None = None
    is_active: bool | None = None


class AgentResponse(BaseModel):
    id: int
    name: str
    description: str | None
    model_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneCreate(BaseModel):
    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    agent_id: int | None = Field(None, description="Agent ID")


class SceneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SceneResponse(BaseModel):
    id: int
    name: str
    description: str | None
    agent_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SubsceneCreate(BaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(
        default="inactive", description="Subscene state: active, inactive"
    )
    description: str | None = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: str | None = Field(None, description="Subscene objective")


class SubsceneUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    state: str | None = None
    description: str | None = None
    mandatory: bool | None = None
    objective: str | None = None


class SubsceneResponse(BaseModel):
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

    class Config:
        orm_mode = True


class ConnectionCreate(BaseModel):
    name: str = Field(..., description="Connection name")
    condition: str | None = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    from_subscene_id: int | None = Field(None, description="Source subscene ID")
    to_subscene_id: int | None = Field(None, description="Target subscene ID")
    scene_id: int | None = Field(None, description="Scene ID")


class ConnectionUpdate(BaseModel):
    name: str | None = None
    condition: str | None = None
    from_subscene: str | None = None
    to_subscene: str | None = None
    from_subscene_id: int | None = None
    to_subscene_id: int | None = None
    scene_id: int | None = None


class ConnectionResponse(BaseModel):
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

    class Config:
        orm_mode = True


class SubsceneWithConnectionsResponse(BaseModel):
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

    class Config:
        orm_mode = True


class SceneGraphResponse(BaseModel):
    id: int | str
    name: str
    description: str | None
    state: str
    agent_id: int | str
    subscenes: list[SubsceneWithConnectionsResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class AgentDetailResponse(AgentResponse):
    """Agent response with full details including scenes and their graphs."""
    scenes: list[SceneGraphResponse] = []


class ChatHistoryCreate(BaseModel):
    agent_id: int = Field(..., description="Agent ID")
    user: str = Field(..., description="Username of the user")
    role: str = Field(..., description="Role: 'user' or 'agent'")
    message: str = Field(..., description="Message content")
    reason: str | None = Field(None, description="Reason from agent response")
    update_scene: str | None = Field(
        None, description="Updated scene graph in JSON format"
    )


class PreviewChatRequest(BaseModel):
    """Schema for preview chat request."""
    message: str = Field(..., description="User message")
    agent_detail: AgentDetailResponse = Field(..., description="Full agent detail definition")
    current_scene_name: str | None = Field(None, description="Name of the currently active scene")
    current_subscene_name: str | None = Field(None, description="Name of the currently active subscene")


class PreviewChatResponse(BaseModel):
    """Schema for preview chat response."""
    response: str
    reason: str | None
    graph: list[SceneGraphResponse] | None = Field(None, description="Updated scene graph")
    current_scene_name: str | None = Field(None, description="Updated active scene")
    current_subscene_name: str | None = Field(None, description="Updated active subscene")
    create_time: str


class StreamEventType(str, Enum):
    """Enum for SSE stream event types."""
    REASONING = "reasoning"
    REASON = "reason"
    RESPONSE = "response"
    UPDATED_SCENES = "updated_scenes"
    MATCH_CONNECTION = "match_connection"
    ERROR = "error"


class StreamEvent(BaseModel):
    """Schema for SSE stream event data."""
    type: StreamEventType = Field(..., description="Event type: 'reasoning', 'reason', 'response', 'updated_scenes', 'match_connection', 'error'")
    delta: str | None = Field(default=None, description="Incremental content update")
    updated_scenes: list[SceneGraphResponse] | None = Field(default=None, description="Updated scene graph")
    matched_connection: ConnectionResponse | None = Field(default=None, description="Matched connection details")
    error: str | None = Field(default=None, description="Error message")
    create_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Creation timestamp")

    @classmethod
    def from_core_response_chunk(
        cls, 
        chunk: "AgentResponseChunk", 
        create_time: str,
        updated_scenes: list[SceneGraphResponse] | None = None, 
        matched_connection: ConnectionResponse | None = None
    ) -> "StreamEvent":
        """Create a StreamEvent from an AgentResponseChunk.
        
        Args:
            chunk: The AgentResponseChunk from core agent.
            create_time: The creation timestamp for this event.
            updated_scenes: Converted SceneGraphResponse list (required if chunk.type is UPDATED_SCENES).
            matched_connection: Converted ConnectionResponse (required if chunk.type is MATCH_CONNECTION).
        """
        # Note: We use string values for type because AgentResponseChunkType is defined in core,
        # and we want to keep schemas decoupled from core types if possible, or just use the string value.
        # chunk.type is an Enum, so chunk.type.value gives the string.
        
        chunk_type = getattr(chunk, 'type', "")
        chunk_delta = getattr(chunk, 'delta', None)
        
        # Use getattr to safely check for 'value' attribute, assuming it might be an Enum
        type_str = getattr(chunk_type, 'value', str(chunk_type))
        
        # Map core enum values to schema enum values if needed, but they are currently aligned
        
        return cls(
            type=StreamEventType(type_str),
            delta=chunk_delta,
            updated_scenes=updated_scenes,
            matched_connection=matched_connection,
            error=chunk_delta if type_str == "error" else None, # Error chunk stores message in delta
            create_time=create_time
        )


class ChatHistoryResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: str | None
    update_scene: str | None
    create_time: datetime

    class Config:
        orm_mode = True


class ChatHistoryWithGraphResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: str | None
    update_scene: str | None
    create_time: datetime
    graph: dict | None = Field(None, description="Current scene graph")

    class Config:
        orm_mode = True


class SceneGraphUpdate(BaseModel):
    """Schema for bulk updating scene graph data."""

    subscenes: list[dict] = Field(
        ..., description="List of subscenes with their connections"
    )
    agent_id: int | None = Field(None, description="Agent ID")


class ConnectionGraphItem(BaseModel):
    """Schema for a connection within a subscene update."""

    name: str = Field(default="", description="Connection name")
    condition: str | None = Field(None, description="Condition for transition")
    to_subscene: str = Field(..., description="Target subscene name")


class SubsceneGraphItem(BaseModel):
    """Schema for a subscene within a graph update."""

    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Type: start, normal, end")
    state: str = Field(default="inactive", description="State: active, inactive")
    description: str | None = Field(None, description="Description of the subscene")
    mandatory: bool = Field(default=False, description="Is completion mandatory")
    objective: str | None = Field(None, description="Objective of the subscene")
    connections: list[ConnectionGraphItem] = Field(
        default=[], description="Outbound connections"
    )


class SceneWithGraphUpdate(BaseModel):
    """Schema for scene update including nested graph."""

    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    graph: list[SubsceneGraphItem] | None = Field(
        None, description="Scene graph data (subscenes and connections)"
    )


class AgentSceneListUpdate(BaseModel):
    """Schema for bulk updating agent scenes list with optional graph content."""

    scenes: list[SceneWithGraphUpdate] = Field(
        ..., description="List of scenes to update"
    )
