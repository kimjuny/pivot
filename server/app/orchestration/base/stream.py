from enum import Enum

from app.schemas.base import AppBaseModel
from pydantic import ConfigDict


class AgentResponseChunkType(str, Enum):
    """Enum for agent response chunk types."""

    REASONING = "reasoning"
    REASON = "reason"
    RESPONSE = "response"
    ERROR = "error"
    PARSING = "parsing"  # Internal state, not usually yielded but good to have


class AgentResponseChunk(AppBaseModel):
    """
    Chunk of response from the agent in streaming mode.
    """

    type: AgentResponseChunkType
    delta: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
        arbitrary_types_allowed=True,
    )
