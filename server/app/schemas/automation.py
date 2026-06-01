"""API schemas for automation CRUD endpoints."""

from __future__ import annotations

from app.schemas.base import AppBaseModel
from pydantic import Field


class AutomationCreateRequest(AppBaseModel):
    """Request body for creating a new automation."""

    name: str = Field(min_length=1, max_length=200)
    agent_id: int
    prompt_template: str = Field(min_length=1)
    trigger_config: str = Field(
        description='JSON: {"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai"}',
    )
    session_strategy: str = Field(
        default="reuse",
        pattern=r"^(reuse|isolate|this_session)$",
    )
    max_iterations: int | None = Field(default=None)
    timeout_seconds: int = Field(default=300)
    notify_on_completion: bool = Field(default=False)
    notify_on_failure: bool = Field(default=True)
    channel_session_id: int | None = Field(default=None)


class AutomationUpdateRequest(AppBaseModel):
    """Request body for updating an automation.

    All fields are optional; only provided fields are updated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt_template: str | None = Field(default=None, min_length=1)
    trigger_config: str | None = Field(default=None)
    session_strategy: str | None = Field(
        default=None,
        pattern=r"^(reuse|isolate|this_session)$",
    )
    status: str | None = Field(default=None, pattern=r"^(active|paused|disabled)$")
    max_iterations: int | None = Field(default=None)
    timeout_seconds: int | None = Field(default=None)
    notify_on_completion: bool | None = Field(default=None)
    notify_on_failure: bool | None = Field(default=None)


class AutomationResponse(AppBaseModel):
    """Serialized automation returned to the client."""

    id: int
    automation_id: str
    name: str
    agent_id: int
    release_id: int
    trigger_type: str
    trigger_config: str
    prompt_template: str
    session_strategy: str
    status: str
    max_iterations: int | None
    timeout_seconds: int
    notify_on_completion: bool
    notify_on_failure: bool
    channel_session_id: int | None
    channel_key: str | None = None
    channel_name: str | None = None
    channel_logo_url: str | None = None
    last_run_at: str | None
    next_run_at: str | None
    created_at: str
    updated_at: str


class AutomationRunResponse(AppBaseModel):
    """Serialized automation run returned to the client."""

    id: int
    run_id: str
    automation_id: int
    scheduled_at: str
    session_id: int | None
    session_uuid: str | None
    task_id: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    result_summary: str | None
    error_message: str | None
    token_usage: str | None
    delivery_status: str | None
    delivery_error: str | None
