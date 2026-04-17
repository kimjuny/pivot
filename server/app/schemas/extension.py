"""Schemas for extension installation and agent binding APIs."""

from __future__ import annotations

from typing import Any

from app.schemas.base import AppBaseModel
from pydantic import Field


class ExtensionInstallRequest(AppBaseModel):
    """Request payload for installing one extension folder."""

    source_dir: str = Field(..., description="Local directory path of the extension.")
    trust_confirmed: bool = Field(
        default=False,
        description="Whether the operator explicitly trusted this local package.",
    )
    overwrite_confirmed: bool = Field(
        default=False,
        description=(
            "Whether the operator explicitly approved overwriting an already "
            "installed package with the same scope, name, and version."
        ),
    )


class ExtensionInstallationStatusRequest(AppBaseModel):
    """Request payload for changing one installation status."""

    status: str = Field(..., description="Desired status: active or disabled.")


class ExtensionContributionSummaryResponse(AppBaseModel):
    """Normalized contribution names exposed for one installed extension version."""

    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    hooks: list[str] = Field(default_factory=list)
    chat_surfaces: list[str] = Field(default_factory=list)
    channel_providers: list[str] = Field(default_factory=list)
    image_providers: list[str] = Field(default_factory=list)
    web_search_providers: list[str] = Field(default_factory=list)


class ExtensionContributionItemResponse(AppBaseModel):
    """One operator-facing contribution declared by an extension version."""

    type: str
    name: str
    description: str = ""
    key: str | None = None
    min_width: int | None = None


class ExtensionConfigurationFieldResponse(AppBaseModel):
    """One manifest-declared extension configuration field."""

    key: str
    label: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    placeholder: str = ""


class ExtensionConfigurationSectionResponse(AppBaseModel):
    """Configuration schema section for installation or binding scope."""

    fields: list[ExtensionConfigurationFieldResponse] = Field(default_factory=list)


class ExtensionConfigurationSchemaResponse(AppBaseModel):
    """Normalized configuration schema declared by one extension package."""

    installation: ExtensionConfigurationSectionResponse = Field(
        default_factory=ExtensionConfigurationSectionResponse
    )
    binding: ExtensionConfigurationSectionResponse = Field(
        default_factory=ExtensionConfigurationSectionResponse
    )


class ExtensionHookExecutionResponse(AppBaseModel):
    """Serialized append-only lifecycle hook execution record."""

    id: int
    session_id: str | None = None
    task_id: str
    trace_id: str | None = None
    iteration: int
    agent_id: int
    release_id: int | None = None
    extension_package_id: str
    extension_version: str
    hook_event: str
    hook_callable: str
    status: str
    hook_context: dict[str, Any] | None = None
    effects: list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None
    started_at: str
    finished_at: str
    duration_ms: int


class ExtensionHookReplayResponse(AppBaseModel):
    """Serialized safe replay result for one historical hook execution."""

    execution_id: int
    extension_package_id: str
    extension_version: str
    hook_event: str
    hook_callable: str
    status: str
    effects: list[dict[str, Any]] | None = None
    error: dict[str, Any] | None = None
    replayed_at: str


class ExtensionInstallationResponse(AppBaseModel):
    """Serialized installed extension version."""

    id: int
    scope: str
    name: str
    package_id: str
    version: str
    display_name: str
    description: str
    logo_url: str | None = None
    manifest_hash: str
    artifact_storage_backend: str
    artifact_key: str
    artifact_digest: str
    artifact_size_bytes: int
    install_root: str
    source: str
    trust_status: str
    trust_source: str
    hub_scope: str | None = None
    hub_package_id: str | None = None
    hub_package_version_id: str | None = None
    hub_artifact_digest: str | None = None
    installed_by: str | None = None
    status: str
    created_at: str
    updated_at: str
    contribution_summary: ExtensionContributionSummaryResponse = Field(
        default_factory=ExtensionContributionSummaryResponse
    )
    contribution_items: list[ExtensionContributionItemResponse] = Field(
        default_factory=list
    )
    reference_summary: ExtensionReferenceSummaryResponse | None = None


class ExtensionInstallationConfigRequest(AppBaseModel):
    """Request payload for saving installation-scoped extension configuration."""

    config: dict[str, Any] = Field(default_factory=dict)


class ExtensionInstallationConfigResponse(AppBaseModel):
    """Configuration schema and current values for one installed extension version."""

    installation_id: int
    package_id: str
    version: str
    configuration_schema: ExtensionConfigurationSchemaResponse = Field(
        default_factory=ExtensionConfigurationSchemaResponse
    )
    config: dict[str, Any] = Field(default_factory=dict)


class ExtensionPackageResponse(AppBaseModel):
    """Installed package-level view grouped by extension name."""

    scope: str
    name: str
    package_id: str
    display_name: str
    description: str
    logo_url: str | None = None
    readme_markdown: str = ""
    latest_version: str
    active_version_count: int
    disabled_version_count: int
    versions: list[ExtensionInstallationResponse] = Field(default_factory=list)


class ExtensionImportPreviewResponse(AppBaseModel):
    """Preview shown before trusting and installing one local extension."""

    scope: str
    name: str
    package_id: str
    version: str
    display_name: str
    description: str
    source: str
    trust_status: str
    trust_source: str
    manifest_hash: str
    contribution_summary: ExtensionContributionSummaryResponse = Field(
        default_factory=ExtensionContributionSummaryResponse
    )
    contribution_items: list[ExtensionContributionItemResponse] = Field(
        default_factory=list
    )
    permissions: dict[str, Any] = Field(default_factory=dict)
    existing_installation_id: int | None = None
    existing_installation_status: str | None = None
    identical_to_installed: bool = False
    requires_overwrite_confirmation: bool = False
    overwrite_blocked_reason: str = ""
    existing_reference_summary: ExtensionReferenceSummaryResponse | None = None


class ExtensionReferenceSummaryResponse(AppBaseModel):
    """Counts of persisted references that still rely on an extension version."""

    extension_binding_count: int
    channel_binding_count: int
    image_provider_binding_count: int
    web_search_binding_count: int
    binding_count: int
    release_count: int
    test_snapshot_count: int
    saved_draft_count: int


class ExtensionUninstallResponse(AppBaseModel):
    """Result returned after uninstalling one extension version."""

    mode: str
    references: ExtensionReferenceSummaryResponse
    installation: ExtensionInstallationResponse | None = None


class AgentExtensionBindingRequest(AppBaseModel):
    """Request payload for creating or updating one agent binding."""

    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentExtensionBindingUpsertRequest(AppBaseModel):
    """One binding entry inside a batch replace request."""

    extension_installation_id: int
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentExtensionBindingBatchRequest(AppBaseModel):
    """Request payload for replacing one agent's full binding set."""

    bindings: list[AgentExtensionBindingUpsertRequest] = Field(default_factory=list)


class AgentExtensionBindingResponse(AppBaseModel):
    """Serialized agent-extension binding with installation metadata."""

    id: int
    agent_id: int
    extension_installation_id: int
    enabled: bool
    priority: int
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    installation: ExtensionInstallationResponse


class AgentExtensionPackageResponse(AppBaseModel):
    """Package-level extension view tailored for one agent draft."""

    scope: str
    name: str
    package_id: str
    display_name: str
    description: str
    logo_url: str | None = None
    latest_version: str
    active_version_count: int
    disabled_version_count: int
    has_update_available: bool
    selected_binding: AgentExtensionBindingResponse | None = None
    versions: list[ExtensionInstallationResponse] = Field(default_factory=list)
