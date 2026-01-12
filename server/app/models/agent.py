from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import datetime


class Agent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: Optional[str] = Field(default=None)
    model_name: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    scenes: List["Scene"] = Relationship(back_populates="agent")


class Scene(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    agent_id: Optional[int] = Field(default=None, foreign_key="agent.id")
    agent: Optional["Agent"] = Relationship(back_populates="scenes")

    subscenes: List["Subscene"] = Relationship(back_populates="scene")


class Subscene(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    type: str = Field(default="normal")
    state: str = Field(default="inactive")
    description: Optional[str] = Field(default=None)
    mandatory: bool = Field(default=False)
    objective: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id")
    scene: Optional["Scene"] = Relationship(back_populates="subscenes")


class Connection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    condition: Optional[str] = Field(default=None)
    from_subscene: str = Field(index=True)
    to_subscene: str = Field(index=True)
    from_subscene_id: Optional[int] = Field(default=None, foreign_key="subscene.id")
    to_subscene_id: Optional[int] = Field(default=None, foreign_key="subscene.id")
    scene_id: Optional[int] = Field(default=None, foreign_key="scene.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatHistory(SQLModel, table=True):
    """
    Chat history for user-agent conversations.
    Stores all messages exchanged between users and agents.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="agent.id", index=True)
    user: str = Field(index=True, description="Username of the user")
    role: str = Field(index=True, description="Role of the message sender: 'user' or 'agent'")
    message: str = Field(default="", description="Message content from user or agent")
    reason: Optional[str] = Field(default=None, description="Reason from agent response")
    update_scene: Optional[str] = Field(default=None, description="Updated scene graph in JSON format")
    create_time: datetime = Field(default_factory=datetime.utcnow, description="Time when the history was created")
