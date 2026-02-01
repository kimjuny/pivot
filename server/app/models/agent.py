from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import PrivateAttr
from sqlmodel import Field, Relationship, SQLModel


class SceneState(Enum):
    """Runtime state of a Scene."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class SubsceneState(Enum):
    """Runtime state of a Subscene."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class SubsceneType(Enum):
    """Type of Subscene in the scene graph."""

    START = "start"
    NORMAL = "normal"
    END = "end"

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

    Supports both database persistence (SQLModel) and runtime operations
    for agent execution. Runtime state is managed via private attributes.

    Attributes:
        id: Primary key of the scene.
        name: Name of the scene.
        description: Optional description of the scene (maps to identification_condition).
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

    # Runtime state (non-persisted)
    _state: SceneState = PrivateAttr(default=SceneState.INACTIVE)

    @property
    def state(self) -> SceneState:
        """Get runtime state of the scene."""
        return self._state

    @property
    def identification_condition(self) -> str:
        """Alias for description, for Core API compatibility."""
        return self.description or ""

    def activate(self) -> None:
        """Set the scene state to active."""
        self._state = SceneState.ACTIVE

    def deactivate(self) -> None:
        """Set the scene state to inactive."""
        self._state = SceneState.INACTIVE

    def add_subscene(self, subscene: "Subscene") -> None:
        """Add a subscene to this scene.

        Args:
            subscene: The subscene to add.
        """
        self.subscenes.append(subscene)

    def to_dict(self) -> dict[str, Any]:
        """Convert scene to dictionary for LLM consumption.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "name": self.name,
            "identification_condition": self.identification_condition,
            "state": self._state.value,
            "subscenes": [ss.to_dict() for ss in self.subscenes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        """Create Scene from dictionary representation.

        Args:
            data: Dictionary containing scene properties.

        Returns:
            New Scene instance with subscenes populated.
        """
        scene = cls(
            name=data.get("name", ""),
            description=data.get("identification_condition", ""),
        )
        scene._state = SceneState(data.get("state", "inactive").lower())

        # Create subscenes from dict data
        if data.get("subscenes"):
            scene.subscenes = [
                Subscene.from_dict(ss_data) for ss_data in data["subscenes"]
            ]
        return scene


class Subscene(SQLModel, table=True):
    """Subscene model representing a step within a scene.

    Supports both database persistence (SQLModel) and runtime operations
    for agent execution. Runtime state is managed via private attributes.

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

    # Runtime connection list (non-persisted, for agent execution)
    _connections: list["Connection"] = PrivateAttr(default_factory=list)

    @property
    def connections(self) -> list["Connection"]:
        """Get list of outgoing connections from this subscene."""
        return self._connections

    @connections.setter
    def connections(self, value: list["Connection"]) -> None:
        """Set list of outgoing connections."""
        self._connections = value

    @property
    def subscene_type(self) -> SubsceneType:
        """Get type as SubsceneType enum (Core API compatible)."""
        return SubsceneType(self.type)

    def activate(self) -> None:
        """Set the subscene state to active."""
        self.state = SubsceneState.ACTIVE.value

    def deactivate(self) -> None:
        """Set the subscene state to inactive."""
        self.state = SubsceneState.INACTIVE.value

    def add_connection(self, connection: "Connection") -> None:
        """Add an outgoing connection from this subscene.

        Args:
            connection: The connection to add.
        """
        self._connections.append(connection)

    def to_dict(self) -> dict[str, Any]:
        """Convert subscene to dictionary for LLM consumption.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "name": self.name,
            "type": self.type,
            "mandatory": self.mandatory,
            "objective": self.objective or "",
            "state": self.state,
            "connections": [conn.to_dict() for conn in self._connections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Subscene":
        """Create Subscene from dictionary representation.

        Args:
            data: Dictionary containing subscene properties.

        Returns:
            New Subscene instance with connections populated.
        """
        subscene = cls(
            name=data.get("name", ""),
            type=data.get("type", "normal"),
            state=data.get("state", "inactive"),
            mandatory=data.get("mandatory", False),
            objective=data.get("objective"),
        )
        # Process connections
        if data.get("connections"):
            subscene._connections = [
                Connection.from_dict(conn_data) for conn_data in data["connections"]
            ]
        return subscene


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

    def to_dict(self) -> dict[str, Any]:
        """Convert connection to dictionary for LLM consumption.

        Returns:
            Dictionary representation suitable for JSON serialization.
        """
        return {
            "name": self.name,
            "from_subscene": self.from_subscene,
            "to_subscene": self.to_subscene,
            "condition": self.condition or "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connection":
        """Create Connection from dictionary representation.

        Args:
            data: Dictionary containing connection properties.

        Returns:
            New Connection instance.
        """
        return cls(
            name=data.get("name", ""),
            from_subscene=data.get("from_subscene", ""),
            to_subscene=data.get("to_subscene", ""),
            condition=data.get("condition"),
        )

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
    role: str = Field(
        index=True, description="Role of the message sender: 'user' or 'agent'"
    )
    message: str = Field(default="", description="Message content from user or agent")
    reason: str | None = Field(default=None, description="Reason from agent response")
    update_scene: str | None = Field(
        default=None, description="Updated scene graph in JSON format"
    )
    create_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Time when the history was created",
    )
