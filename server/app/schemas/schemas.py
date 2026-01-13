from datetime import datetime

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent name")
    description: str | None = Field(None, description="Agent description")
    model_name: str | None = Field(None, description="Model name")
    is_active: bool = Field(default=True, description="Whether agent is active")


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    model_name: str | None = None
    is_active: bool | None = None


class AgentResponse(BaseModel):
    id: int
    name: str
    description: str | None
    model_name: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneCreate(BaseModel):
    name: str = Field(..., description="Scene name")
    description: str | None = Field(None, description="Scene description")
    agent_id: int | None = Field(None, description="Agent ID")


class SceneUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: int | None = None


class SceneResponse(BaseModel):
    id: int
    name: str
    description: str | None
    agent_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SubsceneCreate(BaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(default="inactive", description="Subscene state: active, inactive")
    description: str | None = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: str | None = Field(None, description="Subscene objective")


class SubsceneUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    state: str | None = None
    description: str | None = None
    mandatory: bool | None = None
    objective: str | None = None


class SubsceneResponse(BaseModel):
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

    class Config:
        orm_mode = True


class ConnectionCreate(BaseModel):
    name: str = Field(..., description="Connection name")
    condition: str | None = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    from_subscene_id: int | None = Field(None, description="Source subscene ID")
    to_subscene_id: int | None = Field(None, description="Target subscene ID")
    scene_id: int | None = Field(None, description="Scene ID")


class ConnectionUpdate(BaseModel):
    name: str | None = None
    condition: str | None = None
    from_subscene: str | None = None
    to_subscene: str | None = None
    from_subscene_id: int | None = None
    to_subscene_id: int | None = None
    scene_id: int | None = None


class ConnectionResponse(BaseModel):
    id: int
    name: str
    condition: str | None
    from_subscene: str
    to_subscene: str
    from_subscene_id: int | None
    to_subscene_id: int | None
    scene_id: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SubsceneWithConnectionsResponse(BaseModel):
    id: int | None
    name: str
    type: str
    state: str
    description: str | None
    mandatory: bool
    objective: str | None
    scene_id: int | None
    connections: list[ConnectionResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneGraphResponse(BaseModel):
    id: int
    name: str
    description: str | None
    agent_id: int
    scenes: list[SubsceneWithConnectionsResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ChatHistoryCreate(BaseModel):
    agent_id: int = Field(..., description="Agent ID")
    user: str = Field(..., description="Username of the user")
    role: str = Field(..., description="Role: 'user' or 'agent'")
    message: str = Field(..., description="Message content")
    reason: str | None = Field(None, description="Reason from agent response")
    update_scene: str | None = Field(None, description="Updated scene graph in JSON format")


class ChatHistoryResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: str | None
    update_scene: str | None
    create_time: datetime

    class Config:
        orm_mode = True


class ChatHistoryWithGraphResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: str | None
    update_scene: str | None
    create_time: datetime
    graph: dict | None = Field(None, description="Current scene graph")

    class Config:
        orm_mode = True
