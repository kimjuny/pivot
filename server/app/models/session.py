"""Session models for ReAct agent conversation sessions."""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

# Current version for chat_history schema
CHAT_HISTORY_VERSION = 1


class Session(SQLModel, table=True):
    """Session model representing a conversation session.

    Each session contains multiple tasks (conversations) and maintains
    the runtime prompt window reused across tasks.

    Note: Tasks are linked via session_id (UUID string) in ReactTask model,
    but there's no ORM relationship defined here to avoid complex join conditions.
    Use service layer to query tasks by session_id.

    Attributes:
        id: Primary key of the session.
        session_id: UUID string for global unique session identification.
        agent_id: Foreign key to the agent handling this session.
        type: Whether this session belongs to Consumer or Studio Test.
        release_id: Published release fixed to this session at creation time.
        test_snapshot_id: Frozen Studio working-copy snapshot pinned to this
            session when ``type`` is ``studio_test``.
        user: Username of the user who owns this session.
        status: Current session lifecycle status (active, waiting_input, closed).
        runtime_status: Live aggregate execution state derived from child tasks.
        project_id: Owning project UUID for shared-workspace sessions.
        workspace_id: Owning workspace UUID.
        title: Optional user-facing session label set from the sidebar.
        is_pinned: Whether the session should stay at the top of the sidebar.
        chat_history: JSON string containing the complete chat history.
        chat_history_version: Version number for chat_history schema.
        react_llm_messages: Serialized OpenAI-style message list reused across
            tasks in the same session.
        react_compact_result: Canonical JSON string of the latest compact result
            inserted into the runtime message window.
        react_pending_action_result: Serialized action result injected into the
            next recursion payload while a task is active.
        react_llm_cache_state: Serialized provider-specific cache linkage state.
        created_at: UTC timestamp when session was created.
        updated_at: UTC timestamp when session was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, unique=True, description="UUID for session")
    agent_id: int = Field(foreign_key="agent.id", index=True)
    type: str = Field(
        default="consumer",
        index=True,
        description="Session type: consumer or studio_test",
    )
    release_id: int | None = Field(
        default=None,
        index=True,
        description=(
            "Published release fixed to this session at creation time. "
            "Legacy rows created before release pinning may still be null."
        ),
    )
    test_snapshot_id: int | None = Field(
        default=None,
        index=True,
        description=(
            "Frozen Studio working-copy snapshot pinned to this session. "
            "Consumer sessions keep this field null."
        ),
    )
    user: str = Field(index=True, description="Username")
    status: str = Field(
        default="active",
        description="Status: active, waiting_input, closed",
    )
    runtime_status: str = Field(
        default="idle",
        description="Live runtime status: idle, running, waiting_input",
    )
    project_id: str | None = Field(
        default=None,
        index=True,
        description="Shared project UUID for project-backed sessions",
    )
    workspace_id: str | None = Field(
        default=None,
        index=True,
        description="Owning workspace UUID",
    )
    title: str | None = Field(
        default=None,
        description="Optional user-defined session title",
    )
    is_pinned: bool = Field(
        default=False,
        description="Whether the session is pinned in the sidebar",
    )
    chat_history: str | None = Field(
        default=None,
        description="JSON string of complete chat history",
    )
    chat_history_version: int = Field(
        default=CHAT_HISTORY_VERSION,
        description="Version of chat_history schema",
    )
    react_llm_messages: str = Field(
        default="[]",
        description=(
            "Serialized list[message] reused across tasks in the same session. "
            "Messages are appended incrementally to maximize prompt cache reuse."
        ),
    )
    react_compact_result: str | None = Field(
        default=None,
        description=(
            "Canonical compact JSON currently representing the summarized "
            "session context inside the runtime prompt window."
        ),
    )
    react_pending_action_result: str | None = Field(
        default=None,
        description=(
            "Serialized action result payload to inject into the next recursion "
            "user message while a task is active."
        ),
    )
    react_llm_cache_state: str = Field(
        default="{}",
        description=(
            "Serialized protocol-specific cache state used by LLM transport "
            "(e.g. previous_response_id chaining)."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
