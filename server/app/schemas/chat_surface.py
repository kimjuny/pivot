"""Schemas for chat surface development and workspace file APIs."""

from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel
from pydantic import Field


class CreateDevSurfaceSessionRequest(AppBaseModel):
    """Request payload for creating one development-mode chat surface session."""

    session_id: str = Field(..., description="Owning chat session identifier.")
    surface_key: str = Field(
        ...,
        description="Stable surface key used by the development runtime.",
    )
    dev_server_url: str = Field(
        ...,
        description=(
            "Local development runtime URL served by the surface author. "
            "May point at a server root or a concrete entry HTML page."
        ),
    )
    display_name: str | None = Field(
        default=None,
        description="Optional operator-facing label shown in the dock.",
    )


class CreateInstalledSurfaceSessionRequest(AppBaseModel):
    """Request payload for creating one installed chat surface session."""

    session_id: str = Field(..., description="Owning chat session identifier.")
    extension_installation_id: int = Field(
        ...,
        description="Installed extension version bound to the active agent.",
    )
    surface_key: str = Field(
        ...,
        description="Stable surface key declared by the installed extension.",
    )


class CreatePreviewEndpointRequest(AppBaseModel):
    """Request payload for creating one session-scoped web preview endpoint."""

    session_id: str = Field(..., description="Owning chat session identifier.")
    preview_name: str = Field(
        ...,
        description="Operator-facing preview label shown in the preview picker.",
    )
    start_server: str = Field(
        ...,
        description=(
            "Idempotent shell command that ensures the preview server is running."
        ),
    )
    port: int = Field(..., description="Sandbox-local HTTP port to expose.")
    path: str | None = Field(
        default="/",
        description="Optional initial HTTP path served from the preview port.",
    )
    cwd: str | None = Field(
        default=".",
        description="Workspace-relative or absolute /workspace directory for start_server.",
    )


class PreviewEndpointResponse(AppBaseModel):
    """Serialized session-scoped web preview endpoint."""

    preview_id: str
    session_id: str
    workspace_id: str
    workspace_logical_root: str
    title: str
    port: int
    path: str
    has_launch_recipe: bool
    proxy_url: str
    created_at: str


class ReconnectPreviewEndpointResponse(AppBaseModel):
    """Reconnect response returned to one surface runtime."""

    preview: PreviewEndpointResponse
    available_previews: list[PreviewEndpointResponse] = Field(default_factory=list)
    active_preview_id: str | None = None


class SurfaceFilesApiResponse(AppBaseModel):
    """Workspace file endpoints exposed to one surface runtime."""

    directory_url: str
    text_url: str
    blob_url: str
    tree_url: str
    content_url: str
    create_directory_url: str
    path_url: str


class SurfaceThemeResponse(AppBaseModel):
    """Resolved host theme state injected into one surface runtime."""

    preference: Literal["system", "dark", "light"]
    resolved: Literal["dark", "light"]


class DevSurfaceBootstrapResponse(AppBaseModel):
    """Minimum bootstrap payload required by one development surface runtime."""

    surface_session_id: str
    surface_token: str
    mode: Literal["dev"] = "dev"
    surface_key: str
    display_name: str
    agent_id: int
    session_id: str
    workspace_id: str
    workspace_logical_root: str
    dev_server_url: str
    capabilities: list[str] = Field(default_factory=list)
    files_api: SurfaceFilesApiResponse
    theme: SurfaceThemeResponse | None = None


class DevSurfaceSessionResponse(AppBaseModel):
    """Serialized development surface session returned to the chat host."""

    surface_session_id: str
    surface_token: str
    surface_key: str
    display_name: str
    agent_id: int
    session_id: str
    workspace_id: str
    workspace_logical_root: str
    dev_server_url: str
    created_at: str
    bootstrap: DevSurfaceBootstrapResponse


class InstalledSurfaceBootstrapResponse(AppBaseModel):
    """Minimum bootstrap payload required by one installed surface runtime."""

    surface_session_id: str
    surface_token: str
    mode: Literal["installed"] = "installed"
    surface_key: str
    display_name: str
    package_id: str
    extension_installation_id: int
    agent_id: int
    session_id: str
    workspace_id: str
    workspace_logical_root: str
    runtime_url: str
    capabilities: list[str] = Field(default_factory=list)
    files_api: SurfaceFilesApiResponse
    theme: SurfaceThemeResponse | None = None


class InstalledSurfaceSessionResponse(AppBaseModel):
    """Serialized installed surface session returned to the chat host."""

    surface_session_id: str
    surface_token: str
    surface_key: str
    display_name: str
    package_id: str
    extension_installation_id: int
    agent_id: int
    session_id: str
    workspace_id: str
    workspace_logical_root: str
    runtime_url: str
    created_at: str
    bootstrap: InstalledSurfaceBootstrapResponse


class WorkspaceFileTreeEntryResponse(AppBaseModel):
    """One file-system node inside a workspace tree listing."""

    path: str
    name: str
    kind: Literal["file", "directory"]
    parent_path: str | None = None
    size_bytes: int | None = None


class WorkspaceFileTreeResponse(AppBaseModel):
    """Recursive file listing rooted at one workspace-relative path."""

    root_path: str = "."
    entries: list[WorkspaceFileTreeEntryResponse] = Field(default_factory=list)


class WorkspaceDirectoryEntryResponse(AppBaseModel):
    """One direct child returned by a workspace directory listing."""

    path: str
    name: str
    kind: Literal["file", "directory"]
    parent_path: str | None = None
    size_bytes: int | None = None


class WorkspaceDirectoryResponse(AppBaseModel):
    """Direct file listing for one workspace-relative directory."""

    root_path: str = "."
    entries: list[WorkspaceDirectoryEntryResponse] = Field(default_factory=list)


class WorkspaceTextFileResponse(AppBaseModel):
    """UTF-8 text file payload returned to a surface runtime."""

    path: str
    content: str
    encoding: Literal["utf-8"] = "utf-8"


class WorkspaceBinaryFileResponse(AppBaseModel):
    """Binary file metadata returned after a workspace upload."""

    path: str
    mime_type: str
    size_bytes: int


class WorkspaceFileContentResponse(AppBaseModel):
    """Previewable workspace file payload returned to a surface runtime."""

    path: str
    kind: Literal["text", "image"]
    content: str | None = None
    encoding: Literal["utf-8"] | None = None
    mime_type: str | None = None
    data_base64: str | None = None


class WriteWorkspaceFileRequest(AppBaseModel):
    """Request payload for saving one UTF-8 text file into a workspace."""

    path: str = Field(..., description="Workspace-relative file path.")
    content: str = Field(..., description="Full UTF-8 text payload to persist.")


class CreateWorkspaceDirectoryRequest(AppBaseModel):
    """Request payload for creating one workspace directory."""

    path: str = Field(..., description="Workspace-relative directory path.")
