from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent name")
    api_key: str = Field(..., description="API key for LLM")


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    api_key: Optional[str] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    api_key: str
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
    subscenes: list["SubsceneResponse"]

    class Config:
        orm_mode = True


class SubsceneCreate(BaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(default="inactive", description="Subscene state: active, inactive")
    description: Optional[str] = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: Optional[str] = Field(None, description="Subscene objective")
    scene_id: int = Field(..., description="Scene ID")


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
    connections: list["ConnectionResponse"]

    class Config:
        orm_mode = True


class ConnectionCreate(BaseModel):
    name: str = Field(..., description="Connection name")
    condition: Optional[str] = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    subscene_id: int = Field(..., description="Subscene ID")


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[str] = None


class ConnectionResponse(BaseModel):
    id: int
    name: str
    condition: Optional[str]
    from_subscene: str
    to_subscene: str
    subscene_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
