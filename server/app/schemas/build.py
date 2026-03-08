from typing import Any

from app.schemas.base import AppBaseModel


class BuildChatRequest(AppBaseModel):
    session_id: str | None = None
    agent_id: str | None = None  # If provided, load this agent as base
    llm_id: int | None = None  # Required if agent_id is not provided
    content: str  # User requirement


class BuildChatResponse(AppBaseModel):
    session_id: str
    response: str
    reason: str
    updated_agent: dict[str, Any]  # The JSON representation of the agent
