"""Schemas for Session API requests and responses."""

from typing import Any, Literal

from app.schemas.base import AppBaseModel
from app.schemas.file import FileAssetListItem
from app.schemas.task_attachment import TaskAttachmentListItem
from pydantic import Field


class StudioTestSnapshotConnectionPayload(AppBaseModel):
    """Normalized connection payload accepted for Studio test snapshots."""

    id: int | str | None = None
    name: str
    condition: str | None = None
    from_subscene: str
    to_subscene: str


class StudioTestSnapshotSubscenePayload(AppBaseModel):
    """Normalized subscene payload accepted for Studio test snapshots."""

    id: int | str | None = None
    name: str
    type: str = "normal"
    state: str = "inactive"
    description: str | None = None
    mandatory: bool = False
    objective: str | None = None
    connections: list[StudioTestSnapshotConnectionPayload] = Field(default_factory=list)


class StudioTestSnapshotScenePayload(AppBaseModel):
    """Normalized scene payload accepted for Studio test snapshots."""

    id: int | str | None = None
    name: str
    description: str | None = None
    subscenes: list[StudioTestSnapshotSubscenePayload] = Field(default_factory=list)


class StudioTestSnapshotAgentPayload(AppBaseModel):
    """Runtime-facing agent payload accepted for Studio test snapshots."""

    name: str
    description: str | None = None
    llm_id: int | None = None
    skill_resolution_llm_id: int | None = None
    session_idle_timeout_minutes: int = Field(default=15, ge=1)
    sandbox_timeout_seconds: int = Field(default=60, ge=1)
    compact_threshold_percent: int = Field(default=60, ge=1, le=100)
    is_active: bool = True
    max_iteration: int = Field(default=30, ge=1)
    tool_ids: list[str] | None = None
    skill_ids: list[str] | None = None


class StudioTestSnapshotPayload(AppBaseModel):
    """Minimal working-copy snapshot sent from Studio into Test."""

    schema_version: int = 1
    agent: StudioTestSnapshotAgentPayload
    scenes: list[StudioTestSnapshotScenePayload] = Field(default_factory=list)


class SessionCreate(AppBaseModel):
    """Request schema for creating a new session."""

    agent_id: int = Field(..., description="Agent ID for this session")
    user: str = Field(default="default_user", description="Username")
    type: Literal["consumer", "studio_test"] = Field(
        default="consumer",
        description="Whether the session belongs to Consumer or Studio Test",
    )
    test_snapshot: StudioTestSnapshotPayload | None = Field(
        default=None,
        description="Frozen Studio working-copy snapshot used for studio_test sessions",
    )


class SessionResponse(AppBaseModel):
    """Response schema for session information."""

    id: int
    session_id: str
    agent_id: int
    type: Literal["consumer", "studio_test"]
    release_id: int | None
    test_workspace_hash: str | None = None
    user: str
    status: str
    runtime_status: str = "idle"
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
    type: Literal["consumer", "studio_test"]
    release_id: int | None
    test_workspace_hash: str | None = None
    status: str
    runtime_status: str = "idle"
    title: str | None = None
    is_pinned: bool = False
    created_at: str
    updated_at: str


class SessionListResponse(AppBaseModel):
    """Response schema for session list."""

    sessions: list[SessionListItem]
    total: int


class ConsumerSessionListItem(SessionListItem):
    """Session list item enriched with Consumer-facing agent metadata."""

    agent_name: str
    agent_description: str | None = None


class ConsumerSessionListResponse(AppBaseModel):
    """Response schema for Consumer recent session listings."""

    sessions: list[ConsumerSessionListItem]
    total: int


class ChatHistoryMessage(AppBaseModel):
    """Schema for a single chat history message."""

    type: str
    content: str
    timestamp: str
    files: list[FileAssetListItem] = Field(default_factory=list)
    attachments: list[TaskAttachmentListItem] = Field(default_factory=list)


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


class SkillChangeApprovalRequestPayload(AppBaseModel):
    """Structured skill approval request embedded in one waiting action."""

    submission_id: int
    skill_name: str
    change_type: str
    question: str
    message: str = ""
    file_count: int = 0
    total_bytes: int = 0


class PendingUserActionPayload(AppBaseModel):
    """System-owned waiting action persisted on a task."""

    kind: str
    approval_request: SkillChangeApprovalRequestPayload | None = None


class TaskMessage(AppBaseModel):
    """Schema for a task message with full recursion details."""

    task_id: str
    user_message: str
    files: list[FileAssetListItem] = Field(default_factory=list)
    assistant_attachments: list[TaskAttachmentListItem] = Field(default_factory=list)
    agent_answer: str | None = None
    status: str
    total_tokens: int = 0
    skill_selection_result: dict[str, Any] | None = None
    pending_user_action: PendingUserActionPayload | None = None
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
