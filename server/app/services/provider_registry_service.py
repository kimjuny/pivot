"""Services for resolving built-in and extension-backed providers."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.channels.providers import BUILTIN_PROVIDERS
from app.channels.types import ChannelManifest, ChannelProvider
from app.media_generation.providers import BUILTIN_MEDIA_GENERATION_PROVIDERS
from app.media_generation.types import (
    MediaGenerationProvider,
    MediaGenerationProviderManifest,
)
from app.models.channel import AgentChannelBinding
from app.models.extension import ExtensionInstallation
from app.models.media_generation import AgentMediaProviderBinding
from app.models.web_search import AgentWebSearchBinding
from app.orchestration.web_search.providers import BUILTIN_WEB_SEARCH_PROVIDERS
from app.orchestration.web_search.types import (
    WebSearchProvider,
    WebSearchProviderManifest,
)
from app.services.artifact_storage_service import ExtensionArtifactStorageService
from sqlmodel import Session, col, select


@dataclass(frozen=True)
class ProviderBindingReferenceSummary:
    """Counts of agent provider bindings that depend on one installation."""

    channel_binding_count: int
    media_provider_binding_count: int
    web_search_binding_count: int

    @property
    def total_count(self) -> int:
        """Return the combined binding count across provider types."""
        return (
            self.channel_binding_count
            + self.media_provider_binding_count
            + self.web_search_binding_count
        )


@dataclass(frozen=True)
class ProviderConflict:
    """Describe one provider-key collision during installation or activation."""

    provider_type: str
    provider_key: str
    source: str
    installation_id: int | None = None
    installation_name: str | None = None
    installation_version: str | None = None


def extract_provider_keys_from_manifest(
    manifest: dict[str, Any],
) -> dict[str, set[str]]:
    """Return provider keys declared by one normalized extension manifest."""
    contributions = manifest.get("contributions")
    if not isinstance(contributions, dict):
        return {"channel": set(), "media": set(), "web_search": set()}

    channel_keys = {
        str(item["key"])
        for item in contributions.get("channel_providers", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"]
    }
    media_keys = {
        str(item["key"])
        for item in contributions.get("media_providers", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"]
    }
    web_search_keys = {
        str(item["key"])
        for item in contributions.get("web_search_providers", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"]
    }
    return {
        "channel": channel_keys,
        "media": media_keys,
        "web_search": web_search_keys,
    }


def load_channel_provider_from_file(
    *,
    source_path: Path,
    module_key: str,
    visibility: str = "extension",
    status: str = "active",
    extension_name: str | None = None,
    extension_version: str | None = None,
    extension_display_name: str | None = None,
) -> ChannelProvider:
    """Load one channel provider object exported from a Python entrypoint."""
    spec = importlib.util.spec_from_file_location(module_key, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(
            f"Unable to import channel provider entrypoint '{source_path}'."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise ValueError(
            f"Failed to load channel provider from '{source_path}': {exc}"
        ) from exc
    provider = getattr(module, "PROVIDER", None)
    if not isinstance(provider, ChannelProvider):
        raise ValueError(
            f"Channel provider entrypoint '{source_path}' must export PROVIDER."
        )
    manifest = getattr(provider, "manifest", None)
    if not isinstance(manifest, ChannelManifest):
        raise ValueError(
            f"Channel provider entrypoint '{source_path}' must expose "
            "a ChannelManifest."
        )
    provider.manifest = manifest.model_copy(
        update={
            "visibility": visibility,
            "status": status,
            "extension_name": extension_name,
            "extension_version": extension_version,
            "extension_display_name": extension_display_name,
        }
    )
    return provider


def load_web_search_provider_from_file(
    *,
    source_path: Path,
    module_key: str,
    visibility: str = "extension",
    status: str = "active",
    extension_name: str | None = None,
    extension_version: str | None = None,
    extension_display_name: str | None = None,
) -> WebSearchProvider:
    """Load one web-search provider object exported from a Python entrypoint."""
    spec = importlib.util.spec_from_file_location(module_key, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(
            f"Unable to import web-search provider entrypoint '{source_path}'."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise ValueError(
            f"Failed to load web-search provider from '{source_path}': {exc}"
        ) from exc
    provider = getattr(module, "PROVIDER", None)
    if not isinstance(provider, WebSearchProvider):
        raise ValueError(
            f"Web-search provider entrypoint '{source_path}' must export PROVIDER."
        )
    manifest = getattr(provider, "manifest", None)
    if not isinstance(manifest, WebSearchProviderManifest):
        raise ValueError(
            f"Web-search provider entrypoint '{source_path}' must expose "
            "a WebSearchProviderManifest."
        )
    logo_path = provider.get_logo_path()
    provider.manifest = manifest.model_copy(
        update={
            "visibility": visibility,
            "status": status,
            "extension_name": extension_name,
            "extension_version": extension_version,
            "extension_display_name": extension_display_name,
            "logo_url": (
                f"/api/web-search/providers/{manifest.key}/logo"
                if logo_path is not None
                else None
            ),
        }
    )
    return provider


def load_media_generation_provider_from_file(
    *,
    source_path: Path,
    module_key: str,
    visibility: str = "extension",
    status: str = "active",
    extension_name: str | None = None,
    extension_version: str | None = None,
    extension_display_name: str | None = None,
) -> MediaGenerationProvider:
    """Load one media-generation provider object from a Python entrypoint."""
    spec = importlib.util.spec_from_file_location(module_key, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(
            f"Unable to import media-generation provider entrypoint '{source_path}'."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise ValueError(
            f"Failed to load media-generation provider from '{source_path}': {exc}"
        ) from exc
    provider = getattr(module, "PROVIDER", None)
    if not isinstance(provider, MediaGenerationProvider):
        raise ValueError(
            f"Media-generation provider entrypoint '{source_path}' must export PROVIDER."
        )
    manifest = getattr(provider, "manifest", None)
    if not isinstance(manifest, MediaGenerationProviderManifest):
        raise ValueError(
            f"Media-generation provider entrypoint '{source_path}' must expose "
            "a MediaGenerationProviderManifest."
        )
    provider.manifest = manifest.model_copy(
        update={
            "visibility": visibility,
            "status": status,
            "extension_name": extension_name,
            "extension_version": extension_version,
            "extension_display_name": extension_display_name,
        }
    )
    return provider


class ProviderRegistryService:
    """Resolve installed provider catalogs across built-ins and extensions."""

    def __init__(self, db: Session) -> None:
        """Store the active database session for provider resolution."""
        self.db = db
        self.artifact_storage = ExtensionArtifactStorageService()

    def list_channel_providers(self) -> list[ChannelProvider]:
        """Return every active channel provider visible to the application."""
        providers = dict(BUILTIN_PROVIDERS)
        for provider in self._load_extension_channel_providers().values():
            providers[provider.manifest.key] = provider
        return list(providers.values())

    def get_channel_provider(self, channel_key: str) -> ChannelProvider:
        """Resolve one channel provider by provider key."""
        provider = self._load_extension_channel_providers().get(channel_key)
        if provider is not None:
            return provider
        return BUILTIN_PROVIDERS[channel_key]

    def list_web_search_providers(self) -> list[WebSearchProvider]:
        """Return every active web-search provider visible to the application."""
        providers = dict(BUILTIN_WEB_SEARCH_PROVIDERS)
        for provider in self._load_extension_web_search_providers().values():
            providers[provider.manifest.key] = provider
        return list(providers.values())

    def list_media_generation_providers(self) -> list[MediaGenerationProvider]:
        """Return every active media-generation provider visible to the app."""
        providers = dict(BUILTIN_MEDIA_GENERATION_PROVIDERS)
        for provider in self._load_extension_media_generation_providers().values():
            providers[provider.manifest.key] = provider
        return list(providers.values())

    def get_web_search_provider(self, provider_key: str) -> WebSearchProvider:
        """Resolve one web-search provider by provider key."""
        provider = self._load_extension_web_search_providers().get(provider_key)
        if provider is not None:
            return provider
        return BUILTIN_WEB_SEARCH_PROVIDERS[provider_key]

    def get_media_generation_provider(
        self,
        provider_key: str,
    ) -> MediaGenerationProvider:
        """Resolve one media-generation provider by provider key."""
        provider = self._load_extension_media_generation_providers().get(provider_key)
        if provider is not None:
            return provider
        return BUILTIN_MEDIA_GENERATION_PROVIDERS[provider_key]

    def analyze_manifest_provider_conflicts(
        self,
        *,
        manifest: dict[str, Any],
        excluding_installation_id: int | None = None,
    ) -> list[ProviderConflict]:
        """Return provider-key conflicts for one manifest against active providers."""
        conflicts: list[ProviderConflict] = []
        requested_keys = extract_provider_keys_from_manifest(manifest)

        for channel_key in sorted(requested_keys["channel"]):
            if channel_key in BUILTIN_PROVIDERS:
                conflicts.append(
                    ProviderConflict(
                        provider_type="channel",
                        provider_key=channel_key,
                        source="builtin",
                    )
                )

        for provider_key in sorted(requested_keys["media"]):
            if provider_key in BUILTIN_MEDIA_GENERATION_PROVIDERS:
                conflicts.append(
                    ProviderConflict(
                        provider_type="media",
                        provider_key=provider_key,
                        source="builtin",
                    )
                )

        for provider_key in sorted(requested_keys["web_search"]):
            if provider_key in BUILTIN_WEB_SEARCH_PROVIDERS:
                conflicts.append(
                    ProviderConflict(
                        provider_type="web_search",
                        provider_key=provider_key,
                        source="builtin",
                    )
                )

        statement = select(ExtensionInstallation).where(
            col(ExtensionInstallation.status) == "active"
        )
        for installation in self.db.exec(statement).all():
            installation_id = installation.id
            if (
                excluding_installation_id is not None
                and installation_id == excluding_installation_id
            ):
                continue
            if installation_id is None:
                continue

            installed_manifest = self._load_manifest(installation)
            installed_keys = extract_provider_keys_from_manifest(installed_manifest)
            for provider_type, key_group in installed_keys.items():
                overlap = sorted(requested_keys[provider_type] & key_group)
                for provider_key in overlap:
                    conflicts.append(
                        ProviderConflict(
                            provider_type=provider_type,
                            provider_key=provider_key,
                            source="extension",
                            installation_id=installation_id,
                            installation_name=installation.package_id,
                            installation_version=installation.version,
                        )
                    )

        return conflicts

    def count_installation_provider_binding_references(
        self,
        installation: ExtensionInstallation,
    ) -> int:
        """Count agent provider bindings that depend on one installation."""
        return self.get_installation_provider_binding_summary(installation).total_count

    def get_installation_provider_binding_summary(
        self,
        installation: ExtensionInstallation,
    ) -> ProviderBindingReferenceSummary:
        """Return provider-binding reference counts for one installation."""
        manifest = self._load_manifest(installation)
        provider_keys = extract_provider_keys_from_manifest(manifest)

        channel_keys = provider_keys["channel"]
        channel_binding_count = 0
        if channel_keys:
            channel_binding_count = len(
                self.db.exec(
                    select(AgentChannelBinding).where(
                        col(AgentChannelBinding.channel_key).in_(channel_keys)
                    )
                ).all()
            )

        media_keys = provider_keys["media"]
        media_provider_binding_count = 0
        if media_keys:
            media_provider_binding_count = len(
                self.db.exec(
                    select(AgentMediaProviderBinding).where(
                        col(AgentMediaProviderBinding.provider_key).in_(media_keys)
                    )
                ).all()
            )

        web_search_keys = provider_keys["web_search"]
        web_search_binding_count = 0
        if web_search_keys:
            web_search_binding_count = len(
                self.db.exec(
                    select(AgentWebSearchBinding).where(
                        col(AgentWebSearchBinding.provider_key).in_(web_search_keys)
                    )
                ).all()
            )

        return ProviderBindingReferenceSummary(
            channel_binding_count=channel_binding_count,
            media_provider_binding_count=media_provider_binding_count,
            web_search_binding_count=web_search_binding_count,
        )

    def _load_extension_channel_providers(self) -> dict[str, ChannelProvider]:
        """Load channel providers contributed by active extension installations."""
        providers: dict[str, ChannelProvider] = {}
        for installation in self._iter_active_installations():
            manifest = self._load_manifest(installation)
            contributions = manifest.get("contributions", {})
            if not isinstance(contributions, dict):
                continue

            for item in contributions.get("channel_providers", []):
                if not isinstance(item, dict):
                    continue
                entrypoint = item.get("entrypoint")
                if not isinstance(entrypoint, str) or not entrypoint:
                    continue
                install_root = self.artifact_storage.ensure_materialized_directory(
                    artifact_key=installation.artifact_key,
                    target_dir=Path(installation.install_root),
                )
                source_path = install_root.joinpath(*PurePosixPath(entrypoint).parts)
                provider = load_channel_provider_from_file(
                    source_path=source_path,
                    module_key=(
                        f"_pivot_extension_channel_{installation.id}_"
                        f"{item.get('key', 'provider')}"
                    ),
                    extension_name=installation.package_id,
                    extension_version=installation.version,
                    extension_display_name=installation.display_name,
                )
                providers[provider.manifest.key] = provider
        return providers

    def _load_extension_web_search_providers(self) -> dict[str, WebSearchProvider]:
        """Load web-search providers contributed by active extension installations."""
        providers: dict[str, WebSearchProvider] = {}
        for installation in self._iter_active_installations():
            manifest = self._load_manifest(installation)
            contributions = manifest.get("contributions", {})
            if not isinstance(contributions, dict):
                continue

            for item in contributions.get("web_search_providers", []):
                if not isinstance(item, dict):
                    continue
                entrypoint = item.get("entrypoint")
                if not isinstance(entrypoint, str) or not entrypoint:
                    continue
                install_root = self.artifact_storage.ensure_materialized_directory(
                    artifact_key=installation.artifact_key,
                    target_dir=Path(installation.install_root),
                )
                source_path = install_root.joinpath(*PurePosixPath(entrypoint).parts)
                provider = load_web_search_provider_from_file(
                    source_path=source_path,
                    module_key=(
                        f"_pivot_extension_web_search_{installation.id}_"
                        f"{item.get('key', 'provider')}"
                    ),
                    extension_name=installation.package_id,
                    extension_version=installation.version,
                    extension_display_name=installation.display_name,
                )
                providers[provider.manifest.key] = provider
        return providers

    def _load_extension_media_generation_providers(
        self,
    ) -> dict[str, MediaGenerationProvider]:
        """Load media-generation providers from active extension installations."""
        providers: dict[str, MediaGenerationProvider] = {}
        for installation in self._iter_active_installations():
            manifest = self._load_manifest(installation)
            contributions = manifest.get("contributions", {})
            if not isinstance(contributions, dict):
                continue

            for item in contributions.get("media_providers", []):
                if not isinstance(item, dict):
                    continue
                entrypoint = item.get("entrypoint")
                if not isinstance(entrypoint, str) or not entrypoint:
                    continue
                install_root = self.artifact_storage.ensure_materialized_directory(
                    artifact_key=installation.artifact_key,
                    target_dir=Path(installation.install_root),
                )
                source_path = install_root.joinpath(*PurePosixPath(entrypoint).parts)
                provider = load_media_generation_provider_from_file(
                    source_path=source_path,
                    module_key=(
                        f"_pivot_extension_media_{installation.id}_"
                        f"{item.get('key', 'provider')}"
                    ),
                    extension_name=installation.package_id,
                    extension_version=installation.version,
                    extension_display_name=installation.display_name,
                )
                providers[provider.manifest.key] = provider
        return providers

    def _iter_active_installations(self) -> list[ExtensionInstallation]:
        """Return every active installation that may contribute providers."""
        statement = select(ExtensionInstallation).where(
            col(ExtensionInstallation.status) == "active"
        )
        return list(self.db.exec(statement).all())

    @staticmethod
    def _load_manifest(installation: ExtensionInstallation) -> dict[str, Any]:
        """Parse the persisted normalized manifest for one installation."""
        parsed = json.loads(installation.manifest_json)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Stored manifest for {installation.package_id}@{installation.version} "
                "is invalid."
            )
        return parsed
