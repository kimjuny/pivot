"""Shared manifest and execution types for web-search providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from app.orchestration.web_search.normalization import (
    normalize_date_text,
    normalize_domain_list,
    normalize_enum_text,
    normalize_optional_text,
    normalize_required_text,
)
from app.schemas.base import AppBaseModel
from pydantic import Field, field_validator

if TYPE_CHECKING:
    from pathlib import Path

FieldType = Literal["text", "number", "secret", "textarea", "boolean"]
SearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]
SearchTopic = Literal["general", "news", "finance"]
SearchTimeRange = Literal["day", "week", "month", "year"]


class WebSearchConfigField(AppBaseModel):
    """Schema-driven field used by the frontend to render config forms."""

    key: str
    label: str
    type: FieldType
    required: bool = False
    placeholder: str | None = None
    description: str | None = None


class WebSearchProviderManifest(AppBaseModel):
    """Declarative metadata for one installed web-search provider."""

    key: str
    name: str
    description: str
    docs_url: str
    logo_url: str | None = None
    visibility: str = "builtin"
    status: str = "active"
    auth_schema: list[WebSearchConfigField]
    config_schema: list[WebSearchConfigField]
    setup_steps: list[str]
    supported_parameters: list[str]


@dataclass(frozen=True)
class WebSearchProviderBinding:
    """Resolved provider binding payload passed from the service layer."""

    provider_key: str
    enabled: bool
    auth_config: dict[str, Any]
    runtime_config: dict[str, Any]


class WebSearchQueryRequest(AppBaseModel):
    """Provider-neutral request shape accepted by the abstract web_search tool."""

    query: str
    provider: str | None = None
    max_results: int = Field(default=5, ge=1, le=20)
    search_depth: SearchDepth | None = None
    topic: SearchTopic | None = None
    time_range: SearchTimeRange | None = None
    start_date: str | None = None
    end_date: str | None = None
    include_answer: bool = False
    include_raw_content: bool = False
    include_images: bool = False
    include_image_descriptions: bool = False
    include_favicon: bool = False
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    country: str | None = None
    auto_parameters: bool = False
    exact_match: bool = False
    include_usage: bool = False
    safe_search: bool = False

    @field_validator("query", mode="before")
    @classmethod
    def _normalize_query(cls, value: Any) -> str:
        """Normalize required query text before validation."""
        return normalize_required_text(value, field_name="query")

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: Any) -> str | None:
        """Normalize optional provider text before validation."""
        normalized = normalize_optional_text(value, field_name="provider")
        return normalized.lower() if normalized is not None else None

    @field_validator("search_depth", mode="before")
    @classmethod
    def _normalize_search_depth(cls, value: Any) -> str | None:
        """Normalize search-depth aliases before validation."""
        return normalize_enum_text(
            value,
            field_name="search_depth",
            aliases={
                "basic": "basic",
                "advanced": "advanced",
                "fast": "fast",
                "ultra-fast": "ultra-fast",
                "ultrafast": "ultra-fast",
                "ultra_fast": "ultra-fast",
                "ultra fast": "ultra-fast",
            },
        )

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, value: Any) -> str | None:
        """Normalize topic aliases before validation."""
        return normalize_enum_text(
            value,
            field_name="topic",
            aliases={
                "general": "general",
                "news": "news",
                "finance": "finance",
            },
        )

    @field_validator("time_range", mode="before")
    @classmethod
    def _normalize_time_range(cls, value: Any) -> str | None:
        """Normalize time-range aliases before validation."""
        return normalize_enum_text(
            value,
            field_name="time_range",
            aliases={
                "day": "day",
                "d": "day",
                "week": "week",
                "w": "week",
                "month": "month",
                "m": "month",
                "year": "year",
                "y": "year",
            },
        )

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _normalize_dates(cls, value: Any, info: Any) -> str | None:
        """Normalize date-like fields before provider execution."""
        return normalize_date_text(value, field_name=str(info.field_name))

    @field_validator("country", mode="before")
    @classmethod
    def _normalize_country(cls, value: Any) -> str | None:
        """Normalize optional country text before validation."""
        normalized = normalize_optional_text(value, field_name="country")
        return normalized.lower() if normalized is not None else None

    @field_validator("include_domains", "exclude_domains", mode="before")
    @classmethod
    def _normalize_domain_fields(cls, value: Any) -> list[str]:
        """Normalize domain lists into hostname-only entries."""
        return normalize_domain_list(value)


class WebSearchResultItem(AppBaseModel):
    """One normalized search result item returned by a provider."""

    title: str
    url: str
    snippet: str | None = None
    content: str | None = None
    source: str | None = None
    published_at: str | None = None
    score: float | None = None
    favicon_url: str | None = None
    resource_type: str = "web"
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebSearchExecutionResult(AppBaseModel):
    """Structured result returned by the abstract web_search tool."""

    query: str
    provider: dict[str, str]
    applied_parameters: dict[str, Any] = Field(default_factory=dict)
    ignored_parameters: dict[str, str] = Field(default_factory=dict)
    provider_request: dict[str, Any] = Field(default_factory=dict)
    provider_response_metadata: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
    images: list[dict[str, Any]] = Field(default_factory=list)
    results: list[WebSearchResultItem] = Field(default_factory=list)


class WebSearchTestResult(AppBaseModel):
    """Connectivity or credential validation result returned by providers."""

    ok: bool
    status: str
    message: str


class WebSearchProvider(Protocol):
    """Runtime contract implemented by each web-search adapter."""

    manifest: WebSearchProviderManifest

    def get_name(self) -> str:
        """Return the human-readable provider name."""
        ...

    def get_description(self) -> str:
        """Return the human-readable provider description."""
        ...

    def get_logo_path(self) -> Path | None:
        """Return the optional logo asset path for this provider."""
        ...

    def validate_config(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> None:
        """Validate one binding's credentials and config."""
        ...

    def search(
        self,
        *,
        binding: WebSearchProviderBinding,
        request: WebSearchQueryRequest,
    ) -> WebSearchExecutionResult:
        """Execute one provider-backed search through the remote API."""
        ...

    def test_connection(
        self,
        *,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> WebSearchTestResult:
        """Execute a lightweight connectivity test for one provider."""
        ...
