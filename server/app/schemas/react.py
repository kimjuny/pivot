"""Schemas for ReAct agent API requests and responses."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ReactChatRequest(BaseModel):
    """Request schema for ReAct chat stream endpoint."""

    agent_id: int = Field(..., description="Agent ID to use for the task")
    message: str = Field(..., description="User message/task description")
    user: str = Field(default="default_user", description="Username")


class ReactStreamEventType(str, Enum):
    """Types of events in ReAct stream."""

    RECURSION_START = "recursion_start"
    OBSERVE = "observe"
    THOUGHT = "thought"
    ABSTRACT = "abstract"
    ACTION = "action"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PLAN_UPDATE = "plan_update"
    ANSWER = "answer"
    ERROR = "error"
    TASK_COMPLETE = "task_complete"


class ReactStreamEvent(BaseModel):
    """Stream event schema for ReAct execution updates."""

    type: ReactStreamEventType = Field(..., description="Event type")
    task_id: str = Field(..., description="Task UUID")
    trace_id: str | None = Field(None, description="Current recursion trace ID")
    iteration: int = Field(..., description="Current iteration index")
    delta: str | None = Field(None, description="Incremental text content")
    data: dict[str, Any] | None = Field(None, description="Additional event data")
    timestamp: datetime = Field(..., description="Event timestamp")


class ReactTaskResponse(BaseModel):
    """Response schema for ReAct task information."""

    id: int
    task_id: str
    agent_id: int
    user: str
    user_message: str
    objective: str
    status: str
    iteration: int
    max_iteration: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ReactRecursionResponse(BaseModel):
    """Response schema for ReAct recursion information."""

    id: int
    trace_id: str
    task_id: str
    iteration_index: int
    observe: str | None
    thought: str | None
    abstract: str | None
    action_type: str | None
    action_output: str | None
    tool_call_results: str | None
    status: str
    error_log: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ReactPlanStepResponse(BaseModel):
    """Response schema for ReAct plan step information."""

    id: int
    task_id: str
    step_id: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
