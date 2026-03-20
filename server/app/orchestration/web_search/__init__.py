"""Web-search provider registry and shared types."""

from app.orchestration.web_search.registry import (
    get_web_search_provider,
    list_web_search_providers,
)

__all__ = ["get_web_search_provider", "list_web_search_providers"]
