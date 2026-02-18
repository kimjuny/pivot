"""Schemas for Session API requests and responses."""

from typing import Any

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Request schema for creating a new session."""

    agent_id: int = Field(..., description="Agent ID for this session")
    user: str = Field(default="default_user", description="Username")


class SessionResponse(BaseModel):
    """Response schema for session information."""

    id: int
    session_id: str
    agent_id: int
    user: str
    status: str
    subject: dict[str, Any] | None = None
    object: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class SessionMemoryResponse(BaseModel):
    """Response schema for full session memory."""

    session_id: str
    subject: dict[str, Any] | None = None
    object: dict[str, Any] | None = None
    status: str
    artifacts_metadata: dict[str, Any] = Field(default_factory=dict)
    conversations: list[dict[str, Any]] = Field(default_factory=list)
    session_memory: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str


class SessionListItem(BaseModel):
    """Schema for session list item (brief info for sidebar)."""

    session_id: str
    agent_id: int
    status: str
    subject: str | None = None  # Just the subject content string
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionListResponse(BaseModel):
    """Response schema for session list."""

    sessions: list[SessionListItem]
    total: int


class ChatHistoryMessage(BaseModel):
    """Schema for a single chat history message."""

    type: str
    content: str
    timestamp: str


class ChatHistoryResponse(BaseModel):
    """Response schema for chat history."""

    version: int
    messages: list[ChatHistoryMessage]


class RecursionDetail(BaseModel):
    """Schema for recursion details in full session history."""

    iteration: int
    trace_id: str
    observe: str | None = None
    thought: str | None = None
    abstract: str | None = None
    action_type: str | None = None
    action_output: str | None = None
    tool_call_results: str | None = None
    status: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: str
    updated_at: str


class TaskMessage(BaseModel):
    """Schema for a task message with full recursion details."""

    task_id: str
    user_message: str
    agent_answer: str | None = None
    status: str
    total_tokens: int = 0
    recursions: list[RecursionDetail] = Field(default_factory=list)
    created_at: str
    updated_at: str


class FullSessionHistoryResponse(BaseModel):
    """Response schema for full session history with recursion details."""

    session_id: str
    tasks: list[TaskMessage]
