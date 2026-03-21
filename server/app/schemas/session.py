"""Schemas for Session API requests and responses."""

from typing import Any

from app.schemas.base import AppBaseModel
from app.schemas.file import FileAssetListItem
from pydantic import Field


class SessionCreate(AppBaseModel):
    """Request schema for creating a new session."""

    agent_id: int = Field(..., description="Agent ID for this session")
    user: str = Field(default="default_user", description="Username")


class SessionResponse(AppBaseModel):
    """Response schema for session information."""

    id: int
    session_id: str
    agent_id: int
    user: str
    status: str
    title: str | None = None
    is_pinned: bool = False
    created_at: str
    updated_at: str


class SessionUpdate(AppBaseModel):
    """Request schema for sidebar-driven session metadata updates."""

    title: str | None = None
    is_pinned: bool | None = None


class SessionListItem(AppBaseModel):
    """Schema for session list item (brief info for sidebar)."""

    session_id: str
    agent_id: int
    status: str
    title: str | None = None
    is_pinned: bool = False
    created_at: str
    updated_at: str


class SessionListResponse(AppBaseModel):
    """Response schema for session list."""

    sessions: list[SessionListItem]
    total: int


class ChatHistoryMessage(AppBaseModel):
    """Schema for a single chat history message."""

    type: str
    content: str
    timestamp: str
    files: list[FileAssetListItem] = Field(default_factory=list)


class ChatHistoryResponse(AppBaseModel):
    """Response schema for chat history."""

    version: int
    messages: list[ChatHistoryMessage]


class RecursionDetail(AppBaseModel):
    """Schema for recursion details in full session history."""

    iteration: int
    trace_id: str
    observe: str | None = None
    thinking: str | None = None
    reason: str | None = None
    summary: str | None = None
    action_type: str | None = None
    action_output: str | None = None
    tool_call_results: str | None = None
    status: str
    error_log: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    created_at: str
    updated_at: str


class CurrentPlanRecursionSummary(AppBaseModel):
    """Compact recursion summary attached to one current-plan step."""

    iteration: int | None = None
    summary: str = ""


class CurrentPlanStep(AppBaseModel):
    """Latest visible plan-step state returned with task history."""

    step_id: str
    general_goal: str
    specific_description: str
    completion_criteria: str
    status: str
    recursion_history: list[CurrentPlanRecursionSummary] = Field(default_factory=list)


class TaskMessage(AppBaseModel):
    """Schema for a task message with full recursion details."""

    task_id: str
    user_message: str
    files: list[FileAssetListItem] = Field(default_factory=list)
    agent_answer: str | None = None
    status: str
    total_tokens: int = 0
    skill_selection_result: dict[str, Any] | None = None
    current_plan: list[CurrentPlanStep] = Field(default_factory=list)
    recursions: list[RecursionDetail] = Field(default_factory=list)
    created_at: str
    updated_at: str


class FullSessionHistoryResponse(AppBaseModel):
    """Response schema for full session history with recursion details."""

    session_id: str
    last_event_id: int = 0
    resume_from_event_id: int = 0
    tasks: list[TaskMessage]
