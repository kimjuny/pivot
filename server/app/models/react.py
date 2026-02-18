"""ReAct Agent models for task execution and recursion tracking.

This module defines database models for the ReAct (Reasoning and Acting) agent system,
which implements a recursive state machine for autonomous task execution.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class ReactTask(SQLModel, table=True):
    """Task model representing a single ReAct conversation task.

    Each task corresponds to one user request and contains multiple recursion cycles
    until completion or max iteration is reached.

    Note: session_id is a UUID string reference to Session.session_id for linking
    tasks to sessions. There's no ORM relationship defined to avoid complex join
    conditions. Use service layer to query session by session_id.

    Attributes:
        id: Primary key of the task.
        task_id: UUID string for global unique task identification.
        session_id: UUID string linking to the parent session (optional for backward compatibility).
        agent_id: Foreign key to the agent executing this task.
        user: Username of the user who initiated the task.
        user_message: Original user input message.
        objective: Task objective/goal.
        status: Current status (pending, running, completed, failed).
        iteration: Current number of recursion cycles executed.
        max_iteration: Maximum allowed recursion cycles.
        created_at: UTC timestamp when task was created.
        updated_at: UTC timestamp when task was last updated.
        recursions: List of recursion cycles for this task.
        plan_steps: List of plan steps for this task.
    """

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, unique=True, description="UUID for task")
    session_id: str | None = Field(
        default=None,
        index=True,
        description="UUID for session (optional)",
    )
    agent_id: int = Field(foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Username")
    user_message: str = Field(description="Original user input")
    objective: str = Field(description="Task objective")
    status: str = Field(
        default="pending",
        description="Status: pending, running, completed, failed",
    )
    iteration: int = Field(default=0, description="Current iteration count")
    max_iteration: int = Field(default=30, description="Maximum iterations")
    total_prompt_tokens: int = Field(
        default=0, description="Total prompt tokens consumed by this task"
    )
    total_completion_tokens: int = Field(
        default=0, description="Total completion tokens consumed by this task"
    )
    total_tokens: int = Field(
        default=0, description="Total tokens consumed by this task"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    recursions: list["ReactRecursion"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    plan_steps: list["ReactPlanStep"] = Relationship(
        back_populates="task",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class ReactRecursion(SQLModel, table=True):
    """Recursion model representing a single ReAct recursion cycle.

    Each recursion corresponds to one observe-think-act cycle in the ReAct state machine.

    Attributes:
        id: Primary key of the recursion.
        trace_id: UUID string for unique recursion identification.
        task_id: Foreign key to the parent task (string UUID).
        react_task_id: Foreign key to ReactTask table (integer).
        iteration_index: Index of this recursion in the task (0-based).
        observe: LLM's observation of current state.
        thought: LLM's reasoning/analysis.
        action_type: Type of action (CALL_TOOL, RE_PLAN, ANSWER, REFLECT).
        action_output: JSON string of action output.
        tool_call_results: JSON string of tool execution results.
        short_term_memory: Short-term memory appended in this recursion.
        status: Current status (running, done, error).
        error_log: Error message if any.
        created_at: UTC timestamp when recursion was created.
        updated_at: UTC timestamp when recursion was last updated.
        task: Parent task relationship.
    """

    id: int | None = Field(default=None, primary_key=True)
    trace_id: str = Field(index=True, unique=True, description="UUID for recursion")
    task_id: str = Field(index=True, description="Task UUID")
    react_task_id: int = Field(foreign_key="reacttask.id", index=True)
    iteration_index: int = Field(description="Recursion index in task")
    observe: str | None = Field(default=None, description="LLM observation")
    thought: str | None = Field(default=None, description="LLM reasoning")
    abstract: str | None = Field(
        default=None,
        description="Brief summary of this recursion cycle",
    )
    action_type: str | None = Field(
        default=None,
        description="Action type: CALL_TOOL, RE_PLAN, ANSWER, REFLECT",
    )
    action_output: str | None = Field(
        default=None,
        description="JSON string of action output",
    )
    tool_call_results: str | None = Field(
        default=None,
        description="JSON string of tool results",
    )
    short_term_memory: str | None = Field(
        default=None,
        description="Short-term memory appended in this recursion",
    )
    status: str = Field(default="running", description="Status: running, done, error")
    error_log: str | None = Field(default=None, description="Error message")
    prompt_tokens: int = Field(
        default=0, description="Prompt tokens consumed in this recursion"
    )
    completion_tokens: int = Field(
        default=0, description="Completion tokens consumed in this recursion"
    )
    total_tokens: int = Field(
        default=0, description="Total tokens consumed in this recursion"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Optional["ReactTask"] = Relationship(back_populates="recursions")


class ReactPlanStep(SQLModel, table=True):
    """Plan step model representing a step in the task execution plan.

    Plan steps are generated by the LLM during RE_PLAN action and guide
    subsequent recursion cycles.

    Attributes:
        id: Primary key of the plan step.
        task_id: Foreign key to the parent task (string UUID).
        react_task_id: Foreign key to ReactTask table (integer).
        step_id: Step identifier within the plan.
        description: Description of the step.
        status: Current status (pending, running, done, error).
        created_at: UTC timestamp when step was created.
        updated_at: UTC timestamp when step was last updated.
        task: Parent task relationship.
    """

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, description="Task UUID")
    react_task_id: int = Field(foreign_key="reacttask.id", index=True)
    step_id: str = Field(description="Step identifier")
    description: str = Field(description="Step description")
    status: str = Field(
        default="pending",
        description="Status: pending, running, done, error",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    task: Optional["ReactTask"] = Relationship(back_populates="plan_steps")


class ReactRecursionState(SQLModel, table=True):
    """Recursion state model for persisting complete state machine snapshots.

    Each record stores the complete current_state (as JSON string) for one recursion cycle,
    enabling state recovery, debugging, and historical analysis.

    Attributes:
        id: Primary key of the state record.
        trace_id: UUID of the recursion this state belongs to (foreign key).
        task_id: UUID of the parent task (for easier querying).
        iteration_index: Index of this recursion in the task (denormalized for querying).
        current_state: Complete JSON string of the state machine at this recursion.
                      Structure follows the schema in context_template.md:
                      {
                          "global": {...},
                          "current_recursion": {...},
                          "context": {...},
                          "last_recursion": {...}
                      }
        created_at: UTC timestamp when state was saved.
    """

    id: int | None = Field(default=None, primary_key=True)
    trace_id: str = Field(
        index=True,
        unique=True,
        description="Recursion UUID (one-to-one with ReactRecursion)",
    )
    task_id: str = Field(index=True, description="Task UUID (denormalized)")
    iteration_index: int = Field(
        description="Recursion index in task (denormalized for querying)"
    )
    current_state: str = Field(
        description="Complete JSON snapshot of state machine at this recursion"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
