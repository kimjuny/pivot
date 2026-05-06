"""Services for installing and resolving extension package folders."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import re
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

from app.channels.types import ChannelManifest
from app.config import get_settings
from app.media_generation.types import MediaGenerationProviderManifest
from app.models.access import AccessLevel, PrincipalType, ResourceType
from app.models.agent_release import AgentRelease, AgentSavedDraft, AgentTestSnapshot
from app.models.channel import (
    AgentChannelBinding,
    ChannelEventLog,
    ChannelLinkToken,
    ChannelSession,
    ExternalIdentityBinding,
)
from app.models.extension import AgentExtensionBinding, ExtensionInstallation
from app.models.media_generation import AgentMediaProviderBinding
from app.models.skill import Skill
from app.models.user import User
from app.models.web_search import AgentWebSearchBinding
from app.orchestration.skills.skill_files import parse_front_matter
from app.orchestration.tool import ToolManager, get_tool_manager
from app.orchestration.tool.builtin.programmatic_tool_call import (
    make_programmatic_tool_call,
)
from app.orchestration.tool.metadata import ToolMetadata
from app.orchestration.web_search.types import WebSearchProviderManifest
from app.services.access_service import AccessService
from app.services.artifact_storage_service import ExtensionArtifactStorageService
from app.services.provider_registry_service import (
    ProviderRegistryService,
    extract_provider_keys_from_manifest,
    load_channel_provider_from_file,
    load_media_generation_provider_from_file,
    load_web_search_provider_from_file,
)
from app.services.tool_service import load_runtime_manual_tool_metadata
from app.services.workspace_service import ensure_agent_workspace
from sqlmodel import Session, col, select

_MANIFEST_FILENAME = "manifest.json"
_README_MARKDOWN_FILENAME = "README.md"
_SKILL_MARKDOWN_FILENAME = "SKILL.md"
_DEFAULT_EXTENSION_LOGO_BASENAME = "logo"
_VALID_EXTENSION_SCOPE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VALID_EXTENSION_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VALID_PROVIDER_LOCAL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VALID_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_SUPPORTED_EXTENSION_LOGO_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".svg", ".webp"}
)
_SUPPORTED_CONFIGURATION_FIELD_TYPES = frozenset(
    {"string", "secret", "number", "boolean"}
)
_TOOL_ENTRY_TYPES = frozenset({"tools"})
_ENTRYPOINT_TYPES = frozenset(
    {"hooks", "channel_providers", "media_providers", "web_search_providers"}
)
_VERSION_TOKEN_PATTERN = re.compile(r"\d+|[A-Za-z]+|[^A-Za-z0-9]+")
_SUPPORTED_HOOK_EVENTS = frozenset(
    {
        "task.before_start",
        "task.completed",
        "task.failed",
        "task.waiting_input",
        "iteration.plan_updated",
        "iteration.answer_ready",
        "iteration.error",
        "iteration.before_tool_call",
        "iteration.after_tool_result",
    }
)
_SUPPORTED_HOOK_MODES = frozenset({"sync", "async"})


@dataclass(frozen=True)
class ExtensionBundleImportFile:
    """One uploaded file that belongs to a local extension bundle."""

    relative_path: str
    content: bytes


@dataclass(frozen=True)
class ExtensionInstallPreview:
    """Preview metadata shown before a local package is trusted and installed."""

    scope: str
    name: str
    version: str
    package_id: str
    display_name: str
    description: str
    source: str
    trust_status: str
    trust_source: str
    manifest_hash: str
    contribution_summary: dict[str, list[str]]
    contribution_items: list[dict[str, str]]
    permissions: dict[str, Any]
    existing_installation_id: int | None = None
    existing_installation_status: str | None = None
    identical_to_installed: bool = False
    requires_overwrite_confirmation: bool = False
    overwrite_blocked_reason: str = ""
    existing_reference_summary: ExtensionReferenceSummary | None = None


@dataclass(frozen=True)
class ExtensionReferenceSummary:
    """Counts of persisted references that still rely on one extension version."""

    extension_binding_count: int
    channel_binding_count: int
    media_provider_binding_count: int
    web_search_binding_count: int
    release_count: int
    test_snapshot_count: int
    saved_draft_count: int

    @property
    def binding_count(self) -> int:
        """Return the combined agent binding count across integration types."""
        return (
            self.extension_binding_count
            + self.channel_binding_count
            + self.media_provider_binding_count
            + self.web_search_binding_count
        )

    @property
    def has_references(self) -> bool:
        """Return whether any reference still relies on the extension."""
        return (
            self.binding_count > 0
            or self.release_count > 0
            or self.test_snapshot_count > 0
            or self.saved_draft_count > 0
        )

    def to_dict(self) -> dict[str, int]:
        """Serialize the summary to a JSON-friendly dictionary."""
        return {
            "extension_binding_count": self.extension_binding_count,
            "channel_binding_count": self.channel_binding_count,
            "media_provider_binding_count": self.media_provider_binding_count,
            "web_search_binding_count": self.web_search_binding_count,
            "binding_count": self.binding_count,
            "release_count": self.release_count,
            "test_snapshot_count": self.test_snapshot_count,
            "saved_draft_count": self.saved_draft_count,
        }


def _dump_json(payload: Any) -> str:
    """Serialize one payload into canonical compact JSON text."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hash_payload(payload: Any) -> str:
    """Return a stable hash for one canonical JSON payload."""
    return hashlib.sha256(_dump_json(payload).encode("utf-8")).hexdigest()


def _extensions_root() -> Path:
    """Return the local runtime-cache root for materialized extension versions.

    Why: extension artifacts remain the canonical source of truth. The unpacked
    Python package directory is only a backend-local runtime cache and should
    never be written into the active workspace or external POSIX provider root.
    """
    settings = get_settings()
    configured_root = settings.LOCAL_CACHE_ROOT
    if configured_root:
        root = Path(configured_root)
    else:
        root = Path(__file__).resolve().parent.parent.parent / "data" / ".local_cache"
    root = root / "extensions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _installation_version_root(*, scope: str, name: str, version: str) -> Path:
    """Return the local directory that owns one package version."""
    return _extensions_root() / scope / name / version


def _installation_runtime_root(*, scope: str, name: str, version: str) -> Path:
    """Return the extracted runtime directory for one package version."""
    return (
        _installation_version_root(
            scope=scope,
            name=name,
            version=version,
        )
        / "runtime"
    )


def _runtime_install_root_for_installation(
    installation: ExtensionInstallation,
) -> Path:
    """Return the derived runtime cache directory for one installation row."""
    return _installation_runtime_root(
        scope=installation.scope,
        name=installation.name,
        version=installation.version,
    )


def _package_id(scope: str, name: str) -> str:
    """Return the canonical npm-style package identifier."""
    return f"@{scope}/{name}"


def _local_trust_metadata(*, source: str) -> tuple[str, str]:
    """Return persisted trust metadata for one non-Hub installation source."""
    del source
    return ("trusted_local", "local_import")


def _build_contribution_summary(
    manifest: dict[str, Any],
) -> dict[str, list[str]]:
    """Extract normalized contribution names from one normalized manifest."""
    contributions = manifest.get("contributions", {})
    if not isinstance(contributions, dict):
        contributions = {}

    def _extract_names(
        raw_items: object,
        *,
        field_name: str,
    ) -> list[str]:
        if not isinstance(raw_items, list):
            return []

        names: list[str] = []
        seen_names: set[str] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            raw_name = item.get(field_name)
            if not isinstance(raw_name, str):
                continue
            normalized_name = raw_name.strip()
            if not normalized_name or normalized_name in seen_names:
                continue
            seen_names.add(normalized_name)
            names.append(normalized_name)
        return names

    return {
        "tools": _extract_names(contributions.get("tools"), field_name="name"),
        "skills": _extract_names(contributions.get("skills"), field_name="name"),
        "hooks": _extract_names(contributions.get("hooks"), field_name="name"),
        "chat_surfaces": _extract_names(
            contributions.get("chat_surfaces"),
            field_name="key",
        ),
        "channel_providers": _extract_names(
            contributions.get("channel_providers"),
            field_name="key",
        ),
        "media_providers": _extract_names(
            contributions.get("media_providers"),
            field_name="key",
        ),
        "web_search_providers": _extract_names(
            contributions.get("web_search_providers"),
            field_name="key",
        ),
    }


def _build_contribution_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract operator-facing contribution entries from one normalized manifest."""
    contributions = manifest.get("contributions", {})
    if not isinstance(contributions, dict):
        contributions = {}

    items: list[dict[str, Any]] = []
    contribution_order = [
        ("hooks", "hook"),
        ("chat_surfaces", "chat_surface"),
        ("channel_providers", "channel_provider"),
        ("media_providers", "media_provider"),
        ("web_search_providers", "web_search_provider"),
        ("tools", "tool"),
        ("skills", "skill"),
    ]
    for manifest_key, contribution_type in contribution_order:
        raw_items = contributions.get(manifest_key, [])
        if not isinstance(raw_items, list):
            continue
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            raw_name = (
                raw_item.get("display_name")
                if manifest_key == "chat_surfaces"
                else raw_item.get("name")
            )
            if manifest_key == "chat_surfaces" and not isinstance(raw_name, str):
                raw_name = raw_item.get("key")
            raw_description = raw_item.get("description")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            item: dict[str, Any] = {
                "type": contribution_type,
                "name": raw_name.strip(),
                "description": (
                    raw_description.strip() if isinstance(raw_description, str) else ""
                ),
            }
            if contribution_type == "chat_surface":
                raw_key = raw_item.get("key")
                item["key"] = (
                    raw_key.strip()
                    if isinstance(raw_key, str) and raw_key.strip()
                    else None
                )
                item["min_width"] = (
                    raw_item.get("min_width")
                    if isinstance(raw_item.get("min_width"), int)
                    else None
                )
            items.append(item)
    return items


def _normalize_configuration_schema(
    raw_configuration: object,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Validate and normalize one manifest ``configuration`` section."""
    normalized_sections = {
        "installation": {"fields": []},
        "binding": {"fields": []},
    }
    if raw_configuration is None:
        return normalized_sections
    if not isinstance(raw_configuration, dict):
        raise ValueError("manifest.json configuration must be an object.")

    for section_name in ("installation", "binding"):
        raw_section = raw_configuration.get(section_name)
        if raw_section is None:
            continue
        if not isinstance(raw_section, dict):
            raise ValueError(f"configuration.{section_name} must be an object.")
        raw_fields = raw_section.get("fields", [])
        if not isinstance(raw_fields, list):
            raise ValueError(
                f"configuration.{section_name}.fields must be a JSON array."
            )

        normalized_fields: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for index, raw_field in enumerate(raw_fields, start=1):
            if not isinstance(raw_field, dict):
                raise ValueError(
                    f"configuration.{section_name}.fields[{index}] must be an object."
                )

            raw_key = raw_field.get("key")
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise ValueError(
                    f"configuration.{section_name}.fields[{index}] must declare a key."
                )
            key = raw_key.strip()
            if key in seen_keys:
                raise ValueError(
                    f"Duplicate configuration field '{key}' in {section_name}."
                )
            seen_keys.add(key)

            raw_type = raw_field.get("type")
            if not isinstance(raw_type, str) or not raw_type.strip():
                raise ValueError(
                    f"configuration.{section_name}.fields[{index}] must declare a type."
                )
            field_type = raw_type.strip().lower()
            if field_type not in _SUPPORTED_CONFIGURATION_FIELD_TYPES:
                raise ValueError(
                    f"Unsupported configuration field type '{field_type}'."
                )

            raw_required = raw_field.get("required", False)
            if not isinstance(raw_required, bool):
                raise ValueError(
                    f"configuration.{section_name}.fields[{index}].required must be a boolean."
                )
            raw_label = raw_field.get("label")
            raw_description = raw_field.get("description")
            raw_placeholder = raw_field.get("placeholder")
            normalized_label = (
                raw_label.strip()
                if isinstance(raw_label, str) and raw_label.strip()
                else key
            )
            normalized_description = (
                raw_description.strip() if isinstance(raw_description, str) else ""
            )
            normalized_placeholder = (
                raw_placeholder.strip() if isinstance(raw_placeholder, str) else ""
            )

            normalized_field: dict[str, Any] = {
                "key": key,
                "label": normalized_label,
                "type": field_type,
                "description": normalized_description,
                "required": raw_required,
                "placeholder": normalized_placeholder,
            }
            if "default" in raw_field:
                normalized_field["default"] = raw_field.get("default")
            _normalize_config_value(
                value=normalized_field.get("default"),
                field=normalized_field,
                field_path=(f"configuration.{section_name}.fields[{index}].default"),
                allow_missing=True,
            )
            normalized_fields.append(normalized_field)

        normalized_sections[section_name] = {"fields": normalized_fields}
    return normalized_sections


