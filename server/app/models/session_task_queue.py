"""Database model for serializing tasks on shared sessions."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


class SessionTaskQueue(SQLModel, table=True):
    """A queued task waiting to execute on a session.

    Decouples *who wants to run* from *when execution happens*. When a
    session already has an active ReactTask, new work (e.g. an automation
    run) is enqueued here and consumed once the session becomes idle.

    Attributes:
        id: Primary key.
        queue_id: UUID for global unique identification.
        session_id: Pivot session UUID (matches ``ReactTask.session_id``).
        prompt: The rendered prompt to execute when dequeued.
        queue_type: ``"wait_for_completion"`` waits for the current task;
            ``"immediate_insert"`` injects into the running task (future).
        source: ``"automation"`` or ``"user_input"`` — determines priority.
        source_ref_id: Optional FK to the originating record (e.g.
            ``AutomationRun.id``).
        status: ``"pending"`` | ``"processing"`` | ``"completed"`` |
            ``"cancelled"`` | ``"failed"``.
        created_at: UTC timestamp when the item was enqueued.
        started_at: UTC timestamp when processing began.
        finished_at: UTC timestamp when processing ended.
    """

    __tablename__ = "session_task_queue"

    id: int | None = Field(default=None, primary_key=True)
    queue_id: str = Field(
        default_factory=lambda: uuid4().hex,
        unique=True,
        index=True,
    )

    # Target
    session_id: str = Field(index=True)
    prompt: str

    # Classification
    queue_type: str = Field(
        index=True,
        description='"wait_for_completion" | "immediate_insert"',
    )
    source: str = Field(
        index=True,
        description='"automation" | "user_input" — determines dequeue priority',
    )
    source_ref_id: int | None = Field(
        default=None,
        foreign_key="automation_run.id",
    )

    # Lifecycle
    status: str = Field(
        default="pending",
        index=True,
        max_length=20,
        description="pending | processing | completed | cancelled | failed",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
