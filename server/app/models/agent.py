from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


class Agent(SQLModel, table=True):
    """Agent model representing an AI agent configuration.

    Attributes:
        id: Primary key of the agent.
        name: Unique name of the agent.
        description: Optional description of the agent's purpose.
        model_name: Name of the LLM model to use.
        is_active: Whether the agent is currently active.
        created_at: UTC timestamp when the agent was created.
        updated_at: UTC timestamp when the agent was last updated.
        scenes: List of scenes associated with this agent.
    """
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = Field(default=None)
    model_name: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenes: list["Scene"] = Relationship(back_populates="agent")


class Scene(SQLModel, table=True):
    """Scene model representing a scene in an agent's workflow.

    Attributes:
        id: Primary key of the scene.
        name: Name of the scene.
        description: Optional description of the scene.
        created_at: UTC timestamp when the scene was created.
        updated_at: UTC timestamp when the scene was last updated.
        agent_id: Foreign key to the agent that owns this scene.
        agent: The agent that owns this scene.
        subscenes: List of subscenes within this scene.
    """
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: int | None = Field(default=None, foreign_key="agent.id")
    agent: Optional["Agent"] = Relationship(back_populates="scenes")
    subscenes: list["Subscene"] = Relationship(back_populates="scene")


class Subscene(SQLModel, table=True):
    """Subscene model representing a step within a scene.

    Attributes:
        id: Primary key of the subscene.
        name: Name of the subscene.
        type: Type of subscene (start, normal, end).
        state: Current state of the subscene (active, inactive).
        description: Optional description of the subscene.
        mandatory: Whether this subscene must be completed.
        objective: Optional objective of this subscene.
        created_at: UTC timestamp when the subscene was created.
        updated_at: UTC timestamp when the subscene was last updated.
        scene_id: Foreign key to the scene that contains this subscene.
        scene: The scene that contains this subscene.
    """
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str = Field(default="normal")
    state: str = Field(default="inactive")
    description: str | None = Field(default=None)
    mandatory: bool = Field(default=False)
    objective: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scene_id: int | None = Field(default=None, foreign_key="scene.id")
    scene: Optional["Scene"] = Relationship(back_populates="subscenes")


class Connection(SQLModel, table=True):
    """Connection model representing a transition between subscenes.

    Attributes:
        id: Primary key of the connection.
        name: Name of the connection.
        condition: Optional condition for this connection to be valid.
        from_subscene: Name of the source subscene.
        to_subscene: Name of the target subscene.
        from_subscene_id: Foreign key to the source subscene.
        to_subscene_id: Foreign key to the target subscene.
        scene_id: Foreign key to the scene this connection belongs to.
        created_at: UTC timestamp when the connection was created.
        updated_at: UTC timestamp when the connection was last updated.
    """
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    condition: str | None = Field(default=None)
    from_subscene: str = Field(index=True)
    to_subscene: str = Field(index=True)
    from_subscene_id: int | None = Field(default=None, foreign_key="subscene.id")
    to_subscene_id: int | None = Field(default=None, foreign_key="subscene.id")
    scene_id: int | None = Field(default=None, foreign_key="scene.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatHistory(SQLModel, table=True):
    """Chat history for user-agent conversations.

    Stores all messages exchanged between users and agents,
    including the agent's reasoning and scene graph updates.

    Attributes:
        id: Primary key of the chat history entry.
        agent_id: Foreign key to the agent.
        user: Username of the user.
        role: Role of the message sender ('user' or 'agent').
        message: Message content from user or agent.
        reason: Reason from agent response.
        update_scene: Updated scene graph in JSON format.
        create_time: UTC timestamp when the history was created.
    """
    id: int | None = Field(default=None, primary_key=True)
    agent_id: int | None = Field(default=None, foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Username of the user")
    role: str = Field(index=True, description="Role of the message sender: 'user' or 'agent'")
    message: str = Field(default="", description="Message content from user or agent")
    reason: str | None = Field(default=None, description="Reason from agent response")
    update_scene: str | None = Field(default=None, description="Updated scene graph in JSON format")
    create_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Time when the history was created")