def _normalize_config_value(
    *,
    value: Any,
    field: dict[str, Any],
    field_path: str,
    allow_missing: bool = False,
) -> Any:
    """Validate one configuration value against a normalized field schema."""
    if value is None:
        if allow_missing:
            return None
        raise ValueError(f"{field_path} is required.")

    field_type = str(field.get("type", "string"))
    if field_type in {"string", "secret"}:
        if not isinstance(value, str):
            raise ValueError(f"{field_path} must be a string.")
        return value
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{field_path} must be a boolean.")
        return value
    if field_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ValueError(f"{field_path} must be a number.")
        return value
    raise ValueError(f"{field_path} uses unsupported field type '{field_type}'.")


def _normalize_config_payload(
    *,
    schema_section: dict[str, Any],
    config: dict[str, Any] | None,
    field_path: str,
    enforce_required: bool = True,
) -> dict[str, Any]:
    """Validate one config payload against one normalized schema section."""
    normalized_config = config or {}
    if not isinstance(normalized_config, dict):
        raise ValueError(f"{field_path} must be a JSON object.")

    raw_fields = schema_section.get("fields", [])
    fields = raw_fields if isinstance(raw_fields, list) else []
    field_map = {
        str(field.get("key")): field
        for field in fields
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    }
    if not field_map:
        return normalized_config
    normalized_result: dict[str, Any] = {}

    for key in normalized_config:
        if key not in field_map:
            raise ValueError(f"{field_path}.{key} is not declared by the extension.")

    for key, field in field_map.items():
        if key in normalized_config:
            normalized_result[key] = _normalize_config_value(
                value=normalized_config[key],
                field=field,
                field_path=f"{field_path}.{key}",
            )
            continue

        if "default" in field:
            normalized_result[key] = _normalize_config_value(
                value=field.get("default"),
                field=field,
                field_path=f"{field_path}.{key}",
            )
            continue

        if enforce_required and bool(field.get("required", False)):
            raise ValueError(f"{field_path}.{key} is required.")

    return normalized_result


def _safe_relative_path(raw_path: str, *, field_name: str) -> PurePosixPath:
    """Validate one manifest-relative path and return its normalized form."""
    normalized = raw_path.strip().replace("\\", "/")
    if normalized == "":
        raise ValueError(f"{field_name} cannot be empty.")

    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute():
        raise ValueError(f"{field_name} must be relative to the extension root.")
    if any(part in {"", ".", ".."} for part in pure_path.parts):
        raise ValueError(f"{field_name} contains an unsafe relative path.")
    return pure_path


def _validate_extension_provider_key(
    *,
    provider_key: str,
    scope: str,
    field_name: str,
) -> str:
    """Validate one extension provider key against the owning package scope.

    Args:
        provider_key: Provider key exposed by the provider manifest.
        scope: Extension package scope from ``manifest.json``.
        field_name: User-facing field label for validation errors.

    Returns:
        The normalized provider key.

    Raises:
        ValueError: If the provider key is blank or does not follow
            ``scope@provider_name`` with a matching scope prefix.
    """
    normalized_key = provider_key.strip()
    if normalized_key == "":
        raise ValueError(f"{field_name} must not be empty.")

    if "@" not in normalized_key:
        raise ValueError(
            f"{field_name} must follow 'scope@provider_name' for extension providers."
        )

    provider_scope, provider_name = normalized_key.split("@", 1)
    if provider_scope != scope:
        raise ValueError(
            f"{field_name} must use the extension scope '{scope}' as its prefix."
        )
    if not _VALID_PROVIDER_LOCAL_NAME.fullmatch(provider_name):
        raise ValueError(
            f"{field_name} must use a valid provider name after '{scope}@'."
        )
    return normalized_key


def _normalize_logo_path(
    raw_logo_path: object,
    *,
    source_dir: Path,
) -> str | None:
    """Validate one optional extension logo asset declaration.

    Why: package logos should be easy for authors to add via a root-level
    convention, while still allowing larger packages to keep assets in a
    dedicated folder without weakening path-safety checks.
    """
    if raw_logo_path is None:
        for relative_path in _default_extension_logo_paths():
            candidate_path = source_dir.joinpath(*relative_path.parts)
            if candidate_path.is_file():
                return relative_path.as_posix()
        return None

    if not isinstance(raw_logo_path, str):
        raise ValueError("manifest.json logo_path must be a string.")

    relative_path = _safe_relative_path(raw_logo_path, field_name="logo_path")
    if relative_path.suffix.lower() not in _SUPPORTED_EXTENSION_LOGO_SUFFIXES:
        raise ValueError(
            "logo_path must point to a supported image file "
            "(.png, .jpg, .jpeg, .svg, or .webp)."
        )

    logo_path = source_dir.joinpath(*relative_path.parts)
    if not logo_path.is_file():
        raise ValueError(f"Logo path '{relative_path.as_posix()}' does not exist.")

    return relative_path.as_posix()


def _default_extension_logo_paths() -> list[PurePosixPath]:
    """Return the supported root-level extension logo conventions in priority order."""
    return [
        PurePosixPath(f"{_DEFAULT_EXTENSION_LOGO_BASENAME}{suffix}")
        for suffix in (".png", ".jpg", ".jpeg", ".svg", ".webp")
    ]


