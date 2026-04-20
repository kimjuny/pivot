"""Schemas for web-search provider catalog and agent bindings."""

from __future__ import annotations

from typing import Any

from app.schemas.base import AppBaseModel
from pydantic import Field


class WebSearchBindingCreate(AppBaseModel):
    """Payload used to create a new agent web-search provider binding."""

    provider_key: str = Field(..., description="Stable provider key")
    enabled: bool = Field(default=True, description="Whether the provider is active")
    auth_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider auth config collected from the generated form",
    )
    runtime_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider runtime config collected from the generated form",
    )


class WebSearchBindingUpdate(AppBaseModel):
    """Payload used to update an existing agent web-search provider binding."""

    enabled: bool | None = None
    auth_config: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None


class WebSearchBindingTestRequest(AppBaseModel):
    """Payload used to validate one unsaved web-search provider draft."""

    auth_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider auth config collected from the generated form",
    )
    runtime_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider runtime config collected from the generated form",
    )


class WebSearchBindingResponse(AppBaseModel):
    """Serialized web-search provider binding with manifest metadata."""

    id: int
    agent_id: int
    provider_key: str
    enabled: bool
    effective_enabled: bool = True
    disabled_reason: str | None = None
    auth_config: dict[str, Any]
    runtime_config: dict[str, Any]
    manifest: dict[str, Any]
    last_health_status: str | None
    last_health_message: str | None
    last_health_check_at: str | None
    created_at: str
    updated_at: str


class WebSearchCatalogItemResponse(AppBaseModel):
    """One web-search provider catalog item exposed to the frontend."""

    manifest: dict[str, Any]


class WebSearchTestResponse(AppBaseModel):
    """Health-check response for one web-search provider binding."""

    result: dict[str, Any]
