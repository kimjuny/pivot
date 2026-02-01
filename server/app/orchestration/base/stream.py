from enum import Enum

from app.models.agent import Connection, Scene
from pydantic import BaseModel


class AgentResponseChunkType(str, Enum):
    """Enum for agent response chunk types."""
    REASONING = "reasoning"
    REASON = "reason"
    RESPONSE = "response"
    UPDATED_SCENES = "updated_scenes"
    MATCH_CONNECTION = "match_connection"
    ERROR = "error"
    PARSING = "parsing"  # Internal state, not usually yielded but good to have


class AgentResponseChunk(BaseModel):
    """
    Chunk of response from the agent in streaming mode.
    """
    type: AgentResponseChunkType
    delta: str | None = None
    updated_scenes: list[Scene] | None = None
    matched_connection: Connection | None = None

    class Config:
        arbitrary_types_allowed = True