def _extract_bundle_extension_directory(
    *,
    bundle_name: str,
    files: list[ExtensionBundleImportFile],
    destination: Path,
) -> None:
    """Write uploaded bundle files into a temporary extension directory.

    Args:
        bundle_name: Root folder name selected by the user.
        files: Uploaded files with browser-provided relative paths.
        destination: Temporary directory that receives the extracted bundle.

    Raises:
        ValueError: If the bundle is empty, malformed, or missing manifest.json.
    """
    if not files:
        raise ValueError("Choose a local extension folder before importing.")

    destination.mkdir(parents=True, exist_ok=True)
    seen_paths: set[PurePosixPath] = set()

    for item in files:
        normalized = item.relative_path.strip().replace("\\", "/")
        if not normalized:
            raise ValueError("Imported bundle contains a file without a relative path.")

        path_parts = list(PurePosixPath(normalized).parts)
        if path_parts and path_parts[0] == bundle_name:
            path_parts = path_parts[1:]
        if not path_parts:
            raise ValueError("Imported bundle contains an invalid file path.")
        if any(part in {"", ".", ".."} for part in path_parts):
            raise ValueError("Imported bundle contains an unsafe file path.")

        relative_path = PurePosixPath(*path_parts)
        if relative_path in seen_paths:
            raise ValueError(
                f"Imported bundle contains duplicate file '{relative_path.as_posix()}'."
            )
        seen_paths.add(relative_path)

        target_path = destination.joinpath(*relative_path.parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(item.content)

    manifest_path = destination / _MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(
            f"Imported extension bundle must contain {_MANIFEST_FILENAME} at its top level."
        )


def _normalize_manifest(
    raw_manifest: dict[str, Any], *, source_dir: Path
) -> dict[str, Any]:
    """Validate and normalize one extension manifest."""
    schema_version = raw_manifest.get("schema_version")
    if schema_version != 1:
        raise ValueError("manifest.json schema_version must be 1.")

    scope = raw_manifest.get("scope")
    if not isinstance(scope, str) or not _VALID_EXTENSION_SCOPE.fullmatch(
        scope.strip()
    ):
        raise ValueError("manifest.json must declare a valid extension scope.")
    normalized_scope = scope.strip()

    name = raw_manifest.get("name")
    if not isinstance(name, str) or not _VALID_EXTENSION_NAME.fullmatch(name.strip()):
        raise ValueError("manifest.json must declare a valid extension name.")
    normalized_name = name.strip()

    version = raw_manifest.get("version")
    if not isinstance(version, str) or not _VALID_VERSION.fullmatch(version.strip()):
        raise ValueError("manifest.json must declare a valid extension version.")
    normalized_version = version.strip()

    display_name = raw_manifest.get("display_name")
    normalized_display_name = (
        display_name.strip()
        if isinstance(display_name, str) and display_name.strip()
        else _package_id(normalized_scope, normalized_name)
    )
    description = raw_manifest.get("description")
    normalized_description = description.strip() if isinstance(description, str) else ""
    normalized_logo_path = _normalize_logo_path(
        raw_manifest.get("logo_path"),
        source_dir=source_dir,
    )

    contributions = raw_manifest.get("contributions")
    if contributions is None:
        normalized_contributions: dict[str, list[dict[str, Any]]] = {}
    elif isinstance(contributions, dict):
        normalized_contributions = {}
        for key, raw_items in contributions.items():
            if not isinstance(key, str):
                raise ValueError("manifest.json contribution keys must be strings.")
            if not isinstance(raw_items, list):
                raise ValueError(f"Contribution '{key}' must be a JSON array.")

            normalized_items: list[dict[str, Any]] = []
            seen_names: set[str] = set()
            for index, raw_item in enumerate(raw_items, start=1):
                if not isinstance(raw_item, dict):
                    raise ValueError(
                        f"Contribution '{key}' item #{index} must be a JSON object."
                    )

                if key == "skills":
                    skill_name = raw_item.get("name")
                    skill_path = raw_item.get("path")
                    if not isinstance(skill_name, str) or not skill_name.strip():
                        raise ValueError("Skill contributions must declare a name.")
                    if not isinstance(skill_path, str):
                        raise ValueError("Skill contributions must declare a path.")
                    normalized_skill_name = skill_name.strip()
                    if normalized_skill_name in seen_names:
                        raise ValueError(
                            f"Duplicate skill contribution '{normalized_skill_name}'."
                        )
                    seen_names.add(normalized_skill_name)
                    relative_path = _safe_relative_path(
                        skill_path,
                        field_name=f"contributions.skills[{index}].path",
                    )
                    skill_dir = source_dir.joinpath(*relative_path.parts)
                    if not skill_dir.is_dir():
                        raise ValueError(
                            f"Skill path '{relative_path.as_posix()}' does not exist."
                        )
                    skill_markdown_path = skill_dir / _SKILL_MARKDOWN_FILENAME
                    if not skill_markdown_path.is_file():
                        raise ValueError(
                            f"Skill '{normalized_skill_name}' must contain "
                            f"{_SKILL_MARKDOWN_FILENAME}."
                        )
                    raw_source = skill_markdown_path.read_text(encoding="utf-8")
                    front_matter = parse_front_matter(raw_source)
                    skill_description = front_matter.get("description", "")
                    normalized_items.append(
                        {
                            "name": normalized_skill_name,
                            "path": relative_path.as_posix(),
                            "description": (
                                skill_description
                                if isinstance(skill_description, str)
                                else ""
                            ),
                        }
                    )
                    continue

                if key == "chat_surfaces":
                    surface_key = raw_item.get("key")
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(surface_key, str) or not surface_key.strip():
                        raise ValueError(
                            "Chat surface contributions must declare a key."
                        )
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            "Chat surface contributions must declare an entrypoint."
                        )
                    normalized_surface_key = surface_key.strip()
                    if normalized_surface_key in seen_names:
                        raise ValueError(
                            "Duplicate chat surface contribution "
                            f"'{normalized_surface_key}'."
                        )
                    seen_names.add(normalized_surface_key)
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=(f"contributions.chat_surfaces[{index}].entrypoint"),
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            "Chat surface entrypoint "
                            f"'{relative_entrypoint.as_posix()}' does not exist."
                        )
                    raw_display_name = raw_item.get("display_name")
                    raw_description = raw_item.get("description")
                    raw_placement = raw_item.get("placement")
                    raw_min_width = raw_item.get("min_width")
                    normalized_min_width: int | None = None
                    if raw_min_width is not None:
                        if not isinstance(raw_min_width, int) or raw_min_width <= 0:
                            raise ValueError(
                                "Chat surface min_width must be a positive integer."
                            )
                        normalized_min_width = raw_min_width
                    normalized_items.append(
                        {
                            "key": normalized_surface_key,
                            "display_name": (
                                raw_display_name.strip()
                                if isinstance(raw_display_name, str)
                                and raw_display_name.strip()
                                else normalized_surface_key
                            ),
                            "description": (
                                raw_description.strip()
                                if isinstance(raw_description, str)
                                else ""
                            ),
                            "entrypoint": relative_entrypoint.as_posix(),
                            "placement": (
                                raw_placement.strip()
                                if isinstance(raw_placement, str)
                                and raw_placement.strip()
                                else "right_dock"
                            ),
                            "min_width": normalized_min_width,
                        }
                    )
                    continue

                if key in _TOOL_ENTRY_TYPES:
                    tool_name = raw_item.get("name")
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(tool_name, str) or not tool_name.strip():
                        raise ValueError("Tool contributions must declare a name.")
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            "Tool contributions must declare an entrypoint."
                        )
                    normalized_tool_name = tool_name.strip()
                    if normalized_tool_name in seen_names:
                        raise ValueError(
                            f"Duplicate tool contribution '{normalized_tool_name}'."
                        )
                    seen_names.add(normalized_tool_name)
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=f"contributions.tools[{index}].entrypoint",
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            f"Tool entrypoint '{relative_entrypoint.as_posix()}' does not exist."
                        )
                    metadata = _load_tool_metadata_from_file(
                        tool_name=normalized_tool_name,
                        source_path=entrypoint_path,
                        module_key=(
                            "_pivot_extension_validate_"
                            f"{normalized_name}_{normalized_version}_{normalized_tool_name}"
                        ),
                    )
                    normalized_items.append(
                        {
                            "name": normalized_tool_name,
                            "entrypoint": relative_entrypoint.as_posix(),
                            "description": metadata.description,
                            "tool_type": metadata.tool_type,
                        }
                    )
                    continue

                if key == "channel_providers":
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            "Channel provider contributions must declare an entrypoint."
                        )
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=f"contributions.channel_providers[{index}].entrypoint",
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            f"Entrypoint '{relative_entrypoint.as_posix()}' does not exist."
                        )

                    provider = load_channel_provider_from_file(
                        source_path=entrypoint_path,
                        module_key=(
                            "_pivot_extension_validate_channel_"
                            f"{normalized_name}_{normalized_version}_{index}"
                        ),
                    )
                    if not isinstance(provider.manifest, ChannelManifest):
                        raise ValueError(
                            "Channel provider entrypoint must expose a ChannelManifest."
                        )
                    provider_key = _validate_extension_provider_key(
                        provider_key=provider.manifest.key,
                        scope=normalized_scope,
                        field_name=(
                            f"contributions.channel_providers[{index}].manifest.key"
                        ),
                    )
                    if provider_key in seen_names:
                        raise ValueError(
                            f"Duplicate channel provider contribution '{provider_key}'."
                        )
                    seen_names.add(provider_key)
                    normalized_items.append(
                        {
                            "key": provider_key,
                            "name": provider.manifest.name,
                            "description": provider.manifest.description,
                            "entrypoint": relative_entrypoint.as_posix(),
                            "transport_mode": provider.manifest.transport_mode,
                        }
                    )
                    continue

                if key == "media_providers":
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            "Media-generation provider contributions must declare "
                            "an entrypoint."
                        )
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=(
                            f"contributions.media_providers[{index}].entrypoint"
                        ),
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            f"Entrypoint '{relative_entrypoint.as_posix()}' does not exist."
                        )

                    provider = load_media_generation_provider_from_file(
                        source_path=entrypoint_path,
                        module_key=(
                            "_pivot_extension_validate_media_"
                            f"{normalized_name}_{normalized_version}_{index}"
                        ),
                    )
                    if not isinstance(
                        provider.manifest, MediaGenerationProviderManifest
                    ):
                        raise ValueError(
                            "Media-generation provider entrypoint must expose a "
                            "MediaGenerationProviderManifest."
                        )
                    provider_key = _validate_extension_provider_key(
                        provider_key=provider.manifest.key,
                        scope=normalized_scope,
                        field_name=(
                            "contributions.media_providers" f"[{index}].manifest.key"
                        ),
                    )
                    if provider_key in seen_names:
                        raise ValueError(
                            "Duplicate media-generation provider contribution "
                            f"'{provider_key}'."
                        )
                    seen_names.add(provider_key)
                    normalized_items.append(
                        {
                            "key": provider_key,
                            "name": provider.manifest.name,
                            "description": provider.manifest.description,
                            "entrypoint": relative_entrypoint.as_posix(),
                            "supported_operations": list(
                                provider.manifest.supported_operations
                            ),
                        }
                    )
                    continue

                if key == "web_search_providers":
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            "Web-search provider contributions must declare an entrypoint."
                        )
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=(
                            f"contributions.web_search_providers[{index}].entrypoint"
                        ),
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            f"Entrypoint '{relative_entrypoint.as_posix()}' does not exist."
                        )

                    provider = load_web_search_provider_from_file(
                        source_path=entrypoint_path,
                        module_key=(
                            "_pivot_extension_validate_web_search_"
                            f"{normalized_name}_{normalized_version}_{index}"
                        ),
                    )
                    if not isinstance(provider.manifest, WebSearchProviderManifest):
                        raise ValueError(
                            "Web-search provider entrypoint must expose a "
                            "WebSearchProviderManifest."
                        )
                    provider_key = _validate_extension_provider_key(
                        provider_key=provider.manifest.key,
                        scope=normalized_scope,
                        field_name=(
                            "contributions.web_search_providers"
                            f"[{index}].manifest.key"
                        ),
                    )
                    if provider_key in seen_names:
                        raise ValueError(
                            f"Duplicate web-search provider contribution '{provider_key}'."
                        )
                    seen_names.add(provider_key)
                    normalized_items.append(
                        {
                            "key": provider_key,
                            "name": provider.manifest.name,
                            "description": provider.manifest.description,
                            "entrypoint": relative_entrypoint.as_posix(),
                        }
                    )
                    continue

                if key in _ENTRYPOINT_TYPES:
                    entrypoint = raw_item.get("entrypoint")
                    if not isinstance(entrypoint, str):
                        raise ValueError(
                            f"Contribution '{key}' item #{index} must declare an entrypoint."
                        )
                    relative_entrypoint = _safe_relative_path(
                        entrypoint,
                        field_name=f"contributions.{key}[{index}].entrypoint",
                    )
                    entrypoint_path = source_dir.joinpath(*relative_entrypoint.parts)
                    if not entrypoint_path.is_file():
                        raise ValueError(
                            f"Entrypoint '{relative_entrypoint.as_posix()}' does not exist."
                        )

                    normalized_item: dict[str, Any] = {
                        entry_key: entry_value
                        for entry_key, entry_value in raw_item.items()
                        if isinstance(entry_key, str)
                    }
                    normalized_item["entrypoint"] = relative_entrypoint.as_posix()
                    if key == "hooks":
                        hook_name = raw_item.get("name")
                        if not isinstance(hook_name, str) or not hook_name.strip():
                            raise ValueError(
                                f"Contribution '{key}' item #{index} must declare a name."
                            )
                        hook_description = raw_item.get("description")
                        if (
                            not isinstance(hook_description, str)
                            or not hook_description.strip()
                        ):
                            raise ValueError(
                                f"Contribution '{key}' item #{index} must declare a description."
                            )
                        event_name = raw_item.get("event")
                        if not isinstance(event_name, str) or not event_name.strip():
                            raise ValueError(
                                f"Contribution '{key}' item #{index} must declare an event."
                            )
                        normalized_event_name = event_name.strip()
                        if normalized_event_name not in _SUPPORTED_HOOK_EVENTS:
                            raise ValueError(
                                "Unsupported hook event " f"'{normalized_event_name}'."
                            )

                        callable_name = raw_item.get("callable")
                        if (
                            not isinstance(callable_name, str)
                            or not callable_name.strip()
                        ):
                            raise ValueError(
                                f"Contribution '{key}' item #{index} must declare a callable."
                            )

                        mode = raw_item.get("mode")
                        normalized_mode = "sync"
                        if isinstance(mode, str) and mode.strip():
                            normalized_mode = mode.strip()
                        if normalized_mode not in _SUPPORTED_HOOK_MODES:
                            raise ValueError(
                                f"Hook mode '{normalized_mode}' is not supported."
                            )

                        normalized_item["name"] = hook_name.strip()
                        normalized_item["description"] = hook_description.strip()
                        normalized_item["event"] = normalized_event_name
                        normalized_item["callable"] = callable_name.strip()
                        normalized_item["mode"] = normalized_mode
                    normalized_items.append(normalized_item)
                    continue

                normalized_items.append(
                    {
                        entry_key: entry_value
                        for entry_key, entry_value in raw_item.items()
                        if isinstance(entry_key, str)
                    }
                )

            normalized_contributions[key] = normalized_items
    else:
        raise ValueError("manifest.json contributions must be an object.")

    permissions = raw_manifest.get("permissions")
    normalized_permissions = permissions if isinstance(permissions, dict) else {}

    compatibility = raw_manifest.get("compatibility")
    normalized_compatibility = compatibility if isinstance(compatibility, dict) else {}
    normalized_configuration = _normalize_configuration_schema(
        raw_manifest.get("configuration")
    )

    publisher = raw_manifest.get("publisher")
    normalized_publisher = publisher if isinstance(publisher, dict) else {}

    return {
        "schema_version": 1,
        "scope": normalized_scope,
        "name": normalized_name,
        "display_name": normalized_display_name,
        "version": normalized_version,
        "publisher": normalized_publisher,
        "description": normalized_description,
        "logo_path": normalized_logo_path,
        "api_version": (
            raw_manifest.get("api_version")
            if isinstance(raw_manifest.get("api_version"), str)
            else "1.x"
        ),
        "license": (
            raw_manifest.get("license")
            if isinstance(raw_manifest.get("license"), str)
            else None
        ),
        "homepage_url": (
            raw_manifest.get("homepage_url")
            if isinstance(raw_manifest.get("homepage_url"), str)
            else None
        ),
        "repository_url": (
            raw_manifest.get("repository_url")
            if isinstance(raw_manifest.get("repository_url"), str)
            else None
        ),
        "contributions": normalized_contributions,
        "configuration": normalized_configuration,
        "permissions": normalized_permissions,
        "compatibility": normalized_compatibility,
    }


