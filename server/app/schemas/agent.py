from datetime import datetime

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent name")
    api_key: str = Field(..., description="API key for LLM")


class AgentUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None


class AgentResponse(BaseModel):
    id: int
    name: str
    api_key: str
    created_at: datetime
    updated_at: datetime


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
    subscenes: list["SubsceneResponse"]


class SubsceneCreate(BaseModel):
    name: str = Field(..., description="Subscene name")
    type: str = Field(default="normal", description="Subscene type: start, normal, end")
    state: str = Field(default="inactive", description="Subscene state: active, inactive")
    description: str | None = Field(None, description="Subscene description")
    mandatory: bool = Field(default=False, description="Whether subscene is mandatory")
    objective: str | None = Field(None, description="Subscene objective")
    scene_id: int = Field(..., description="Scene ID")


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
    connections: list["ConnectionResponse"]


class ConnectionCreate(BaseModel):
    name: str = Field(..., description="Connection name")
    condition: str | None = Field(None, description="Connection condition")
    from_subscene: str = Field(..., description="Source subscene name")
    to_subscene: str = Field(..., description="Target subscene name")
    subscene_id: int = Field(..., description="Subscene ID")


class ConnectionUpdate(BaseModel):
    name: str | None = None
    condition: str | None = None


class ConnectionResponse(BaseModel):
    id: int
    name: str
    condition: str | None
    from_subscene: str
    to_subscene: str
    subscene_id: int