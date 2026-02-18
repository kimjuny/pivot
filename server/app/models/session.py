"""Session models for ReAct agent conversation sessions.

This module defines database models for managing conversation sessions
and their associated memory in the ReAct agent system.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

# Current version for chat_history schema
CHAT_HISTORY_VERSION = 1

# Current version for session_memory schema
SESSION_MEMORY_VERSION = 1


class Session(SQLModel, table=True):
    """Session model representing a conversation session.

    Each session contains multiple tasks (conversations) and maintains
    a shared memory across all tasks within the session.

    Note: Tasks are linked via session_id (UUID string) in ReactTask model,
    but there's no ORM relationship defined here to avoid complex join conditions.
    Use service layer to query tasks by session_id.

    Attributes:
        id: Primary key of the session.
        session_id: UUID string for global unique session identification.
        agent_id: Foreign key to the agent handling this session.
        user: Username of the user who owns this session.
        status: Current status (active, waiting_input, closed).
        subject: JSON string containing session subject info.
        object: JSON string containing session object (purpose) info.
        chat_history: JSON string containing the complete chat history.
        chat_history_version: Version number for chat_history schema.
        created_at: UTC timestamp when session was created.
        updated_at: UTC timestamp when session was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(index=True, unique=True, description="UUID for session")
    agent_id: int = Field(foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Username")
    status: str = Field(
        default="active",
        description="Status: active, waiting_input, closed",
    )
    subject: str | None = Field(
        default=None,
        description="JSON string of session subject",
    )
    object: str | None = Field(
        default=None,
        description="JSON string of session object (purpose)",
    )
    chat_history: str | None = Field(
        default=None,
        description="JSON string of complete chat history",
    )
    chat_history_version: int = Field(
        default=CHAT_HISTORY_VERSION,
        description="Version of chat_history schema",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    memory: Optional["SessionMemory"] = Relationship(back_populates="session")


class SessionMemory(SQLModel, table=True):
    """SessionMemory model for storing persistent session memory.

    This model stores the session_memory array as described in context_template.md,
    including preferences, constraints, background info, capability assumptions,
    and decisions accumulated across all tasks in a session.

    Attributes:
        id: Primary key of the session memory.
        session_id: UUID string linking to the parent session.
        session_db_id: Foreign key to Session table (integer).
        version: Version number for memory schema compatibility.
        memory_items: JSON string containing the session_memory array.
        conversations: JSON string containing conversations summary.
        created_at: UTC timestamp when memory was created.
        updated_at: UTC timestamp when memory was last updated.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(
        index=True,
        unique=True,
        description="Session UUID (one-to-one with Session)",
    )
    session_db_id: int = Field(foreign_key="session.id", index=True)
    version: int = Field(
        default=SESSION_MEMORY_VERSION,
        description="Version of session_memory schema",
    )
    memory_items: str = Field(
        default="[]",
        description="JSON string of session_memory array",
    )
    conversations: str = Field(
        default="[]",
        description="JSON string of conversations summary array",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    session: Optional["Session"] = Relationship(back_populates="memory")


# Import ReactTask here to avoid circular imports
# This will be used for the relationship in ReactTask
