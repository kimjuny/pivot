from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent name")
    description: Optional[str] = Field(None, description="Agent description")
    model_name: Optional[str] = Field(None, description="Model name")
    is_active: bool = Field(default=True, description="Whether agent is active")


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    model_name: Optional[str] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    model_name: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneCreate(BaseModel):
    name: str = Field(..., description="Scene name")
    description: Optional[str] = Field(None, description="Scene description")
    agent_id: Optional[int] = Field(None, description="Agent ID")


class SceneUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[int] = None


class SceneResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    agent_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SubsceneCreate(BaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(default="inactive", description="Subscene state: active, inactive")
    description: Optional[str] = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: Optional[str] = Field(None, description="Subscene objective")


class SubsceneUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    state: Optional[str] = None
    description: Optional[str] = None
    mandatory: Optional[bool] = None
    objective: Optional[str] = None


class SubsceneResponse(BaseModel):
    id: int
    name: str
    type: str
    state: str
    description: Optional[str]
    mandatory: bool
    objective: Optional[str]
    scene_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ConnectionCreate(BaseModel):
    name: str = Field(..., description="Connection name")
    condition: Optional[str] = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    from_subscene_id: Optional[int] = Field(None, description="Source subscene ID")
    to_subscene_id: Optional[int] = Field(None, description="Target subscene ID")
    scene_id: Optional[int] = Field(None, description="Scene ID")


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[str] = None
    from_subscene: Optional[str] = None
    to_subscene: Optional[str] = None
    from_subscene_id: Optional[int] = None
    to_subscene_id: Optional[int] = None
    scene_id: Optional[int] = None


class ConnectionResponse(BaseModel):
    id: int
    name: str
    condition: Optional[str]
    from_subscene: str
    to_subscene: str
    from_subscene_id: Optional[int]
    to_subscene_id: Optional[int]
    scene_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SubsceneWithConnectionsResponse(BaseModel):
    id: int
    name: str
    type: str
    state: str
    description: Optional[str]
    mandatory: bool
    objective: Optional[str]
    scene_id: int
    connections: List[ConnectionResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class SceneGraphResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    agent_id: int
    scenes: List[SubsceneWithConnectionsResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class ChatHistoryCreate(BaseModel):
    agent_id: int = Field(..., description="Agent ID")
    user: str = Field(..., description="Username of the user")
    role: str = Field(..., description="Role: 'user' or 'agent'")
    message: str = Field(..., description="Message content")
    reason: Optional[str] = Field(None, description="Reason from agent response")
    update_scene: Optional[str] = Field(None, description="Updated scene graph in JSON format")


class ChatHistoryResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: Optional[str]
    update_scene: Optional[str]
    create_time: datetime

    class Config:
        orm_mode = True


class ChatHistoryWithGraphResponse(BaseModel):
    id: int
    agent_id: int
    user: str
    role: str
    message: str
    reason: Optional[str]
    update_scene: Optional[str]
    create_time: datetime
    graph: Optional[dict] = Field(None, description="Current scene graph")

    class Config:
        orm_mode = True
