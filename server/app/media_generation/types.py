"""Shared manifest and execution types for media-generation providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.schemas.base import AppBaseModel
from pydantic import Field, field_validator

FieldType = Literal["text", "number", "secret", "textarea", "boolean"]
MediaType = Literal["image", "video"]
MediaInputRole = Literal["first_frame", "last_frame", "reference"]
MediaProviderJobStatus = Literal["pending", "running", "succeeded", "failed"]


class MediaProviderConfigField(AppBaseModel):
    """Schema-driven field used by the frontend to render config forms."""

    key: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: str | None = None
    default_value: str | int | float | bool | None = None
    description: str | None = None


class MediaGenerationProviderManifest(AppBaseModel):
    """Declarative metadata for one installed media-generation provider."""

    key: str
    name: str
    media_type: MediaType
    description: str
    docs_url: str
    visibility: str = "builtin"
    status: str = "active"
    extension_name: str | None = None
    extension_version: str | None = None
    extension_display_name: str | None = None
    auth_schema: list[MediaProviderConfigField]
    config_schema: list[MediaProviderConfigField]
    setup_steps: list[str]
    supported_operations: list[str]
    supported_parameters: list[str]
    capability_flags: dict[str, bool] = Field(default_factory=dict)


@dataclass(frozen=True)
class MediaGenerationProviderBinding:
    """Resolved provider binding payload passed from the service layer."""

    provider_key: str
    enabled: bool
    auth_config: dict[str, Any]
    runtime_config: dict[str, Any]


class MediaGenerationInput(AppBaseModel):
    """Provider-neutral media input attached to one generation request."""

    media_type: MediaType
    role: MediaInputRole
    source_path: str | None = None
    base64_data: str | None = None
    mime_type: str | None = None
    file_name: str | None = None

    @field_validator("source_path", mode="before")
    @classmethod
    def _normalize_source_path(cls, value: Any) -> str | None:
        """Normalize one optional workspace source path."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("source_path must be a string when provided.")
        normalized = value.strip()
        return normalized or None

    @field_validator("base64_data", mode="before")
    @classmethod
    def _normalize_base64_data(cls, value: Any) -> str | None:
        """Normalize one optional base64 payload."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("base64_data must be a string when provided.")
        normalized = value.strip()
        return normalized or None

    @field_validator("file_name", mode="before")
    @classmethod
    def _normalize_file_name(cls, value: Any) -> str | None:
        """Normalize one optional input filename."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("file_name must be a string when provided.")
        normalized = value.strip()
        return normalized or None


class MediaGenerationRequest(AppBaseModel):
    """Provider-neutral request shape passed into one provider invocation."""

    operation: str = Field(default="generate", min_length=1)
    prompt: str | None = None
    output_path: str = "/workspace/.pivot/generated/media/output"
    poll_timeout_seconds: int = Field(default=90, ge=1, le=900)
    poll_interval_seconds: int = Field(default=3, ge=1, le=60)
    inputs: list[MediaGenerationInput] = Field(default_factory=list)
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

    @field_validator("inputs", mode="before")
    @classmethod
    def _normalize_inputs(cls, value: Any) -> list[MediaGenerationInput]:
        """Normalize provider input media into a typed list."""
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("inputs must be an array.")
        return value

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
class MediaGenerationJobHandle:
    """Provider-owned job handle returned by ``start``."""

    provider_key: str
    operation: str
    status: MediaProviderJobStatus
    request_id: str | None = None
    provider_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MediaGenerationJobState:
    """Current state observed by one service-level poll iteration."""

    status: MediaProviderJobStatus
    request_id: str | None = None
    payload: dict[str, Any] | None = None
    error_message: str | None = None


@dataclass(slots=True)
class MediaGenerationArtifact:
    """One provider-returned media artifact before workspace persistence."""

    media_type: MediaType
    url: str | None = None
    base64_data: str | None = None
    mime_type: str | None = None
    suggested_name: str | None = None


class MediaGenerationExecutionResult(AppBaseModel):
    """Structured result returned to media-generation tools."""

    provider: dict[str, str]
    operation: str
    output_paths: list[str] = Field(default_factory=list)
    primary_output_path: str | None = None
    provider_task_id: str | None = None
    request_id: str | None = None
    status: str
    usage: dict[str, Any] = Field(default_factory=dict)
    provider_payload: dict[str, Any] = Field(default_factory=dict)


class MediaGenerationTestResult(AppBaseModel):
    """Connectivity or configuration validation result returned by providers."""

    ok: bool
    status: str
    message: str


@dataclass(slots=True)
class MediaGenerationCollectResult:
    """Final provider result before the service persists artifacts."""

    provider_key: str
    operation: str
    status: MediaProviderJobStatus
    request_id: str | None
    provider_task_id: str | None
    artifacts: list[MediaGenerationArtifact] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class MediaGenerationProvider(Protocol):
    """Runtime contract implemented by each media-generation adapter."""

    manifest: MediaGenerationProviderManifest

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
    ) -> MediaGenerationTestResult:
        """Execute a lightweight connectivity or config validation check."""
        ...

    def start(
        self,
        *,
        binding: MediaGenerationProviderBinding,
        request: MediaGenerationRequest,
    ) -> MediaGenerationJobHandle:
        """Start one media-generation provider job."""
        ...

    def poll(
        self,
        *,
        binding: MediaGenerationProviderBinding,
        handle: MediaGenerationJobHandle,
    ) -> MediaGenerationJobState:
        """Poll one provider job handle for its latest status."""
        ...

    def collect(
        self,
        *,
        binding: MediaGenerationProviderBinding,
        handle: MediaGenerationJobHandle,
    ) -> MediaGenerationCollectResult:
        """Collect the final payload for one completed provider job."""
        ...
