"""Schemas for media-generation provider catalog and agent bindings."""

from __future__ import annotations

from typing import Any

from app.media_generation.types import MediaGenerationProviderManifest  # noqa: TC002
from app.schemas.base import AppBaseModel
from pydantic import Field


class MediaProviderCatalogItemResponse(AppBaseModel):
    """One catalog entry describing an available media-generation provider."""

    manifest: MediaGenerationProviderManifest


class MediaProviderBindingCreate(AppBaseModel):
    """Request payload for creating one agent media-provider binding."""

    provider_key: str
    enabled: bool = True
    auth_config: dict[str, Any] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class MediaProviderBindingUpdate(AppBaseModel):
    """Request payload for updating one existing media-provider binding."""

    enabled: bool | None = None
    auth_config: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None


class MediaProviderBindingTestRequest(AppBaseModel):
    """Request payload for testing one unsaved media-provider draft config."""

    auth_config: dict[str, Any] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class MediaProviderBindingResponse(AppBaseModel):
    """Serialized media-provider binding enriched with provider metadata."""

    id: int
    agent_id: int
    provider_key: str
    enabled: bool
    effective_enabled: bool = True
    disabled_reason: str | None = None
    auth_config: dict[str, str] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    manifest: MediaGenerationProviderManifest
    last_health_status: str | None = None
    last_health_message: str | None = None
    last_health_check_at: str | None = None
    created_at: str
    updated_at: str


class MediaProviderTestResponse(AppBaseModel):
    """Provider-specific config or health-check result envelope."""

    result: dict[str, Any]
