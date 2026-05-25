"""Request/response schemas for agent delegation endpoints."""

from datetime import datetime

from app.schemas.base import AppBaseModel
from pydantic import Field


class DelegationCreate(AppBaseModel):
    """Schema for creating a new delegation."""

    callee_agent_id: int = Field(..., description="ID of the agent to delegate to")
    callee_alias: str = Field(
        ..., description="Short identifier for the callee in tool calls"
    )
    pass_mode: str = Field(
        default="instruction_only",
        description="instruction_only | with_context",
    )
    max_timeout_seconds: int = Field(
        default=300, description="Max wall-clock seconds for the delegated task"
    )
    max_iterations_override: int | None = Field(
        None,
        description="Override callee's max_iteration for delegated calls",
    )
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)


class DelegationUpdate(AppBaseModel):
    """Schema for updating an existing delegation."""

    callee_alias: str | None = None
    pass_mode: str | None = None
    max_timeout_seconds: int | None = None
    max_iterations_override: int | None = None
    enabled: bool | None = None
    priority: int | None = None


class DelegationResponse(AppBaseModel):
    """Schema for returning a delegation in API responses."""

    id: int
    caller_agent_id: int
    callee_agent_id: int
    callee_alias: str
    pass_mode: str
    max_timeout_seconds: int
    max_iterations_override: int | None
    enabled: bool
    priority: int
    created_at: datetime
    updated_at: datetime
    # Joined from the callee agent for convenience
    callee_name: str | None = None
    callee_description: str | None = None
    callee_llm_id: int | None = None
    callee_model_name: str | None = None


class DelegationReplaceItem(AppBaseModel):
    """One item in a batch replace request."""

    callee_agent_id: int
    callee_alias: str
    pass_mode: str = "instruction_only"
    max_timeout_seconds: int = 300
    max_iterations_override: int | None = None
    enabled: bool = True
    priority: int = 100


class DelegationReplaceRequest(AppBaseModel):
    """Schema for batch-replacing all delegations of an agent."""

    delegations: list[DelegationReplaceItem]
