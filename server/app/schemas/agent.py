from datetime import datetime

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    """Schema for creating a new agent.

    Attributes:
        name: Name of the agent.
        api_key: API key for LLM.
    """
    name: str = Field(..., description="Agent name")
    api_key: str = Field(..., description="API key for LLM")


class AgentUpdate(BaseModel):
    """Schema for updating an existing agent.

    All fields are optional to allow partial updates.

    Attributes:
        name: New name of the agent.
        api_key: New API key for LLM.
    """
    name: str | None = None
    api_key: str | None = None


class AgentResponse(BaseModel):
    """Schema for agent response.

    Attributes:
        id: Primary key of the agent.
        name: Name of the agent.
        api_key: API key for LLM.
        created_at: UTC timestamp when the agent was created.
        updated_at: UTC timestamp when the agent was last updated.
    """
    id: int
    name: str
    api_key: str
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneCreate(BaseModel):
    """Schema for creating a new scene.

    Attributes:
        name: Name of the scene.
        description: Optional description of the scene.
        agent_id: Optional ID of the agent this scene belongs to.
    """
    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    agent_id: int | None = Field(None, description="Agent ID")


class SceneUpdate(BaseModel):
    """Schema for updating an existing scene.

    All fields are optional to allow partial updates.

    Attributes:
        name: New name of the scene.
        description: New description of the scene.
        agent_id: New agent ID.
    """
    name: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SceneResponse(BaseModel):
    """Schema for scene response.

    Attributes:
        id: Primary key of the scene.
        name: Name of the scene.
        description: Description of the scene.
        agent_id: ID of the agent this scene belongs to.
        created_at: UTC timestamp when the scene was created.
        updated_at: UTC timestamp when the scene was last updated.
        subscenes: List of subscenes belonging to this scene.
    """
    id: int
    name: str
    description: str | None
    agent_id: int | None
    created_at: datetime
    updated_at: datetime
    subscenes: list["SubsceneResponse"]

    class Config:
        orm_mode = True


class SubsceneCreate(BaseModel):
    """Schema for creating a new subscene.

    Attributes:
        name: Name of the subscene.
        type: Type of subscene (start, normal, end).
        state: State of subscene (active, inactive).
        description: Optional description of the subscene.
        mandatory: Whether this subscene must be completed.
        objective: Optional objective of this subscene.
        scene_id: ID of the scene this subscene belongs to.
    """
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(default="inactive", description="Subscene state: active, inactive")
    description: str | None = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: str | None = Field(None, description="Subscene objective")
    scene_id: int = Field(..., description="Scene ID")


class SubsceneUpdate(BaseModel):
    """Schema for updating an existing subscene.

    All fields are optional to allow partial updates.

    Attributes:
        name: New name of the subscene.
        type: New type of subscene.
        state: New state of subscene.
        description: New description of the subscene.
        mandatory: New mandatory status.
        objective: New objective of this subscene.
    """
    name: str | None = None
    type: str | None = None
    state: str | None = None
    description: str | None = None
    mandatory: bool | None = None
    objective: str | None = None


class SubsceneResponse(BaseModel):
    """Schema for subscene response.

    Attributes:
        id: Primary key of the subscene.
        name: Name of the subscene.
        type: Type of subscene.
        state: State of subscene.
        description: Description of the subscene.
        mandatory: Whether this subscene is mandatory.
        objective: Objective of this subscene.
        scene_id: ID of the scene this subscene belongs to.
        created_at: UTC timestamp when the subscene was created.
        updated_at: UTC timestamp when the subscene was last updated.
        connections: List of connections from this subscene.
    """
    id: int
    name: str
    type: str
    state: str
    description: str | None
    mandatory: bool
    objective: str | None
    scene_id: int
    created_at: datetime
    updated_at: datetime
    connections: list["ConnectionResponse"]

    class Config:
        orm_mode = True


class ConnectionCreate(BaseModel):
    """Schema for creating a new connection.

    Attributes:
        name: Name of the connection.
        condition: Optional condition for this connection.
        from_subscene: Name of the source subscene.
        to_subscene: Name of the target subscene.
        subscene_id: ID of the subscene this connection belongs to.
    """
    name: str = Field(..., description="Connection name")
    condition: str | None = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    subscene_id: int = Field(..., description="Subscene ID")


class ConnectionUpdate(BaseModel):
    """Schema for updating an existing connection.

    All fields are optional to allow partial updates.

    Attributes:
        name: New name of the connection.
        condition: New condition for this connection.
    """
    name: str | None = None
    condition: str | None = None


class ConnectionResponse(BaseModel):
    """Schema for connection response.

    Attributes:
        id: Primary key of the connection.
        name: Name of the connection.
        condition: Condition for this connection.
        from_subscene: Name of the source subscene.
        to_subscene: Name of the target subscene.
        subscene_id: ID of the subscene this connection belongs to.
        created_at: UTC timestamp when the connection was created.
        updated_at: UTC timestamp when the connection was last updated.
    """
    id: int
    name: str
    condition: str | None
    from_subscene: str
    to_subscene: str
    subscene_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
