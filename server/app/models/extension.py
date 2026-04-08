"""Database models for installed extension packages and agent bindings."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class ExtensionInstallation(SQLModel, table=True):
    """One installed extension package version available to Pivot.

    Attributes:
        id: Primary key of the installed extension version.
        scope: Stable namespace such as ``acme``.
        name: Stable package name within the scope, such as ``providers``.
        version: Immutable package version string.
        display_name: Human-readable package title shown in Studio.
        description: Short package summary from ``manifest.json``.
        manifest_json: Canonical normalized manifest payload.
        manifest_hash: Stable hash of the canonical manifest payload.
        artifact_storage_backend: Stable storage backend identifier such as
            ``seaweedfs`` or a future fallback backend.
        artifact_key: Canonical object-storage style key for the persisted
            extension artifact.
        artifact_digest: Stable digest of the persisted extension artifact.
        artifact_size_bytes: Size of the persisted extension artifact in bytes.
        install_root: Absolute directory path containing the materialized runtime
            package used for local imports and Python module loading.
        config_json: Persisted installation-scoped configuration values derived
            from the package's declared configuration schema.
        source: Installation source such as ``manual``.
        trust_status: Trust state such as ``trusted_local`` or ``verified``.
        trust_source: Trust provenance such as ``local_import`` or
            ``official_hub``.
        hub_scope: Verified Hub scope when installed from the official Hub.
        hub_package_id: Canonical Hub package id such as ``@acme/providers``.
        hub_package_version_id: Stable Hub-side package version identifier.
        hub_artifact_digest: Verified artifact digest reported by the Hub.
        installed_by: Username that installed the package, if known.
        status: Lifecycle state such as ``active`` or ``disabled``.
        created_at: UTC timestamp when the package version was installed.
        updated_at: UTC timestamp when the row last changed.
    """

    __table_args__ = (UniqueConstraint("scope", "name", "version"),)

    id: int | None = Field(default=None, primary_key=True)
    scope: str = Field(index=True, max_length=120)
    name: str = Field(index=True, max_length=255)
    version: str = Field(index=True, max_length=64)
    display_name: str = Field(max_length=255)
    description: str = Field(default="")
    manifest_json: str = Field()
    manifest_hash: str = Field(index=True, max_length=64)
    artifact_storage_backend: str = Field(default="seaweedfs", max_length=64)
    artifact_key: str = Field(unique=True, max_length=2048)
    artifact_digest: str = Field(index=True, max_length=64)
    artifact_size_bytes: int = Field(default=0)
    install_root: str = Field(unique=True, max_length=2048)
    config_json: str | None = Field(default=None)
    source: str = Field(default="manual", max_length=32)
    trust_status: str = Field(default="trusted_local", index=True, max_length=32)
    trust_source: str = Field(default="local_import", max_length=32)
    hub_scope: str | None = Field(default=None, max_length=120)
    hub_package_id: str | None = Field(default=None, max_length=255)
    hub_package_version_id: str | None = Field(default=None, max_length=255)
    hub_artifact_digest: str | None = Field(default=None, max_length=255)
    installed_by: str | None = Field(default=None, max_length=120)
    status: str = Field(default="active", index=True, max_length=32)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def package_id(self) -> str:
        """Return the canonical npm-style package identifier."""
        return f"@{self.scope}/{self.name}"


class AgentExtensionBinding(SQLModel, table=True):
    """Agent-scoped toggle and config for one installed extension version.

    Attributes:
        id: Primary key of the binding row.
        agent_id: Agent that may use the installed extension version.
        extension_installation_id: Installed extension version referenced by the
            binding.
        enabled: Whether the extension is active for the agent.
        priority: Lower numbers run earlier during deterministic resolution.
        config_json: Optional agent-local configuration payload.
        created_at: UTC timestamp when the binding was created.
        updated_at: UTC timestamp when the binding last changed.
    """

    __table_args__ = (UniqueConstraint("agent_id", "extension_installation_id"),)

    id: int | None = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    extension_installation_id: int = Field(
        foreign_key="extensioninstallation.id",
        index=True,
    )
    enabled: bool = Field(default=True, index=True)
    priority: int = Field(default=100)
    config_json: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtensionHookExecution(SQLModel, table=True):
    """Append-only execution log for one packaged lifecycle hook invocation.

    Attributes:
        id: Primary key of the execution log row.
        session_id: Owning session UUID when the task is session-backed.
        task_id: Owning task UUID.
        trace_id: Current iteration trace identifier, if available.
        iteration: Iteration index associated with the hook invocation.
        agent_id: Agent executing the extension bundle.
        release_id: Pinned release identifier when the runtime is release-backed.
        extension_package_id: Canonical package id such as ``@acme/providers``.
        extension_version: Installed package version that executed the hook.
        hook_event: Lifecycle event name such as ``task.before_start``.
        hook_callable: Exported callable name inside the hook module.
        status: Execution result such as ``succeeded`` or ``failed``.
        hook_context_json: Serialized historical hook input used for replay.
        effects_json: Serialized structured effects returned by the hook.
        error_json: Serialized error payload when execution fails.
        started_at: UTC timestamp when the hook execution started.
        finished_at: UTC timestamp when the hook execution finished.
        duration_ms: Total wall-clock execution time in milliseconds.
    """

    id: int | None = Field(default=None, primary_key=True)
    session_id: str | None = Field(default=None, index=True, max_length=255)
    task_id: str = Field(index=True, max_length=255)
    trace_id: str | None = Field(default=None, index=True, max_length=255)
    iteration: int = Field(default=0, index=True)
    agent_id: int = Field(index=True)
    release_id: int | None = Field(default=None, index=True)
    extension_package_id: str = Field(index=True, max_length=255)
    extension_version: str = Field(index=True, max_length=64)
    hook_event: str = Field(index=True, max_length=255)
    hook_callable: str = Field(max_length=255)
    status: str = Field(index=True, max_length=32)
    hook_context_json: str | None = Field(default=None)
    effects_json: str | None = Field(default=None)
    error_json: str | None = Field(default=None)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int = Field(default=0)
