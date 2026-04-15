"""Shared manifest and execution types for image-generation providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.schemas.base import AppBaseModel
from pydantic import Field, field_validator

FieldType = Literal["text", "number", "secret", "textarea", "boolean"]
ImageProviderJobStatus = Literal["pending", "running", "succeeded", "failed"]


class ImageProviderConfigField(AppBaseModel):
    """Schema-driven field used by the frontend to render config forms."""

    key: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: str | None = None
    description: str | None = None


class ImageGenerationProviderManifest(AppBaseModel):
    """Declarative metadata for one installed image-generation provider."""

    key: str
    name: str
    description: str
    docs_url: str
    visibility: str = "builtin"
    status: str = "active"
    extension_name: str | None = None
    extension_version: str | None = None
    extension_display_name: str | None = None
    auth_schema: list[ImageProviderConfigField]
    config_schema: list[ImageProviderConfigField]
    setup_steps: list[str]
    supported_operations: list[str]
    supported_parameters: list[str]
    capability_flags: dict[str, bool] = Field(default_factory=dict)


@dataclass(frozen=True)
class ImageGenerationProviderBinding:
    """Resolved provider binding payload passed from the service layer."""

    provider_key: str
    enabled: bool
    auth_config: dict[str, Any]
    runtime_config: dict[str, Any]


class ImageGenerationRequest(AppBaseModel):
    """Provider-neutral request shape passed into one provider invocation."""

    operation: str = Field(default="generate", min_length=1)
    prompt: str | None = None
    output_path: str = "/workspace/.pivot/generated/images/output.png"
    poll_timeout_seconds: int = Field(default=90, ge=1, le=900)
    poll_interval_seconds: int = Field(default=3, ge=1, le=60)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("operation", mode="before")
    @classmethod
    def _normalize_operation(cls, value: Any) -> str:
        """Normalize the requested provider operation name."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("operation must be a non-empty string.")
        return value.strip()

    @field_validator("prompt", mode="before")
    @classmethod
    def _normalize_prompt(cls, value: Any) -> str | None:
        """Normalize optional prompt text."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("prompt must be a string when provided.")
        normalized = value.strip()
        return normalized or None

    @field_validator("output_path", mode="before")
    @classmethod
    def _normalize_output_path(cls, value: Any) -> str:
        """Normalize the desired sandbox output path."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("output_path must be a non-empty string.")
        return value.strip()

    @field_validator("parameters", mode="before")
    @classmethod
    def _normalize_parameters(cls, value: Any) -> dict[str, Any]:
        """Normalize provider-specific parameters into a JSON object."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("parameters must be an object.")
        return value


@dataclass(slots=True)
class ImageGenerationJobHandle:
    """Provider-owned job handle returned by ``start``."""

    provider_key: str
    operation: str
    status: ImageProviderJobStatus
    request_id: str | None = None
    provider_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageGenerationJobState:
    """Current state observed by one service-level poll iteration."""

    status: ImageProviderJobStatus
    request_id: str | None = None
    payload: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(slots=True)
class ImageGenerationArtifact:
    """One provider-returned image artifact before workspace persistence."""

    url: str | None = None
    base64_data: str | None = None
    mime_type: str | None = None
    suggested_name: str | None = None


class ImageGenerationExecutionResult(AppBaseModel):
    """Structured result returned to image-generation tools."""

    provider: dict[str, str]
    operation: str
    output_paths: list[str] = Field(default_factory=list)
    primary_output_path: str | None = None
    provider_task_id: str | None = None
    request_id: str | None = None
    status: str
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class ImageGenerationTestResult(AppBaseModel):
    """Connectivity or configuration validation result returned by providers."""

    ok: bool
    status: str
    message: str


@dataclass(slots=True)
class ImageGenerationCollectResult:
    """Final provider result before the service persists artifacts."""

    provider_key: str
    operation: str
    status: ImageProviderJobStatus
    request_id: str | None
    provider_task_id: str | None
    artifacts: list[ImageGenerationArtifact] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ImageGenerationProvider(Protocol):
    """Runtime contract implemented by each image-generation adapter."""

    manifest: ImageGenerationProviderManifest

    def validate_config(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> None:
        """Validate one binding's credentials and runtime configuration."""
        ...

    def test_connection(
        self,
        *,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> ImageGenerationTestResult:
        """Execute a lightweight connectivity or config validation check."""
        ...

    def start(
        self,
        *,
        binding: ImageGenerationProviderBinding,
        request: ImageGenerationRequest,
    ) -> ImageGenerationJobHandle:
        """Start one image-generation provider job."""
        ...

    def poll(
        self,
        *,
        binding: ImageGenerationProviderBinding,
        handle: ImageGenerationJobHandle,
    ) -> ImageGenerationJobState:
        """Poll one provider job handle for its latest status."""
        ...

    def collect(
        self,
        *,
        binding: ImageGenerationProviderBinding,
        handle: ImageGenerationJobHandle,
    ) -> ImageGenerationCollectResult:
        """Collect the final payload for one completed provider job."""
        ...
