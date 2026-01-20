from datetime import datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


class BuildSession(SQLModel, table=True):
    """
    Session for building/modifying an agent via chat.
    """

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Optional: Link to user or target agent if needed in future
    # user_id: str | None = None
    # target_agent_id: str | None = None


class BuildHistory(SQLModel, table=True):
    """
    Chat history within a build session.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="buildsession.id", index=True)
    role: str  # "user" or "assistant"
    content: str  # The text content (User requirement or Assistant response)

    # Store the agent state snapshot at this point (JSON string)
    # Only relevant for assistant messages where a new agent version was generated
    agent_snapshot: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
