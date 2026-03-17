"""Schemas for ReAct agent API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from app.schemas.base import AppBaseModel
from pydantic import Field


class TokenUsage(AppBaseModel):
    """Token usage information for LLM calls."""

    prompt_tokens: int = Field(..., description="Number of tokens in the prompt")
    completion_tokens: int = Field(
        ..., description="Number of tokens in the completion"
    )
    total_tokens: int = Field(..., description="Total tokens used")
    cached_input_tokens: int = Field(
        default=0,
        description="Number of input tokens served from cache",
    )


class ReactChatRequest(AppBaseModel):
    """Request schema for ReAct chat stream endpoint."""

    agent_id: int = Field(..., description="Agent ID to use for the task")
    message: str = Field(..., description="User message/task description")
    user: str = Field(default="default_user", description="Username")
    task_id: str | None = Field(
        default=None, description="Task ID for resuming a conversation"
    )
    session_id: str | None = Field(
        default=None, description="Session ID for session memory persistence"
    )
    file_ids: list[str] = Field(
        default_factory=list,
        description="Uploaded file IDs to attach to this user turn",
    )


class ReactContextUsageRequest(AppBaseModel):
    """Request schema for estimating current or next-turn ReAct context usage."""

    agent_id: int = Field(..., description="Agent ID used to build the prompt")
    session_id: str | None = Field(
        default=None,
        description="Optional session ID used for session-memory prompt injection",
    )
    task_id: str | None = Field(
        default=None,
        description="Optional active task ID whose runtime messages should be measured",
    )
    draft_message: str = Field(
        default="",
        description="Current unsent composer text to include in the estimate",
    )
    file_ids: list[str] = Field(
        default_factory=list,
        description="Uploaded file IDs whose prompt blocks should be included",
    )


class ReactContextUsageResponse(AppBaseModel):
    """Estimated prompt-context usage for the current composer or task."""

    task_id: str | None = Field(
        default=None,
        description="Task ID used for estimation when measuring an active task",
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID used for session-memory lookup",
    )
    estimation_mode: str = Field(
        ...,
        description=(
            "Estimation mode such as next_turn_preview, active_task, or reply_preview"
        ),
    )
    message_count: int = Field(
        ...,
        description="Number of messages included in the estimated prompt",
    )
    session_message_count: int = Field(
        ...,
        description="Number of persisted session-runtime messages before preview additions",
    )
    used_tokens: int = Field(
        ...,
        description="Estimated prompt tokens currently occupied",
    )
    remaining_tokens: int = Field(
        ...,
        description="Estimated prompt tokens remaining before max context",
    )
    max_context_tokens: int = Field(
        ...,
        description="Maximum context window declared by the configured LLM",
    )
    used_percent: int = Field(
        ...,
        description="Rounded percentage of the context window currently used",
    )
    remaining_percent: int = Field(
        ...,
        description="Rounded percentage of the context window remaining",
    )
    system_tokens: int = Field(
        ...,
        description="Estimated tokens contributed by the system prompt",
    )
    conversation_tokens: int = Field(
        ...,
        description="Estimated tokens contributed by non-system messages",
    )
    session_tokens: int = Field(
        ...,
        description="Estimated tokens already occupied by persisted session-runtime messages",
    )
    preview_tokens: int = Field(
        ...,
        description="Estimated tokens added by the current unsent preview over the persisted session state",
    )
    bootstrap_tokens: int = Field(
        ...,
        description="Estimated tokens contributed by the once-per-task user_prompt bootstrap message",
    )
    draft_tokens: int = Field(
        ...,
        description="Estimated tokens contributed by the unsent draft turn",
    )
    includes_task_bootstrap: bool = Field(
        ...,
        description="Whether the estimate includes a once-per-task user_prompt bootstrap message",
    )


class ReactStreamEventType(str, Enum):
    """Types of events in ReAct stream."""

    RECURSION_START = "recursion_start"
    REASONING = "reasoning"
    OBSERVE = "observe"
    THOUGHT = "thought"
    ABSTRACT = "abstract"
    SUMMARY = "summary"
    ACTION = "action"
    TOOL_CALL = "tool_call"
    SKILL_RESOLUTION_START = "skill_resolution_start"
    SKILL_RESOLUTION_RESULT = "skill_resolution_result"
    TOKEN_RATE = "token_rate"
    TOOL_RESULT = "tool_result"
    PLAN_UPDATE = "plan_update"
    REFLECT = "reflect"
    ANSWER = "answer"
    CLARIFY = "clarify"
    TASK_CANCELLED = "task_cancelled"
    ERROR = "error"
    TASK_COMPLETE = "task_complete"


class ReactStreamEvent(AppBaseModel):
    """Stream event schema for ReAct execution updates."""

    event_id: int | None = Field(
        default=None,
        description="Stable incremental cursor for reconnectable subscribers",
    )
    type: ReactStreamEventType = Field(..., description="Event type")
    task_id: str = Field(..., description="Task UUID")
    trace_id: str | None = Field(default=None, description="Current recursion trace ID")
    iteration: int = Field(..., description="Current iteration index")
    delta: str | None = Field(default=None, description="Incremental text content")
    data: dict[str, Any] | None = Field(
        default=None, description="Additional event data"
    )
    timestamp: datetime = Field(..., description="Event timestamp")
    created_at: str | None = Field(
        default=None, description="Recursion creation timestamp (ISO format)"
    )
    updated_at: str | None = Field(
        default=None, description="Recursion update timestamp (ISO format)"
    )
    tokens: TokenUsage | None = Field(
        default=None, description="Token usage for this recursion"
    )
    total_tokens: TokenUsage | None = Field(
        default=None, description="Total token usage for the task"
    )


class ReactTaskResponse(AppBaseModel):
    """Response schema for ReAct task information."""

    id: int
    task_id: str
    agent_id: int
    user: str
    user_message: str
    user_intent: str
    status: str
    iteration: int
    max_iteration: int
    created_at: datetime
    updated_at: datetime


class ReactTaskStartResponse(AppBaseModel):
    """Response schema returned when a task has been queued for execution."""

    task_id: str = Field(..., description="Task UUID")
    session_id: str | None = Field(
        default=None,
        description="Owning session UUID when the task is session-backed",
    )
    status: str = Field(..., description="Current task status after enqueueing")
    cursor_before_start: int = Field(
        default=0,
        description="Latest session event cursor before this launch began",
    )


class ReactTaskCancelResponse(AppBaseModel):
    """Response schema returned after a cancellation request."""

    task_id: str = Field(..., description="Task UUID")
    status: str = Field(..., description="Current task status")
    cancel_requested: bool = Field(
        ...,
        description="Whether an active execution acknowledged the cancel request",
    )


class ReactRecursionResponse(AppBaseModel):
    """Response schema for ReAct recursion information."""

    id: int
    trace_id: str
    task_id: str
    iteration_index: int
    observe: str | None
    thinking: str | None
    thought: str | None
    abstract: str | None
    summary: str | None
    action_type: str | None
    action_output: str | None
    tool_call_results: str | None
    status: str
    error_log: str | None
    created_at: datetime
    updated_at: datetime


class ReactPlanStepResponse(AppBaseModel):
    """Response schema for ReAct plan step information."""

    id: int
    task_id: str
    step_id: str
    general_goal: str
    specific_description: str
    completion_criteria: str
    status: str
    created_at: datetime
    updated_at: datetime
