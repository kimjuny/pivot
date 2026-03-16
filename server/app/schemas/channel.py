"""Schemas for channel catalog, bindings, and linking APIs."""

from __future__ import annotations

from typing import Any

from app.schemas.base import AppBaseModel
from pydantic import Field


class ChannelBindingCreate(AppBaseModel):
    """Payload used to create a new agent channel binding."""

    channel_key: str = Field(..., description="Stable provider key")
    name: str = Field(..., description="User-facing binding alias")
    enabled: bool = Field(default=True, description="Whether the binding is active")
    auth_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider auth config collected from the generated form",
    )
    runtime_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider runtime config collected from the generated form",
    )


class ChannelBindingUpdate(AppBaseModel):
    """Payload used to update an existing channel binding."""

    name: str | None = None
    enabled: bool | None = None
    auth_config: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None


class ChannelBindingTestRequest(AppBaseModel):
    """Payload used to validate one unsaved channel binding draft."""

    auth_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider auth config collected from the generated form",
    )
    runtime_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider runtime config collected from the generated form",
    )


class ChannelBindingResponse(AppBaseModel):
    """Serialized agent channel binding with manifest and setup details."""

    id: int
    agent_id: int
    channel_key: str
    name: str
    enabled: bool
    auth_config: dict[str, Any]
    runtime_config: dict[str, Any]
    manifest: dict[str, Any]
    endpoint_infos: list[dict[str, Any]]
    last_health_status: str | None
    last_health_message: str | None
    last_health_check_at: str | None
    created_at: str
    updated_at: str


class ChannelCatalogItemResponse(AppBaseModel):
    """One channel catalog item exposed to the frontend."""

    manifest: dict[str, Any]


class ChannelTestResponse(AppBaseModel):
    """Health-check response for one channel binding."""

    result: dict[str, Any]


class ChannelLinkTokenResponse(AppBaseModel):
    """Short-lived link token payload returned after an inbound unauthenticated event."""

    token: str
    link_url: str
    expires_at: str


class ChannelLinkTokenStatusResponse(AppBaseModel):
    """Public metadata for one channel link token."""

    token: str
    status: str
    provider_name: str
    binding_name: str
    agent_id: int
    external_user_id: str
    external_conversation_id: str | None
    expires_at: str
    used_at: str | None


class ChannelLinkCompletionResponse(AppBaseModel):
    """Authenticated response after completing one external identity binding."""

    status: str
    message: str
    pivot_user_id: int
    workspace_owner: str
    linked_at: str
