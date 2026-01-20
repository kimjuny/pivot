from typing import Any

from pydantic import BaseModel


class BuildChatRequest(BaseModel):
    session_id: str | None = None
    agent_id: str | None = None  # If provided, load this agent as base
    content: str  # User requirement


class BuildChatResponse(BaseModel):
    session_id: str
    response: str
    reason: str
    updated_agent: dict[str, Any]  # The JSON representation of the agent
