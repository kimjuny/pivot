"""Registry helpers for built-in web-search providers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.orchestration.web_search.providers import BUILTIN_WEB_SEARCH_PROVIDERS

if TYPE_CHECKING:
    from app.orchestration.web_search.types import WebSearchProvider


def list_web_search_providers() -> list[WebSearchProvider]:
    """Return every installed built-in web-search provider."""
    return list(BUILTIN_WEB_SEARCH_PROVIDERS.values())


def get_web_search_provider(provider_key: str) -> WebSearchProvider:
    """Resolve one web-search provider by its stable key."""
    return BUILTIN_WEB_SEARCH_PROVIDERS[provider_key]
