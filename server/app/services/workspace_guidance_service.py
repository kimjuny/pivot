"""Workspace guidance discovery helpers for ReAct task bootstrapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.workspace_runtime_file_service import WorkspaceRuntimeFileService

if TYPE_CHECKING:
    from app.services.workspace_storage_service import WorkspaceMountSpec


def build_workspace_guidance_prompt(
    *,
    username: str,
    mount_spec: WorkspaceMountSpec,
) -> str:
    """Build one markdown prompt block for the active workspace guidance file.

    Args:
        username: Authenticated username used to reach sandbox-manager.
        mount_spec: Runtime workspace mount identity.

    Returns:
        Markdown text containing the canonical sandbox path plus the full file
        contents. Returns an empty string when no guidance file exists.
    """
    discovered_guidance = WorkspaceRuntimeFileService().read_guidance_file(
        username=username,
        mount_spec=mount_spec,
    )
    if discovered_guidance is None:
        return ""

    sandbox_path, content = discovered_guidance
    return f"# {sandbox_path}\n\n{content}" if content else f"# {sandbox_path}"
