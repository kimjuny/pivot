"""Database models for scheduled automation tasks."""

from datetime import UTC, datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


class Automation(SQLModel, table=True):
    """A user-configured scheduled automation that runs an agent task on a cron schedule.

    Attributes:
        id: Primary key.
        automation_id: UUID for global unique identification.
        name: Human-readable automation name.
        description: Optional description of what this automation does.
        owner_id: User who created and owns this automation.
        agent_id: Published agent this automation talks to.
        release_id: Pinned release snapshot (same as client sessions).
        trigger_type: Trigger mechanism (currently only "cron").
        trigger_config: JSON config for the trigger (e.g. cron expression, timezone).
        prompt_template: Message template sent to the agent each run.
        session_strategy: "reuse" shares one session across runs; "isolate" creates a
            new session per run.
        status: Lifecycle status: active, paused, disabled.
        max_iterations: Optional override for the agent's default max iteration count.
        timeout_seconds: Per-run execution timeout in seconds.
        notify_on_completion: Whether to notify the user on successful runs.
        notify_on_failure: Whether to notify the user on failed runs.
        created_at: UTC timestamp when the automation was created.
        updated_at: UTC timestamp when the automation was last modified.
        last_run_at: UTC timestamp of the most recent run start time.
        next_run_at: UTC timestamp of the next scheduled run.
    """

    __tablename__ = "automation"

    id: int | None = Field(default=None, primary_key=True)
    automation_id: str = Field(
        default_factory=lambda: uuid4().hex,
        unique=True,
        index=True,
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)

    # Ownership
    owner_id: int = Field(foreign_key="user.id", index=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    release_id: int = Field(foreign_key="agentrelease.id", index=True)

    # Trigger
    trigger_type: str = Field(default="cron", max_length=20)
    trigger_config: str = Field(
        default='{"cron": "", "timezone": "UTC"}',
        description='JSON: {"cron": "0 9 * * 1-5", "timezone": "Asia/Shanghai"}',
    )

    # Task template
    prompt_template: str = Field(min_length=1)

    # Session strategy
    session_strategy: str = Field(
        default="reuse",
        max_length=10,
        description='"reuse" shares one session; "isolate" creates new per run',
    )

    # Status
    status: str = Field(
        default="active",
        index=True,
        max_length=10,
        description="active, paused, disabled",
    )

    # Execution settings
    max_iterations: int | None = Field(default=None)
    timeout_seconds: int = Field(default=300)

    # Notification
    notify_on_completion: bool = Field(default=False)
    notify_on_failure: bool = Field(default=True)

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_run_at: datetime | None = Field(default=None)
    next_run_at: datetime | None = Field(default=None, index=True)

    # Relations
    runs: list["AutomationRun"] = Relationship(back_populates="automation")


class AutomationRun(SQLModel, table=True):
    """One execution of an automation, tracking the full lifecycle from claim to result.

    Attributes:
        id: Primary key.
        run_id: UUID for global unique identification.
        automation_id: Parent automation that owns this run.
        scheduled_at: The wall-clock time this run was supposed to fire.
        session_id: The Session created or reused for this run.
        task_id: The ReactTask UUID created by the supervisor.
        status: Execution status: pending, running, completed, failed, timeout, cancelled.
        started_at: UTC timestamp when execution began.
        finished_at: UTC timestamp when execution ended.
        result_summary: Agent's final answer excerpt.
        error_message: Error details if the run failed.
        token_usage: JSON token usage statistics.
    """

    __tablename__ = "automation_run"

    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "scheduled_at",
            name="uq_automation_run_claim",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(
        default_factory=lambda: uuid4().hex,
        unique=True,
        index=True,
    )
    automation_id: int = Field(
        foreign_key="automation.id",
        index=True,
    )
    scheduled_at: datetime = Field(index=True)

    # Execution context
    session_id: int = Field(foreign_key="session.id", index=True)
    task_id: str | None = Field(default=None, index=True)

    # Status
    status: str = Field(
        default="pending",
        index=True,
        max_length=10,
        description="pending, running, completed, failed, timeout, cancelled",
    )
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    # Result
    result_summary: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    token_usage: str | None = Field(
        default=None,
        description='JSON: {"prompt": x, "completion": y}',
    )

    # Relations
    automation: Automation | None = Relationship(back_populates="runs")
