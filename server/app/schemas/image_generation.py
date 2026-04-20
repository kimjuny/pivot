"""Schemas for image-generation provider catalog and agent bindings."""

from __future__ import annotations

from typing import Any

from app.image_generation.types import ImageGenerationProviderManifest  # noqa: TC002
from app.schemas.base import AppBaseModel
from pydantic import Field


class ImageProviderCatalogItemResponse(AppBaseModel):
    """One catalog entry describing an available image-generation provider."""

    manifest: ImageGenerationProviderManifest


class ImageProviderBindingCreate(AppBaseModel):
    """Request payload for creating one agent image-provider binding."""

    provider_key: str
    enabled: bool = True
    auth_config: dict[str, Any] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class ImageProviderBindingUpdate(AppBaseModel):
    """Request payload for updating one existing image-provider binding."""

    enabled: bool | None = None
    auth_config: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None


class ImageProviderBindingTestRequest(AppBaseModel):
    """Request payload for testing one unsaved image-provider draft config."""

    auth_config: dict[str, Any] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)


class ImageProviderBindingResponse(AppBaseModel):
    """Serialized image-provider binding enriched with provider metadata."""

    id: int
    agent_id: int
    provider_key: str
    enabled: bool
    effective_enabled: bool = True
    disabled_reason: str | None = None
    auth_config: dict[str, str] = Field(default_factory=dict)
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    manifest: ImageGenerationProviderManifest
    last_health_status: str | None = None
    last_health_message: str | None = None
    last_health_check_at: str | None = None
    created_at: str
    updated_at: str


class ImageProviderTestResponse(AppBaseModel):
    """Provider-specific config or health-check result envelope."""

    result: dict[str, Any]
