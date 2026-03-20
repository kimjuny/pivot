"""Built-in providers for the abstract web-search system."""

from __future__ import annotations

from importlib import import_module
from pkgutil import iter_modules
from typing import TYPE_CHECKING

from app.orchestration.web_search.base import BaseWebSearchProvider

if TYPE_CHECKING:
    from app.orchestration.web_search.types import WebSearchProvider


def _load_builtin_provider_instances() -> dict[str, WebSearchProvider]:
    """Discover provider packages and return instantiated providers by key."""
    providers: dict[str, WebSearchProvider] = {}
    for module_info in iter_modules(__path__):  # type: ignore[name-defined]
        if not module_info.ispkg or module_info.name.startswith("_"):
            continue

        module = import_module(f"{__name__}.{module_info.name}")
        provider = getattr(module, "PROVIDER", None)
        if not isinstance(provider, BaseWebSearchProvider):
            continue

        logo_path = provider.get_logo_path()
        provider.manifest = provider.manifest.model_copy(
            update={
                "logo_url": (
                    f"/api/web-search/providers/{provider.manifest.key}/logo"
                    if logo_path is not None
                    else None
                )
            }
        )
        providers[provider.manifest.key] = provider

    return providers


BUILTIN_WEB_SEARCH_PROVIDERS = _load_builtin_provider_instances()

__all__ = ["BUILTIN_WEB_SEARCH_PROVIDERS"]
