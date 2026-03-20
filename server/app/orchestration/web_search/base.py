"""Base class for pluggable web-search providers."""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestration.web_search.types import (
        WebSearchExecutionResult,
        WebSearchProviderBinding,
        WebSearchProviderManifest,
        WebSearchQueryRequest,
        WebSearchTestResult,
    )


class BaseWebSearchProvider(ABC):
    """Base helper for built-in or community web-search provider adapters.

    Why: provider authors should only implement parameter mapping and remote HTTP
    calls. Persistence lookup and agent-binding resolution belong to the service
    layer, so a new provider never needs to understand the database schema.
    """

    manifest: WebSearchProviderManifest

    def get_name(self) -> str:
        """Return the user-facing provider name."""
        return self.manifest.name

    def get_description(self) -> str:
        """Return the user-facing provider description."""
        return self.manifest.description

    def get_provider_dir(self) -> Path:
        """Return the provider package directory that owns this implementation."""
        return Path(inspect.getfile(type(self))).resolve().parent

    def get_logo_path(self) -> Path | None:
        """Return the optional ``logo.svg`` path for this provider, if present."""
        logo_path = self.get_provider_dir() / "logo.svg"
        return logo_path if logo_path.is_file() else None

    def validate_config(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> None:
        """Validate required schema-driven fields for a provider."""
        del runtime_config
        for field in self.manifest.auth_schema:
            if field.required and not str(auth_config.get(field.key, "")).strip():
                raise ValueError(f"Missing required auth field: {field.label}")

    def get_api_key(self, binding: WebSearchProviderBinding) -> str:
        """Return the configured provider API key from a resolved binding."""
        api_key = str(binding.auth_config.get("api_key", "")).strip()
        if api_key == "":
            raise ValueError(
                f"Web search provider '{self.manifest.key}' is missing its API key."
            )
        return api_key

    def search(
        self,
        *,
        binding: WebSearchProviderBinding,
        request: WebSearchQueryRequest,
    ) -> WebSearchExecutionResult:
        """Execute one provider search using already-resolved binding data."""
        if not binding.enabled:
            raise ValueError(
                f"Web search provider '{self.manifest.key}' is disabled for this agent."
            )
        self.validate_config(binding.auth_config, binding.runtime_config)
        return self._search_with_binding(
            request=request,
            api_key=self.get_api_key(binding),
            runtime_config=binding.runtime_config,
        )

    @abstractmethod
    def _search_with_binding(
        self,
        *,
        request: WebSearchQueryRequest,
        api_key: str,
        runtime_config: dict[str, Any],
    ) -> WebSearchExecutionResult:
        """Execute the provider-native request with resolved binding config."""

    @abstractmethod
    def test_connection(
        self,
        *,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> WebSearchTestResult:
        """Execute a lightweight connectivity test for one provider."""
