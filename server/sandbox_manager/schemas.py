"""Shared schema and type definitions for sandbox-manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class RuntimeBind:
    """One prepared helper-side bind mount description for a sandbox."""

    source: str
    destination: str
    mode: str = "rw"


class WorkspaceRuntimeDriver(Protocol):
    """Prepare workspace runtime paths for one storage backend."""

    def ensure_runtime_ready(self) -> None:
        """Ensure helper-side runtime prerequisites are satisfied."""
        ...

    def ensure_workspace_ready(self, logical_path: str, mount_mode: str) -> None:
        """Ensure one logical workspace is materialized and ready to bind."""
        ...

    def build_workspace_bind(self, logical_path: str, mount_mode: str) -> RuntimeBind:
        """Return the helper-side bind mount used by sandbox containers."""
        ...

    def delete_workspace(self, logical_path: str) -> None:
        """Delete one logical workspace when the runtime owns lifecycle cleanup."""
        ...

    def sync_workspace(self, logical_path: str, mount_mode: str) -> None:
        """Flush one logical workspace cache back into canonical storage."""
        ...


class SandboxSkillMount(BaseModel):
    """One canonical skill materialization entry sent by backend."""

    name: str = Field(min_length=1)
    canonical_location: str = Field(min_length=1)


class SandboxRequest(BaseModel):
    """Request payload for create/destroy operations."""

    username: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    storage_backend: str = Field(min_length=1)
    logical_path: str = Field(min_length=1)
    mount_mode: str = Field(min_length=1)
    source_workspace_id: str | None = None
    skills: list[SandboxSkillMount] = Field(default_factory=list)


class SandboxExecRequest(SandboxRequest):
    """Request payload for command execution."""

    cmd: list[str] = Field(min_length=1)


class SandboxExecResponse(BaseModel):
    """Response payload for command execution."""

    exit_code: int
    stdout: str
    stderr: str
    container_name: str


class SeaweedfsRuntimeStatusResponse(BaseModel):
    """Describe current shared-mount-root runtime status for diagnostics."""

    storage_backend: str = "seaweedfs"
    attach_strategy: str
    native_mount_required: bool
    filer_url: str
    filer_reachable: bool
    mount_root: str
    mount_root_host_path: str | None = None
    native_mount_active: bool
    fallback_bridge_active: bool
