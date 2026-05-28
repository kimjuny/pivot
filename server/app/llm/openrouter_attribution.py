"""Helpers for OpenRouter app-attribution request headers."""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import get_settings


def _is_openrouter_endpoint(endpoint: str) -> bool:
    """Return whether one endpoint targets OpenRouter."""
    hostname = urlparse(endpoint).hostname or ""
    normalized = hostname.strip().lower()
    return normalized == "openrouter.ai" or normalized.endswith(".openrouter.ai")


def build_openrouter_attribution_headers(endpoint: str) -> dict[str, str]:
    """Return app-attribution headers for OpenRouter requests only.

    Why: OpenRouter app attribution identifies one application, not one model
    config. We therefore keep this as a backend deployment setting and inject
    it only when the selected provider endpoint is OpenRouter.
    """
    if not _is_openrouter_endpoint(endpoint):
        return {}

    settings = get_settings()
    app_url = (settings.OPENROUTER_APP_URL or "").strip()
    if not app_url:
        return {}

    headers = {
        "HTTP-Referer": app_url,
    }

    app_title = (settings.OPENROUTER_APP_TITLE or settings.PROJECT_NAME or "").strip()
    if app_title:
        headers["X-OpenRouter-Title"] = app_title

    categories = (settings.OPENROUTER_APP_CATEGORIES or "").strip()
    if categories:
        headers["X-OpenRouter-Categories"] = categories

    return headers