def _load_tool_metadata_from_file(
    *,
    tool_name: str,
    source_path: Path,
    module_key: str,
) -> ToolMetadata:
    """Load one tool module and return its declared tool metadata."""
    spec = importlib.util.spec_from_file_location(module_key, source_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Unable to import tool entrypoint '{source_path}'.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:
        raise ValueError(f"Failed to load tool '{tool_name}': {exc}") from exc

    try:
        for _name, obj in inspect.getmembers(module, inspect.isfunction):
            metadata = getattr(obj, "__tool_metadata__", None)
            if metadata is not None and isinstance(metadata, ToolMetadata):
                if metadata.name != tool_name:
                    raise ValueError(
                        "Tool metadata name does not match manifest contribution name "
                        f"('{metadata.name}' != '{tool_name}')."
                    )
                return metadata
    finally:
        sys.modules.pop(module_key, None)

    raise ValueError(f"Tool entrypoint '{source_path}' does not export a tool.")


def _parse_name_allowlist(raw_json: str | None) -> set[str]:
    """Parse the existing JSON selection format used on agent rows."""
    if raw_json is None:
        return set()

    text = raw_json.strip()
    if text == "":
        return set()

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return set()

    if not isinstance(parsed, list):
        return set()

    return {item.strip() for item in parsed if isinstance(item, str) and item.strip()}


class ExtensionService:
    """Service class for extension package installation and binding resolution."""

    def __init__(self, db: Session) -> None:
        """Store the active database session."""
        self.db = db
        self.artifact_storage = ExtensionArtifactStorageService()

    def _user_by_username(self, username: str | None) -> User | None:
        """Return a persisted user by username when available."""
        if username is None:
            return None
        normalized_username = username.strip()
        if not normalized_username:
            return None
        return self.db.exec(
            select(User).where(User.username == normalized_username)
        ).first()

    def _grant_installer_edit(
        self,
        *,
        installation: ExtensionInstallation,
        installed_by: str | None,
    ) -> None:
        """Grant extension edit access to the installing user."""
        installer = self._user_by_username(installed_by)
        if installation.id is None or installer is None or installer.id is None:
            return
        installation.creator_id = installer.id
        installation.use_scope = "selected"
        self.db.add(installation)
        self.db.commit()
        self.db.refresh(installation)
        AccessService(self.db).grant_access(
            resource_type=ResourceType.EXTENSION,
            resource_id=installation.id,
            principal_type=PrincipalType.USER,
            principal_id=installer.id,
            access_level=AccessLevel.EDIT,
        )

    def _has_installation_access(
        self,
        *,
        user: User,
        installation: ExtensionInstallation,
        access_level: AccessLevel,
    ) -> bool:
        """Return whether a user can use or edit one installed extension."""
        return AccessService(self.db).has_resource_access(
            user=user,
            resource_type=ResourceType.EXTENSION,
            resource_id=installation.id,
            access_level=access_level,
            creator_user_id=installation.creator_id,
            use_scope=installation.use_scope,
        )

    def can_edit_installation(
        self,
        *,
        user: User,
        installation: ExtensionInstallation,
    ) -> bool:
        """Return whether a user can edit one installed extension."""
        return self._has_installation_access(
            user=user,
            installation=installation,
            access_level=AccessLevel.EDIT,
        )

    def installation_has_setup_fields(
        self,
        installation: ExtensionInstallation,
    ) -> bool:
        """Return whether one installation declares setup fields."""
        manifest = self._load_manifest_from_installation(installation)
        return bool(
            self._get_configuration_schema_section(
                manifest=manifest,
                section_name="installation",
            ).get("fields")
        )

    def set_installation_access(
        self,
        *,
        installation: ExtensionInstallation,
        use_scope: str,
        use_user_ids: set[int],
        use_group_ids: set[int],
        edit_user_ids: set[int],
        edit_group_ids: set[int],
    ) -> None:
        """Replace use/edit grants for one installed extension version."""
        if installation.id is None:
            raise ValueError(
                "Extension installation must be persisted before access can be updated."
            )
        if use_scope not in {"all", "selected"}:
            raise ValueError("use_scope must be 'all' or 'selected'.")

        creator_id = installation.creator_id
        if creator_id is not None:
            edit_user_ids = set(edit_user_ids)
            edit_user_ids.add(creator_id)
            if use_scope == "selected":
                use_user_ids = set(use_user_ids)
                use_user_ids.add(creator_id)

        installation.use_scope = use_scope
        installation.updated_at = datetime.now(UTC)
        self.db.add(installation)

        access_service = AccessService(self.db)
        access_service._replace_resource_grants_in_session(
            resource_type=ResourceType.EXTENSION,
            resource_id=installation.id,
            access_level=AccessLevel.USE,
            user_ids=use_user_ids if use_scope == "selected" else set(),
            group_ids=use_group_ids if use_scope == "selected" else set(),
        )
        access_service._replace_resource_grants_in_session(
            resource_type=ResourceType.EXTENSION,
            resource_id=installation.id,
            access_level=AccessLevel.EDIT,
            user_ids=edit_user_ids,
            group_ids=edit_group_ids,
        )
        self.db.commit()
        self.db.refresh(installation)

    def _ensure_materialized_installation_root(
        self,
        installation: ExtensionInstallation,
    ) -> Path:
        """Return a local runtime directory for one installed extension.

        Why: persisted artifacts are now the source of truth, so runtime code
        must be able to recreate the extracted package directory after local
        cache cleanup or pod restarts.
        """
        target_dir = _runtime_install_root_for_installation(installation)
        return self.artifact_storage.ensure_materialized_directory(
            artifact_key=installation.artifact_key,
            target_dir=target_dir,
        )

    def get_runtime_install_root(
        self,
        installation: ExtensionInstallation,
    ) -> Path:
        """Return the derived materialization path for one installation."""
        return _runtime_install_root_for_installation(installation)

    def list_installations(self) -> list[ExtensionInstallation]:
        """Return installed extension versions ordered for display."""
        statement = select(ExtensionInstallation).order_by(
            col(ExtensionInstallation.scope).asc(),
            col(ExtensionInstallation.name).asc(),
            col(ExtensionInstallation.version).desc(),
        )
        return list(self.db.exec(statement).all())

    def list_visible_installations(self, user: User) -> list[ExtensionInstallation]:
        """Return installed extension versions visible to one Studio user."""
        return [
            installation
            for installation in self.list_installations()
            if self._has_installation_access(
                user=user,
                installation=installation,
                access_level=AccessLevel.USE,
            )
        ]

    def is_package_usable_by_user(self, *, user: User, package_id: str) -> bool:
        """Return whether a user can use at least one active version of a package."""
        return any(
            installation.status == "active"
            and installation.package_id == package_id
            and self._has_installation_access(
                user=user,
                installation=installation,
                access_level=AccessLevel.USE,
            )
            for installation in self.list_installations()
        )

    def list_packages(self) -> list[dict[str, Any]]:
        """Return installed extensions grouped by package name."""
        grouped: dict[str, list[ExtensionInstallation]] = {}
        for installation in self.list_installations():
            grouped.setdefault(installation.package_id, []).append(installation)

        packages: list[dict[str, Any]] = []
        for package_id, installations in grouped.items():
            ordered_installations = sorted(
                installations,
                key=lambda item: self._version_sort_key(item.version),
                reverse=True,
            )
            latest = ordered_installations[0]
            packages.append(
                {
                    "package_id": package_id,
                    "scope": latest.scope,
                    "name": latest.name,
                    "display_name": latest.display_name,
                    "description": latest.description,
                    "readme_markdown": self._read_installation_readme_markdown(latest),
                    "latest_version": latest.version,
                    "active_version_count": sum(
                        1 for item in ordered_installations if item.status == "active"
                    ),
                    "disabled_version_count": sum(
                        1 for item in ordered_installations if item.status == "disabled"
                    ),
                    "versions": ordered_installations,
                }
            )

        return sorted(packages, key=lambda item: str(item["package_id"]))

    def list_visible_packages(self, user: User) -> list[dict[str, Any]]:
        """Return installed extension packages visible to one Studio user."""
        grouped: dict[str, list[ExtensionInstallation]] = {}
        for installation in self.list_visible_installations(user):
            grouped.setdefault(installation.package_id, []).append(installation)

        packages: list[dict[str, Any]] = []
        for package_id, installations in grouped.items():
            ordered_installations = sorted(
                installations,
                key=lambda item: self._version_sort_key(item.version),
                reverse=True,
            )
            latest = ordered_installations[0]
            packages.append(
                {
                    "package_id": package_id,
                    "scope": latest.scope,
                    "name": latest.name,
                    "display_name": latest.display_name,
                    "description": latest.description,
                    "readme_markdown": self._read_installation_readme_markdown(latest),
                    "latest_version": latest.version,
                    "active_version_count": sum(
                        1 for item in ordered_installations if item.status == "active"
                    ),
                    "disabled_version_count": sum(
                        1 for item in ordered_installations if item.status == "disabled"
                    ),
                    "versions": ordered_installations,
                }
            )

        return sorted(packages, key=lambda item: str(item["package_id"]))

    def _read_installation_readme_markdown(
        self,
        installation: ExtensionInstallation,
    ) -> str:
        """Return root-level README markdown for one installation, if present.

        Why: extension detail pages should explain what one package does without
        forcing operators to inspect the on-disk package contents manually.
        """
        install_root = self._ensure_materialized_installation_root(installation)
        readme_path = install_root / _README_MARKDOWN_FILENAME
        if not readme_path.is_file():
            return ""
        try:
            return readme_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def get_installation_logo_path(
        self,
        installation: ExtensionInstallation,
    ) -> Path | None:
        """Return one installation-scoped logo asset when the package declares one.

        Why: UI surfaces should consume a stable package logo URL without
        knowing whether the author relied on the explicit manifest field or the
        root-level ``logo.png`` convention.
        """
        install_root = self._ensure_materialized_installation_root(installation)
        manifest: dict[str, Any] = {}
        try:
            parsed_manifest = json.loads(installation.manifest_json)
        except json.JSONDecodeError:
            parsed_manifest = {}
        if isinstance(parsed_manifest, dict):
            manifest = parsed_manifest

        logo_candidates: list[PurePosixPath] = []
        raw_logo_path = manifest.get("logo_path")
        if isinstance(raw_logo_path, str) and raw_logo_path.strip():
            with suppress(ValueError):
                logo_candidates.append(
                    _safe_relative_path(raw_logo_path, field_name="logo_path")
                )
        for default_logo_path in _default_extension_logo_paths():
            if default_logo_path not in logo_candidates:
                logo_candidates.append(default_logo_path)

        for relative_path in logo_candidates:
            if relative_path.suffix.lower() not in _SUPPORTED_EXTENSION_LOGO_SUFFIXES:
                continue
            candidate_path = install_root.joinpath(*relative_path.parts)
            if candidate_path.is_file():
                return candidate_path
        return None

    def get_installation_logo_url(
        self,
        installation: ExtensionInstallation,
    ) -> str | None:
        """Return one versioned API URL for an installation logo, if present.

        Why: local SQLite development can recycle integer primary keys after
        rows or the whole database are removed. Versioning the image URL with
        the persisted artifact digest prevents browsers from showing an older
        extension's cached logo when a new installation later receives the
        same numeric id.
        """
        installation_id = installation.id or 0
        if installation_id <= 0:
            return None
        if self.get_installation_logo_path(installation) is None:
            return None
        version_token = installation.artifact_digest or installation.manifest_hash
        if version_token:
            return (
                f"/api/extensions/installations/{installation_id}/logo"
                f"?v={version_token}"
            )
        return f"/api/extensions/installations/{installation_id}/logo"

    def get_installation_contribution_items(
        self,
        installation: ExtensionInstallation,
    ) -> list[dict[str, str]]:
        """Return operator-facing contribution items for one installation."""
        return _build_contribution_items(
            self._load_manifest_from_installation(installation)
        )

    def list_agent_package_choices(
        self,
        agent_id: int,
        user: User,
    ) -> list[dict[str, Any]]:
        """Return package-level extension choices for one agent."""
        packages = self.list_visible_packages(user)
        bindings = self.list_agent_bindings(agent_id)
        installations = {
            installation.id or 0: installation
            for installation in self.list_visible_installations(user)
        }
        bindings_by_package: dict[str, AgentExtensionBinding] = {}

        for binding in bindings:
            installation = installations.get(binding.extension_installation_id)
            if installation is None:
                continue
            bindings_by_package[installation.package_id] = binding

        results: list[dict[str, Any]] = []
        for package in packages:
            package_id = package.get("package_id")
            if not isinstance(package_id, str):
                continue

            selected_binding = bindings_by_package.get(package_id)
            selected_version = None
            if selected_binding is not None:
                selected_installation = installations.get(
                    selected_binding.extension_installation_id
                )
                if selected_installation is not None:
                    selected_version = selected_installation.version

            latest_version = package.get("latest_version")
            results.append(
                {
                    **package,
                    "selected_binding": selected_binding,
                    "has_update_available": (
                        isinstance(latest_version, str)
                        and isinstance(selected_version, str)
                        and latest_version != selected_version
                    ),
                }
            )

        return results

    def get_installation(self, installation_id: int) -> ExtensionInstallation | None:
        """Return one installed extension version by primary key."""
        return self.db.get(ExtensionInstallation, installation_id)

    def get_installation_by_package_version(
        self,
        *,
        package_id: str,
        version: str,
    ) -> ExtensionInstallation | None:
        """Return one installed extension by canonical package id and version."""
        scope, name = self._parse_package_id(package_id)
        statement = select(ExtensionInstallation).where(
            ExtensionInstallation.scope == scope,
            ExtensionInstallation.name == name,
            ExtensionInstallation.version == version,
        )
        return self.db.exec(statement).first()

    def preview_from_path(
        self,
        *,
        source_dir: str | Path,
        source: str = "manual",
    ) -> ExtensionInstallPreview:
        """Validate one local package and return its pre-install trust preview."""
        package_root = Path(source_dir).expanduser().resolve()
        if not package_root.is_dir():
            raise ValueError("source_dir must point to an existing directory.")

        manifest_path = package_root / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise ValueError(f"Extension root must contain {_MANIFEST_FILENAME}.")

        try:
            raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("manifest.json is not valid JSON.") from exc
        if not isinstance(raw_manifest, dict):
            raise ValueError("manifest.json must contain a JSON object.")

        normalized_manifest = _normalize_manifest(raw_manifest, source_dir=package_root)
        manifest_hash = _hash_payload(normalized_manifest)
        existing = self.db.exec(
            select(ExtensionInstallation).where(
                ExtensionInstallation.scope == normalized_manifest["scope"],
                ExtensionInstallation.name == normalized_manifest["name"],
                ExtensionInstallation.version == normalized_manifest["version"],
            )
        ).first()
        existing_reference_summary: ExtensionReferenceSummary | None = None
        identical_to_installed = False
        requires_overwrite_confirmation = False
        overwrite_blocked_reason = ""
        existing_installation_id: int | None = None
        existing_installation_status: str | None = None
        if existing is not None:
            existing_installation_id = existing.id
            existing_installation_status = existing.status
            identical_to_installed = existing.manifest_hash == manifest_hash
            if not identical_to_installed:
                existing_reference_summary = self.get_reference_summary(
                    installation_id=existing.id or 0
                )
                if existing_reference_summary.has_references:
                    overwrite_blocked_reason = (
                        "This installed version is still referenced by agent "
                        "bindings, releases, test snapshots, or saved drafts. "
                        "Remove those references or bump the extension version "
                        "before replacing it."
                    )
                else:
                    requires_overwrite_confirmation = True
        return ExtensionInstallPreview(
            scope=normalized_manifest["scope"],
            name=normalized_manifest["name"],
            version=normalized_manifest["version"],
            package_id=_package_id(
                normalized_manifest["scope"],
                normalized_manifest["name"],
            ),
            display_name=normalized_manifest["display_name"],
            description=normalized_manifest["description"],
            source=source,
            trust_status="unverified",
            trust_source="local_import",
            manifest_hash=manifest_hash,
            contribution_summary=_build_contribution_summary(normalized_manifest),
            contribution_items=_build_contribution_items(normalized_manifest),
            permissions=(
                normalized_manifest["permissions"]
                if isinstance(normalized_manifest.get("permissions"), dict)
                else {}
            ),
            existing_installation_id=existing_installation_id,
            existing_installation_status=existing_installation_status,
            identical_to_installed=identical_to_installed,
            requires_overwrite_confirmation=requires_overwrite_confirmation,
            overwrite_blocked_reason=overwrite_blocked_reason,
            existing_reference_summary=existing_reference_summary,
        )

    def set_installation_status(
        self,
        *,
        installation_id: int,
        status: str,
    ) -> ExtensionInstallation:
        """Update one installed extension version status.

        Args:
            installation_id: Installed extension primary key.
            status: Desired installation status.

        Returns:
            Updated installation row.
        """
        installation = self.db.get(ExtensionInstallation, installation_id)
        if installation is None:
            raise ValueError("Installed extension version not found.")
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "disabled"}:
            raise ValueError("status must be either 'active' or 'disabled'.")

        provider_registry = ProviderRegistryService(self.db)
        if normalized_status == "active":
            conflicts = provider_registry.analyze_manifest_provider_conflicts(
                manifest=self._load_manifest_from_installation(installation),
                excluding_installation_id=installation.id,
            )
            if conflicts:
                raise ValueError(
                    self._format_provider_conflict_message(
                        action="enable",
                        conflicts=conflicts,
                    )
                )
        elif (
            installation.status == "active"
            and provider_registry.count_installation_provider_binding_references(
                installation
            )
            > 0
        ):
            raise ValueError(
                "Remove configured channel or web-search bindings before disabling "
                "this extension."
            )

        installation.status = normalized_status
        installation.updated_at = datetime.now(UTC)
        self.db.add(installation)
        self.db.commit()
        self.db.refresh(installation)
        return installation

    def install_from_path(
        self,
        *,
        source_dir: str | Path,
        installed_by: str | None,
        source: str = "manual",
        trust_confirmed: bool,
        overwrite_confirmed: bool = False,
    ) -> ExtensionInstallation:
        """Validate and install one extension folder into the workspace registry.

        Args:
            source_dir: Absolute or relative path to the source package folder.
            installed_by: Username that initiated the installation.
            source: Installation source label such as ``manual`` or ``bundle``.
            trust_confirmed: Whether the operator explicitly trusted the local
                package before installation.
            overwrite_confirmed: Whether the operator explicitly approved
                replacing one already-installed package with the same
                ``scope/name/version`` but different contents.

        Returns:
            Persisted installation row.

        Raises:
            ValueError: If the package layout or manifest is invalid.
        """
        if not trust_confirmed:
            raise ValueError(
                "Local extensions must be explicitly trusted before installation."
            )

        package_root = Path(source_dir).expanduser().resolve()
        preview = self.preview_from_path(source_dir=package_root, source=source)
        normalized_manifest = json.loads(
            (package_root / _MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        if not isinstance(normalized_manifest, dict):
            raise ValueError("manifest.json must contain a JSON object.")
        normalized_manifest = _normalize_manifest(
            normalized_manifest, source_dir=package_root
        )
        manifest_hash = preview.manifest_hash
        provider_registry = ProviderRegistryService(self.db)
        provider_conflicts = provider_registry.analyze_manifest_provider_conflicts(
            manifest=normalized_manifest
        )
        builtin_conflicts = [
            conflict for conflict in provider_conflicts if conflict.source == "builtin"
        ]
        if builtin_conflicts:
            raise ValueError(
                self._format_provider_conflict_message(
                    action="install",
                    conflicts=builtin_conflicts,
                )
            )

        existing = self.db.exec(
            select(ExtensionInstallation).where(
                ExtensionInstallation.scope == normalized_manifest["scope"],
                ExtensionInstallation.name == normalized_manifest["name"],
                ExtensionInstallation.version == normalized_manifest["version"],
            )
        ).first()
        should_overwrite_existing = False
        if existing is not None:
            if existing.manifest_hash != manifest_hash:
                references = self.get_reference_summary(
                    installation_id=existing.id or 0
                )
                if references.has_references:
                    raise ValueError(
                        "This installed version is still referenced by agent "
                        "bindings, releases, test snapshots, or saved drafts. "
                        "Remove those references or bump the extension version "
                        "before replacing it."
                    )
                if not overwrite_confirmed:
                    raise ValueError(
                        "A different extension payload is already installed at "
                        f"{existing.package_id}@{existing.version}. Confirm "
                        "overwrite to replace this version."
                    )
                should_overwrite_existing = True
            else:
                self._ensure_materialized_installation_root(existing)
                self._grant_installer_edit(
                    installation=existing,
                    installed_by=installed_by,
                )
                return existing

        version_root = _installation_version_root(
            scope=normalized_manifest["scope"],
            name=normalized_manifest["name"],
            version=normalized_manifest["version"],
        )
        install_root = _installation_runtime_root(
            scope=normalized_manifest["scope"],
            name=normalized_manifest["name"],
            version=normalized_manifest["version"],
        )
        if version_root.exists() and not should_overwrite_existing:
            # Local package directories are runtime caches plus persisted
            # artifacts. If the database record is gone, treat the leftover
            # directory as an orphaned cache and recreate it from scratch.
            shutil.rmtree(version_root, ignore_errors=True)
        stored_artifact = self.artifact_storage.store_directory(
            source_dir=package_root,
            scope=normalized_manifest["scope"],
            name=normalized_manifest["name"],
            version=normalized_manifest["version"],
            manifest_hash=manifest_hash,
        )
        install_root.parent.mkdir(parents=True, exist_ok=True)
        if should_overwrite_existing:
            shutil.rmtree(install_root, ignore_errors=True)
        try:
            self.artifact_storage.materialize_to_directory(
                artifact_key=stored_artifact.artifact_key,
                target_dir=install_root,
            )
        except Exception:
            shutil.rmtree(version_root, ignore_errors=True)
            self.artifact_storage.delete_artifact(
                artifact_key=stored_artifact.artifact_key
            )
            raise

        now = datetime.now(UTC)
        trust_status, trust_source = _local_trust_metadata(source=source)
        if existing is not None and should_overwrite_existing:
            old_artifact_key = existing.artifact_key
            existing.display_name = normalized_manifest["display_name"]
            existing.description = normalized_manifest["description"]
            existing.manifest_json = _dump_json(normalized_manifest)
            existing.manifest_hash = manifest_hash
            existing.artifact_storage_backend = stored_artifact.storage_backend
            existing.artifact_key = stored_artifact.artifact_key
            existing.artifact_digest = stored_artifact.artifact_digest
            existing.artifact_size_bytes = stored_artifact.size_bytes
            existing.install_root = str(install_root.resolve())
            existing.source = source
            existing.trust_status = trust_status
            existing.trust_source = trust_source
            existing.installed_by = installed_by
            existing.updated_at = now
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            self.artifact_storage.delete_artifact(artifact_key=old_artifact_key)
            self._grant_installer_edit(
                installation=existing,
                installed_by=installed_by,
            )
            return existing

        installation = ExtensionInstallation(
            scope=normalized_manifest["scope"],
            name=normalized_manifest["name"],
            version=normalized_manifest["version"],
            display_name=normalized_manifest["display_name"],
            description=normalized_manifest["description"],
            manifest_json=_dump_json(normalized_manifest),
            manifest_hash=manifest_hash,
            artifact_storage_backend=stored_artifact.storage_backend,
            artifact_key=stored_artifact.artifact_key,
            artifact_digest=stored_artifact.artifact_digest,
            artifact_size_bytes=stored_artifact.size_bytes,
            install_root=str(install_root.resolve()),
            config_json=_dump_json(
                _normalize_config_payload(
                    schema_section=self._get_configuration_schema_section(
                        manifest=normalized_manifest,
                        section_name="installation",
                    ),
                    config={},
                    field_path="installation_config",
                    enforce_required=False,
                )
            ),
            source=source,
            trust_status=trust_status,
            trust_source=trust_source,
            hub_scope=None,
            hub_package_id=None,
            hub_package_version_id=None,
            hub_artifact_digest=None,
            installed_by=installed_by,
            status="disabled" if provider_conflicts else "active",
            created_at=now,
            updated_at=now,
        )
        try:
            self.db.add(installation)
            self.db.commit()
            self.db.refresh(installation)
        except Exception:
            self.db.rollback()
            shutil.rmtree(version_root, ignore_errors=True)
            self.artifact_storage.delete_artifact(
                artifact_key=stored_artifact.artifact_key
            )
            raise
        self._grant_installer_edit(
            installation=installation,
            installed_by=installed_by,
        )
        return installation

    def get_installation_configuration_state(
        self,
        *,
        installation_id: int,
    ) -> dict[str, Any]:
        """Return one installation's declared configuration schema and values."""
        installation = self._get_installation_or_raise(installation_id)
        manifest = self._load_manifest_from_installation(installation)
        return {
            "installation_id": installation.id or 0,
            "package_id": installation.package_id,
            "version": installation.version,
            "schema": manifest.get("configuration", {}),
            "config": self._parse_config(installation.config_json),
        }

    def update_installation_config(
        self,
        *,
        installation_id: int,
        config: dict[str, Any],
    ) -> ExtensionInstallation:
        """Validate and persist installation-scoped configuration values."""
        installation = self._get_installation_or_raise(installation_id)
        manifest = self._load_manifest_from_installation(installation)
        normalized_config = _normalize_config_payload(
            schema_section=self._get_configuration_schema_section(
                manifest=manifest,
                section_name="installation",
            ),
            config=config,
            field_path="installation_config",
        )
        installation.config_json = _dump_json(normalized_config)
        installation.updated_at = datetime.now(UTC)
        self.db.add(installation)
        self.db.commit()
        self.db.refresh(installation)
        return installation

    def install_bundle(
        self,
        *,
        bundle_name: str,
        files: list[ExtensionBundleImportFile],
        installed_by: str | None,
        trust_confirmed: bool,
        overwrite_confirmed: bool = False,
    ) -> ExtensionInstallation:
        """Install one extension bundle uploaded from the local machine.

        Args:
            bundle_name: Root folder name selected by the user.
            files: Uploaded bundle files with relative paths.
            installed_by: Username that initiated the installation.

        Returns:
            Persisted installation row.
        """
        with TemporaryDirectory(prefix="pivot-extension-bundle-") as tmp_root:
            extracted_dir = Path(tmp_root) / bundle_name
            _extract_bundle_extension_directory(
                bundle_name=bundle_name,
                files=files,
                destination=extracted_dir,
            )
            return self.install_from_path(
                source_dir=extracted_dir,
                installed_by=installed_by,
                source="bundle",
                trust_confirmed=trust_confirmed,
                overwrite_confirmed=overwrite_confirmed,
            )

    def preview_bundle(
        self,
        *,
        bundle_name: str,
        files: list[ExtensionBundleImportFile],
    ) -> ExtensionInstallPreview:
        """Validate one uploaded bundle and return its pre-install trust preview."""
        with TemporaryDirectory(prefix="pivot-extension-bundle-preview-") as tmp_root:
            extracted_dir = Path(tmp_root) / bundle_name
            _extract_bundle_extension_directory(
                bundle_name=bundle_name,
                files=files,
                destination=extracted_dir,
            )
            return self.preview_from_path(source_dir=extracted_dir, source="bundle")

    def list_agent_bindings(self, agent_id: int) -> list[AgentExtensionBinding]:
        """Return every extension binding configured for one agent."""
        statement = (
            select(AgentExtensionBinding)
            .where(AgentExtensionBinding.agent_id == agent_id)
            .order_by(
                col(AgentExtensionBinding.priority).asc(),
                col(AgentExtensionBinding.extension_installation_id).asc(),
            )
        )
        return list(self.db.exec(statement).all())

    def upsert_agent_binding(
        self,
        *,
        agent_id: int,
        extension_installation_id: int,
        enabled: bool,
        priority: int = 100,
        config: dict[str, Any] | None = None,
    ) -> AgentExtensionBinding:
        """Create or update one agent-extension binding."""
        installation = self._get_installation_or_raise(extension_installation_id)
        manifest = self._load_manifest_from_installation(installation)
        self._validate_installation_binding_state(
            installation=installation,
            enabled=enabled,
        )
        self._validate_single_package_binding(
            agent_id=agent_id,
            installation=installation,
            current_extension_installation_id=extension_installation_id,
        )

        normalized_config = _normalize_config_payload(
            schema_section=self._get_configuration_schema_section(
                manifest=manifest,
                section_name="binding",
            ),
            config=config or {},
            field_path="binding_config",
        )
        statement = select(AgentExtensionBinding).where(
            AgentExtensionBinding.agent_id == agent_id,
            AgentExtensionBinding.extension_installation_id
            == extension_installation_id,
        )
        binding = self.db.exec(statement).first()
        now = datetime.now(UTC)
        is_new_binding = binding is None
        if binding is None:
            binding = AgentExtensionBinding(
                agent_id=agent_id,
                extension_installation_id=extension_installation_id,
                enabled=enabled,
                priority=priority,
                config_json=_dump_json(normalized_config),
                created_at=now,
                updated_at=now,
            )
        else:
            binding.enabled = enabled
            binding.priority = priority
            binding.config_json = _dump_json(normalized_config)
            binding.updated_at = now

        self.db.add(binding)
        self.db.flush()
        if is_new_binding:
            self._seed_agent_provider_bindings(
                agent_id=agent_id,
                installation=installation,
                now=now,
            )
        try:
            self.validate_agent_bindings(agent_id=agent_id)
        except Exception:
            self.db.rollback()
            raise
        self.db.commit()
        self.db.refresh(binding)
        return binding

    def replace_agent_bindings(
        self,
        *,
        agent_id: int,
        bindings: list[dict[str, Any]],
    ) -> list[AgentExtensionBinding]:
        """Replace one agent's full extension binding set atomically.

        Args:
            agent_id: Agent whose binding set should be replaced.
            bindings: Desired binding rows expressed as dictionaries.

        Returns:
            Persisted bindings after replacement, ordered by priority.

        Raises:
            ValueError: If the payload is malformed or references invalid
                installations.
        """
        existing_bindings = {
            binding.extension_installation_id: binding
            for binding in self.list_agent_bindings(agent_id)
        }
        requested_ids: set[int] = set()
        requested_package_names: set[str] = set()
        requested_installations: dict[int, ExtensionInstallation] = {}
        now = datetime.now(UTC)
        try:
            for item in bindings:
                installation_id = item.get("extension_installation_id")
                if not isinstance(installation_id, int) or installation_id <= 0:
                    raise ValueError(
                        "Each binding must declare extension_installation_id."
                    )
                if installation_id in requested_ids:
                    raise ValueError(
                        "Each extension_installation_id may appear only once in bindings."
                    )
                requested_ids.add(installation_id)

                enabled = bool(item.get("enabled", True))
                priority = item.get("priority", 100)
                if not isinstance(priority, int):
                    raise ValueError("Each binding priority must be an integer.")
                config = item.get("config", {})
                if not isinstance(config, dict):
                    raise ValueError("Each binding config must be a JSON object.")

                installation = self._get_installation_or_raise(installation_id)
                manifest = self._load_manifest_from_installation(installation)
                self._validate_installation_binding_state(
                    installation=installation,
                    enabled=enabled,
                )
                if installation.package_id in requested_package_names:
                    raise ValueError(
                        "Each extension package may appear only once in bindings."
                    )
                requested_package_names.add(installation.package_id)
                requested_installations[installation_id] = installation
                normalized_config = _normalize_config_payload(
                    schema_section=self._get_configuration_schema_section(
                        manifest=manifest,
                        section_name="binding",
                    ),
                    config=config,
                    field_path="binding_config",
                )

                binding = existing_bindings.get(installation_id)
                if binding is None:
                    binding = AgentExtensionBinding(
                        agent_id=agent_id,
                        extension_installation_id=installation_id,
                        created_at=now,
                    )

                binding.enabled = enabled
                binding.priority = priority
                binding.config_json = _dump_json(normalized_config)
                binding.updated_at = now
                self.db.add(binding)
                self._seed_agent_provider_bindings(
                    agent_id=agent_id,
                    installation=installation,
                    now=now,
                )

            preserved_provider_keys = self._build_provider_key_sets(
                requested_installations.values()
            )
            for installation_id, binding in existing_bindings.items():
                if installation_id not in requested_ids:
                    installation = self._get_installation_or_raise(installation_id)
                    self._delete_agent_contributions_for_installation(
                        agent_id=agent_id,
                        installation=installation,
                        preserve_provider_keys=preserved_provider_keys,
                    )
                    self.db.delete(binding)

            self.db.flush()
            self.validate_agent_bindings(agent_id=agent_id)
        except Exception:
            self.db.rollback()
            raise
        self.db.commit()
        return self.list_agent_bindings(agent_id)

    def delete_agent_binding(
        self,
        *,
        agent_id: int,
        extension_installation_id: int,
    ) -> None:
        """Delete one agent-extension binding.

        Args:
            agent_id: Agent that owns the binding.
            extension_installation_id: Installed extension version referenced by
                the binding.

        Raises:
            ValueError: If the binding does not exist.
        """
        statement = select(AgentExtensionBinding).where(
            AgentExtensionBinding.agent_id == agent_id,
            AgentExtensionBinding.extension_installation_id
            == extension_installation_id,
        )
        binding = self.db.exec(statement).first()
        if binding is None:
            raise ValueError("Agent extension binding not found.")

        installation = self._get_installation_or_raise(extension_installation_id)
        self._delete_agent_contributions_for_installation(
            agent_id=agent_id,
            installation=installation,
        )
        self.db.delete(binding)
        self.db.commit()

    def uninstall_installation(
        self,
        *,
        installation_id: int,
    ) -> dict[str, Any]:
        """Uninstall one extension version with reference-aware fallback.

        If bindings or pinned snapshots still reference the package version, the
        installation is only logically uninstalled by disabling it and disabling
        active bindings. Physical deletion happens only when the installation is
        fully unreferenced.
        """
        installation = self.db.get(ExtensionInstallation, installation_id)
        if installation is None:
            raise ValueError("Installed extension version not found.")
        if (
            ProviderRegistryService(
                self.db
            ).count_installation_provider_binding_references(installation)
            > 0
        ):
            raise ValueError(
                "Remove configured channel or web-search bindings before "
                "uninstalling this extension."
            )

        references = self.get_reference_summary(installation_id=installation_id)
        now = datetime.now(UTC)
        if references.has_references:
            installation.status = "disabled"
            installation.updated_at = now
            self.db.add(installation)

            binding_statement = select(AgentExtensionBinding).where(
                AgentExtensionBinding.extension_installation_id == installation_id
            )
            for binding in self.db.exec(binding_statement).all():
                if binding.enabled:
                    binding.enabled = False
                    binding.updated_at = now
                    self.db.add(binding)

            self.db.commit()
            self.db.refresh(installation)
            return {
                "mode": "logical",
                "installation": installation,
                "references": references.to_dict(),
            }

        install_root = _runtime_install_root_for_installation(installation)
        version_root = install_root.parent
        binding_statement = select(AgentExtensionBinding).where(
            AgentExtensionBinding.extension_installation_id == installation_id
        )
        for binding in self.db.exec(binding_statement).all():
            self.db.delete(binding)

        self.db.delete(installation)
        self.db.commit()
        if version_root.exists():
            shutil.rmtree(version_root, ignore_errors=True)
        self.artifact_storage.delete_artifact(artifact_key=installation.artifact_key)

        return {
            "mode": "physical",
            "installation": None,
            "references": references.to_dict(),
        }

    def validate_agent_bindings(self, *, agent_id: int) -> None:
        """Validate conflicts among the currently enabled bindings of one agent."""
        bundle = self.build_agent_extension_snapshot(agent_id)
        seen_tool_names: set[str] = {
            tool.name for tool in get_tool_manager().list_tools()
        }
        seen_skill_names: set[str] = set()
        for row in self.db.exec(select(Skill.name)).all():
            skill_name = row[0] if isinstance(row, tuple) else row
            if isinstance(skill_name, str) and skill_name:
                seen_skill_names.add(skill_name)

        for extension in bundle:
            for tool in extension.get("tools", []):
                tool_name = tool.get("name")
                if not isinstance(tool_name, str) or not tool_name:
                    continue
                if tool_name in seen_tool_names:
                    raise ValueError(
                        f"Extension tool name conflict detected: '{tool_name}'."
                    )
                seen_tool_names.add(tool_name)

            for skill in extension.get("skills", []):
                skill_name = skill.get("name")
                if not isinstance(skill_name, str) or not skill_name:
                    continue
                if skill_name in seen_skill_names:
                    raise ValueError(
                        f"Extension skill name conflict detected: '{skill_name}'."
                    )
                seen_skill_names.add(skill_name)

    def get_reference_summary(
        self, *, installation_id: int
    ) -> ExtensionReferenceSummary:
        """Return persisted references that still rely on one extension version."""
        installation = self.db.get(ExtensionInstallation, installation_id)
        if installation is None:
            raise ValueError("Installed extension version not found.")

        extension_binding_count = len(
            self.db.exec(
                select(AgentExtensionBinding).where(
                    AgentExtensionBinding.extension_installation_id == installation_id
                )
            ).all()
        )
        provider_binding_summary = ProviderRegistryService(
            self.db
        ).get_installation_provider_binding_summary(installation)

        release_count = sum(
            1
            for release in self.db.exec(select(AgentRelease)).all()
            if self._snapshot_references_installation(
                snapshot_json=release.snapshot_json,
                installation=installation,
            )
        )
        test_snapshot_count = sum(
            1
            for snapshot in self.db.exec(select(AgentTestSnapshot)).all()
            if self._snapshot_references_installation(
                snapshot_json=snapshot.snapshot_json,
                installation=installation,
            )
        )
        saved_draft_count = sum(
            1
            for draft in self.db.exec(select(AgentSavedDraft)).all()
            if self._snapshot_references_installation(
                snapshot_json=draft.snapshot_json,
                installation=installation,
            )
        )

        return ExtensionReferenceSummary(
            extension_binding_count=extension_binding_count,
            channel_binding_count=provider_binding_summary.channel_binding_count,
            media_provider_binding_count=(
                provider_binding_summary.media_provider_binding_count
            ),
            web_search_binding_count=provider_binding_summary.web_search_binding_count,
            release_count=release_count,
            test_snapshot_count=test_snapshot_count,
            saved_draft_count=saved_draft_count,
        )

    def build_agent_extension_snapshot(self, agent_id: int) -> list[dict[str, Any]]:
        """Return the normalized enabled extension bundle for one agent."""
        statement = (
            select(AgentExtensionBinding, ExtensionInstallation)
            .join(
                ExtensionInstallation,
                col(AgentExtensionBinding.extension_installation_id)
                == col(ExtensionInstallation.id),
            )
            .where(AgentExtensionBinding.agent_id == agent_id)
            .where(col(AgentExtensionBinding.enabled) == True)  # noqa: E712
            .where(col(ExtensionInstallation.status) == "active")
            .order_by(
                col(AgentExtensionBinding.priority).asc(),
                col(ExtensionInstallation.name).asc(),
            )
        )

        bundle: list[dict[str, Any]] = []
        for binding, installation in self.db.exec(statement).all():
            bundle.append(
                self.build_installation_runtime_entry(
                    installation=installation,
                    priority=binding.priority,
                    config=self._parse_config(binding.config_json),
                )
            )
        return bundle

    def list_agent_bound_extension_package_ids(
        self,
        *,
        agent_id: int,
        enabled_only: bool = False,
    ) -> set[str]:
        """Return package ids bound to one agent, optionally only enabled ones."""
        statement = (
            select(AgentExtensionBinding, ExtensionInstallation)
            .join(
                ExtensionInstallation,
                col(AgentExtensionBinding.extension_installation_id)
                == col(ExtensionInstallation.id),
            )
            .where(AgentExtensionBinding.agent_id == agent_id)
        )
        if enabled_only:
            statement = statement.where(col(AgentExtensionBinding.enabled) == True)  # noqa: E712
            statement = statement.where(col(ExtensionInstallation.status) == "active")

        package_ids: set[str] = set()
        for binding, installation in self.db.exec(statement).all():
            del binding
            package_ids.add(installation.package_id)
        return package_ids

    def is_agent_extension_package_bound(
        self,
        *,
        agent_id: int,
        package_id: str,
        enabled_only: bool = False,
    ) -> bool:
        """Return whether one extension package is currently bound to an agent."""
        return package_id in self.list_agent_bound_extension_package_ids(
            agent_id=agent_id,
            enabled_only=enabled_only,
        )

    def get_agent_child_availability(
        self,
        *,
        agent_id: int,
        package_id: str | None,
    ) -> tuple[bool, str | None]:
        """Resolve whether one extension child contribution is effectively usable."""
        if not package_id:
            return True, None
        if self.is_agent_extension_package_bound(
            agent_id=agent_id,
            package_id=package_id,
            enabled_only=True,
        ):
            return True, None
        if self.is_agent_extension_package_bound(
            agent_id=agent_id,
            package_id=package_id,
            enabled_only=False,
        ):
            return False, "Disabled because its extension is off."
        return (
            False,
            "Unavailable because its extension is not installed on this agent.",
        )

    def build_installation_runtime_entry(
        self,
        *,
        installation: ExtensionInstallation,
        priority: int = 100,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build one runtime bundle entry from an installed extension version."""
        manifest = self._load_manifest_from_installation(installation)
        contributions = manifest.get("contributions", {})
        install_root = self._ensure_materialized_installation_root(installation)
        return {
            "scope": installation.scope,
            "name": installation.name,
            "package_id": installation.package_id,
            "version": installation.version,
            "display_name": installation.display_name,
            "description": installation.description,
            "manifest_hash": installation.manifest_hash,
            "artifact_storage_backend": installation.artifact_storage_backend,
            "artifact_key": installation.artifact_key,
            "artifact_digest": installation.artifact_digest,
            "artifact_size_bytes": installation.artifact_size_bytes,
            "source": installation.source,
            "trust_status": installation.trust_status,
            "trust_source": installation.trust_source,
            "hub_scope": installation.hub_scope,
            "hub_package_id": installation.hub_package_id,
            "hub_package_version_id": installation.hub_package_version_id,
            "hub_artifact_digest": installation.hub_artifact_digest,
            "install_root": str(install_root),
            "priority": priority,
            "configuration": manifest.get("configuration", {}),
            "installation_config": self._parse_config(installation.config_json),
            "binding_config": config or {},
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "tool_type": tool.get("tool_type", "normal"),
                    "entrypoint": tool["entrypoint"],
                    "source_path": str(
                        install_root.joinpath(
                            *PurePosixPath(tool["entrypoint"]).parts
                        ).resolve()
                    ),
                }
                for tool in contributions.get("tools", [])
                if isinstance(tool, dict)
            ],
            "skills": [
                {
                    "name": skill["name"],
                    "description": skill.get("description", ""),
                    "path": skill["path"],
                    "location": str(
                        install_root.joinpath(
                            *PurePosixPath(skill["path"]).parts
                        ).resolve()
                    ),
                    "entry_file": _SKILL_MARKDOWN_FILENAME,
                }
                for skill in contributions.get("skills", [])
                if isinstance(skill, dict)
            ],
            "hooks": [
                {
                    "name": hook["name"],
                    "description": hook.get("description", ""),
                    "event": hook["event"],
                    "callable": hook["callable"],
                    "mode": hook.get("mode", "sync"),
                    "entrypoint": hook["entrypoint"],
                    "source_path": str(
                        install_root.joinpath(
                            *PurePosixPath(hook["entrypoint"]).parts
                        ).resolve()
                    ),
                }
                for hook in contributions.get("hooks", [])
                if isinstance(hook, dict)
                and isinstance(hook.get("event"), str)
                and isinstance(hook.get("callable"), str)
                and isinstance(hook.get("entrypoint"), str)
            ],
            "media_providers": [
                {
                    "key": provider["key"],
                    "name": provider.get("name", provider["key"]),
                    "description": provider.get("description", ""),
                    "supported_operations": provider.get("supported_operations", []),
                    "entrypoint": provider["entrypoint"],
                    "source_path": str(
                        install_root.joinpath(
                            *PurePosixPath(provider["entrypoint"]).parts
                        ).resolve()
                    ),
                }
                for provider in contributions.get("media_providers", [])
                if isinstance(provider, dict)
                and isinstance(provider.get("entrypoint"), str)
            ],
            "chat_surfaces": [
                {
                    "key": surface["key"],
                    "display_name": surface.get("display_name", surface["key"]),
                    "description": surface.get("description", ""),
                    "placement": surface.get("placement", "right_dock"),
                    "min_width": surface.get("min_width"),
                    "entrypoint": surface["entrypoint"],
                    "source_path": str(
                        install_root.joinpath(
                            *PurePosixPath(surface["entrypoint"]).parts
                        ).resolve()
                    ),
                }
                for surface in contributions.get("chat_surfaces", [])
                if isinstance(surface, dict)
                and isinstance(surface.get("entrypoint"), str)
                and isinstance(surface.get("key"), str)
            ],
        }

    def build_request_tool_manager(
        self,
        *,
        username: str,
        agent_id: int,
        raw_tool_ids: str | None,
        extension_bundle: list[dict[str, Any]],
    ) -> ToolManager:
        """Build the runtime tool catalog for one request-scoped execution.

        Why: extension bindings are the agent-scoped opt-in for packaged
        capabilities. Once an extension is enabled for an agent, its declared
        tools remain available without also being stored in the agent's manual
        tool selection list.
        """
        ensure_agent_workspace(username, agent_id)
        shared_manager = get_tool_manager()
        request_tool_manager = ToolManager()
        for metadata in shared_manager.list_tools():
            request_tool_manager.add_entry(metadata)

        allowed_tools = _parse_name_allowlist(raw_tool_ids)
        manual_metas = load_runtime_manual_tool_metadata(
            self.db,
            tool_names=allowed_tools,
        )
        for metadata in manual_metas:
            if request_tool_manager.get_tool(metadata.name) is None:
                request_tool_manager.add_entry(metadata)

        bundle_tool_metadata = self.load_bundle_tool_metadata(extension_bundle)
        bundle_tool_names = {metadata.name for metadata in bundle_tool_metadata}
        for metadata in bundle_tool_metadata:
            if request_tool_manager.get_tool(metadata.name) is None:
                request_tool_manager.add_entry(metadata)

        ptc_meta = request_tool_manager.get_tool("programmatic_tool_call")
        if ptc_meta is not None:
            full_callables = {m.name: m.func for m in request_tool_manager.list_tools()}
            ptc_meta.func = make_programmatic_tool_call(full_callables)

        filtered_manager = ToolManager()
        for metadata in request_tool_manager.list_tools():
            if metadata.name in allowed_tools or metadata.name in bundle_tool_names:
                filtered_manager.add_entry(metadata)
        return filtered_manager

    def load_bundle_tool_metadata(
        self,
        extension_bundle: list[dict[str, Any]],
    ) -> list[ToolMetadata]:
        """Load runtime tool metadata for every tool contribution in a bundle."""
        results: list[ToolMetadata] = []
        seen_tool_names: set[str] = set()
        for extension in extension_bundle:
            extension_name = extension.get("name")
            extension_version = extension.get("version")
            tools = extension.get("tools", [])
            if not isinstance(extension_name, str) or not isinstance(
                extension_version, str
            ):
                continue
            if not isinstance(tools, list):
                continue

            for tool in tools:
                if not isinstance(tool, dict):
                    continue
                tool_name = tool.get("name")
                source_path = tool.get("source_path")
                if (
                    not isinstance(tool_name, str)
                    or not tool_name
                    or not isinstance(source_path, str)
                ):
                    continue
                if tool_name in seen_tool_names:
                    raise ValueError(f"Duplicate extension tool '{tool_name}'.")
                metadata = _load_tool_metadata_from_file(
                    tool_name=tool_name,
                    source_path=Path(source_path),
                    module_key=(
                        "_pivot_extension_runtime_"
                        f"{extension_name}_{extension_version}_{tool_name}"
                    ),
                )
                results.append(metadata)
                seen_tool_names.add(tool_name)
        return results

    def build_bundle_skill_payloads(
        self,
        extension_bundle: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        """Return normalized skill payloads exposed by a resolved bundle."""
        payloads: list[dict[str, str]] = []
        seen_skill_names: set[str] = set()
        for extension in extension_bundle:
            skills = extension.get("skills", [])
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if not isinstance(skill, dict):
                    continue
                skill_name = skill.get("name")
                skill_location = skill.get("location")
                if (
                    not isinstance(skill_name, str)
                    or not skill_name
                    or not isinstance(skill_location, str)
                ):
                    continue
                normalized_skill_name = str(skill_name)
                normalized_location = str(skill_location)
                if normalized_skill_name in seen_skill_names:
                    raise ValueError(
                        f"Duplicate extension skill '{normalized_skill_name}'."
                    )
                normalized_description = (
                    str(skill.get("description"))
                    if isinstance(skill.get("description"), str)
                    else ""
                )
                payload: dict[str, str] = {
                    "name": normalized_skill_name,
                    "description": normalized_description,
                    "location": normalized_location,
                    "entry_file": _SKILL_MARKDOWN_FILENAME,
                }
                payloads.append(payload)
                seen_skill_names.add(normalized_skill_name)
        return payloads

    @staticmethod
    def _format_provider_conflict_message(
        *,
        action: str,
        conflicts: list[Any],
    ) -> str:
        """Render a concise validation error for provider-key collisions."""
        if not conflicts:
            return f"Cannot {action} extension because provider keys conflict."

        details: list[str] = []
        for conflict in conflicts:
            provider_type = getattr(conflict, "provider_type", "provider")
            provider_key = getattr(conflict, "provider_key", "unknown")
            source = getattr(conflict, "source", "extension")
            if source == "builtin":
                details.append(
                    f"{provider_type} provider '{provider_key}' conflicts with a "
                    "built-in provider"
                )
                continue

            installation_name = getattr(conflict, "installation_name", None)
            installation_version = getattr(conflict, "installation_version", None)
            if installation_name and installation_version:
                details.append(
                    f"{provider_type} provider '{provider_key}' conflicts with "
                    f"{installation_name}@{installation_version}"
                )
            else:
                details.append(
                    f"{provider_type} provider '{provider_key}' conflicts with "
                    "another active extension"
                )

        joined_details = "; ".join(details)
        return f"Cannot {action} extension because {joined_details}."

    def _load_manifest_from_installation(
        self,
        installation: ExtensionInstallation,
    ) -> dict[str, Any]:
        """Parse and return the normalized manifest stored on one installation."""
        try:
            parsed = json.loads(installation.manifest_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Stored manifest for {installation.package_id}@{installation.version} is invalid."
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Stored manifest for {installation.package_id}@{installation.version} is invalid."
            )
        return parsed

    @staticmethod
    def _get_configuration_schema_section(
        *,
        manifest: dict[str, Any],
        section_name: str,
    ) -> dict[str, Any]:
        """Return one normalized configuration schema section from a manifest."""
        raw_configuration = manifest.get("configuration", {})
        if not isinstance(raw_configuration, dict):
            return {"fields": []}
        raw_section = raw_configuration.get(section_name, {})
        if not isinstance(raw_section, dict):
            return {"fields": []}
        raw_fields = raw_section.get("fields", [])
        if not isinstance(raw_fields, list):
            return {"fields": []}
        return {"fields": raw_fields}

    @staticmethod
    def _parse_package_id(package_id: str) -> tuple[str, str]:
        """Split one canonical package id into scope and package name."""
        normalized = package_id.strip()
        if not normalized.startswith("@") or "/" not in normalized:
            raise ValueError("package_id must follow '@scope/name'.")
        scope, name = normalized[1:].split("/", 1)
        if scope == "" or name == "":
            raise ValueError("package_id must follow '@scope/name'.")
        return scope, name

    @staticmethod
    def _parse_config(raw_value: str | None) -> dict[str, Any]:
        """Parse one binding config payload into a dictionary."""
        if not raw_value:
            return {}
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _version_sort_key(version: str) -> tuple[tuple[int, int | str], ...]:
        """Build a deterministic version sort key for display ordering."""
        normalized = version.strip()
        if not normalized:
            return ((2, ""),)

        parts: list[tuple[int, int | str]] = []
        for token in _VERSION_TOKEN_PATTERN.findall(normalized):
            if token.isdigit():
                parts.append((3, int(token)))
            elif token.isalpha():
                parts.append((1, token.lower()))
            else:
                parts.append((0, token))
        return tuple(parts)

    def _get_installation_or_raise(
        self,
        installation_id: int,
    ) -> ExtensionInstallation:
        """Load one installation row or raise a descriptive error."""
        installation = self.db.get(ExtensionInstallation, installation_id)
        if installation is None:
            raise ValueError("Installed extension version not found.")
        return installation

    @staticmethod
    def _validate_installation_binding_state(
        *,
        installation: ExtensionInstallation,
        enabled: bool,
    ) -> None:
        """Validate whether one installation may be enabled in a binding."""
        if enabled and installation.status != "active":
            raise ValueError(
                "Disabled extension versions cannot be enabled in agent bindings."
            )

    def _validate_single_package_binding(
        self,
        *,
        agent_id: int,
        installation: ExtensionInstallation,
        current_extension_installation_id: int,
    ) -> None:
        """Ensure one agent does not bind multiple versions of the same package."""
        statement = (
            select(AgentExtensionBinding, ExtensionInstallation)
            .join(
                ExtensionInstallation,
                col(AgentExtensionBinding.extension_installation_id)
                == col(ExtensionInstallation.id),
            )
            .where(AgentExtensionBinding.agent_id == agent_id)
            .where(ExtensionInstallation.scope == installation.scope)
            .where(ExtensionInstallation.name == installation.name)
        )
        for binding, existing_installation in self.db.exec(statement).all():
            del existing_installation
            if binding.extension_installation_id != current_extension_installation_id:
                raise ValueError(
                    "Agent bindings may include only one version per extension package."
                )

    def _seed_agent_provider_bindings(
        self,
        *,
        agent_id: int,
        installation: ExtensionInstallation,
        now: datetime,
    ) -> None:
        """Create default disabled provider bindings for one bound extension."""
        manifest = self._load_manifest_from_installation(installation)
        contributions = manifest.get("contributions", {})
        if not isinstance(contributions, dict):
            return

        for item in contributions.get("media_providers", []):
            if not isinstance(item, dict):
                continue
            provider_key = item.get("key")
            if not isinstance(provider_key, str) or not provider_key.strip():
                continue
            normalized_key = provider_key.strip()
            existing_media_binding = self.db.exec(
                select(AgentMediaProviderBinding).where(
                    AgentMediaProviderBinding.agent_id == agent_id,
                    AgentMediaProviderBinding.provider_key == normalized_key,
                )
            ).first()
            if existing_media_binding is not None:
                continue
            self.db.add(
                AgentMediaProviderBinding(
                    agent_id=agent_id,
                    provider_key=normalized_key,
                    enabled=False,
                    auth_config="{}",
                    runtime_config="{}",
                    created_at=now,
                    updated_at=now,
                )
            )

        for item in contributions.get("web_search_providers", []):
            if not isinstance(item, dict):
                continue
            provider_key = item.get("key")
            if not isinstance(provider_key, str) or not provider_key.strip():
                continue
            normalized_key = provider_key.strip()
            existing_web_search_binding = self.db.exec(
                select(AgentWebSearchBinding).where(
                    AgentWebSearchBinding.agent_id == agent_id,
                    AgentWebSearchBinding.provider_key == normalized_key,
                )
            ).first()
            if existing_web_search_binding is not None:
                continue
            self.db.add(
                AgentWebSearchBinding(
                    agent_id=agent_id,
                    provider_key=normalized_key,
                    enabled=False,
                    auth_config="{}",
                    runtime_config="{}",
                    created_at=now,
                    updated_at=now,
                )
            )

    @staticmethod
    def _build_provider_key_sets(
        installations: list[ExtensionInstallation] | Any,
    ) -> dict[str, set[str]]:
        """Collect provider keys contributed by a set of installations."""
        keys = {
            "channel": set(),
            "media": set(),
            "web_search": set(),
        }
        for installation in installations:
            if not isinstance(installation, ExtensionInstallation):
                continue
            provider_keys = extract_provider_keys_from_manifest(
                json.loads(installation.manifest_json)
            )
            keys["channel"].update(provider_keys["channel"])
            keys["media"].update(provider_keys["media"])
            keys["web_search"].update(provider_keys["web_search"])
        return keys

    def _delete_agent_contributions_for_installation(
        self,
        *,
        agent_id: int,
        installation: ExtensionInstallation,
        preserve_provider_keys: dict[str, set[str]] | None = None,
    ) -> None:
        """Delete agent-scoped child contributions tied to one extension."""
        preserve_provider_keys = preserve_provider_keys or {
            "channel": set(),
            "media": set(),
            "web_search": set(),
        }
        provider_keys = extract_provider_keys_from_manifest(
            self._load_manifest_from_installation(installation)
        )

        removable_channel_keys = (
            provider_keys["channel"] - preserve_provider_keys["channel"]
        )
        if removable_channel_keys:
            channel_binding_rows = self.db.exec(
                select(AgentChannelBinding).where(
                    AgentChannelBinding.agent_id == agent_id,
                    col(AgentChannelBinding.channel_key).in_(removable_channel_keys),
                )
            ).all()
            channel_binding_ids = [
                binding.id for binding in channel_binding_rows if binding.id is not None
            ]
            if channel_binding_ids:
                for token_row in self.db.exec(
                    select(ChannelLinkToken).where(
                        col(ChannelLinkToken.channel_binding_id).in_(
                            channel_binding_ids
                        )
                    )
                ).all():
                    self.db.delete(token_row)
                for identity_row in self.db.exec(
                    select(ExternalIdentityBinding).where(
                        col(ExternalIdentityBinding.channel_binding_id).in_(
                            channel_binding_ids
                        )
                    )
                ).all():
                    self.db.delete(identity_row)
                for session_row in self.db.exec(
                    select(ChannelSession).where(
                        col(ChannelSession.channel_binding_id).in_(channel_binding_ids)
                    )
                ).all():
                    self.db.delete(session_row)
                for event_row in self.db.exec(
                    select(ChannelEventLog).where(
                        col(ChannelEventLog.channel_binding_id).in_(channel_binding_ids)
                    )
                ).all():
                    self.db.delete(event_row)
            for binding in channel_binding_rows:
                self.db.delete(binding)

        removable_media_keys = provider_keys["media"] - preserve_provider_keys["media"]
        if removable_media_keys:
            for binding in self.db.exec(
                select(AgentMediaProviderBinding).where(
                    AgentMediaProviderBinding.agent_id == agent_id,
                    col(AgentMediaProviderBinding.provider_key).in_(
                        removable_media_keys
                    ),
                )
            ).all():
                self.db.delete(binding)

        removable_web_search_keys = (
            provider_keys["web_search"] - preserve_provider_keys["web_search"]
        )
        if removable_web_search_keys:
            for binding in self.db.exec(
                select(AgentWebSearchBinding).where(
                    AgentWebSearchBinding.agent_id == agent_id,
                    col(AgentWebSearchBinding.provider_key).in_(
                        removable_web_search_keys
                    ),
                )
            ).all():
                self.db.delete(binding)

    @staticmethod
    def _snapshot_references_installation(
        *,
        snapshot_json: str,
        installation: ExtensionInstallation,
    ) -> bool:
        """Return whether one persisted snapshot references an extension version."""
        try:
            parsed = json.loads(snapshot_json)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed, dict):
            return False
        raw_extensions = parsed.get("extensions")
        if not isinstance(raw_extensions, list):
            return False

        for item in raw_extensions:
            if not isinstance(item, dict):
                continue
            if (
                item.get("scope") == installation.scope
                and item.get("name") == installation.name
                and item.get("version") == installation.version
                and item.get("manifest_hash") == installation.manifest_hash
            ):
                return True
        return False
