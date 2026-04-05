"""Workspace guidance discovery helpers for ReAct task bootstrapping."""

from __future__ import annotations

from pathlib import Path

_PRIORITIZED_GUIDANCE_FILENAMES = ("AGENTS.md", "CLAUDE.md")
_SANDBOX_WORKSPACE_ROOT = Path("/workspace")


def discover_workspace_guidance_file(
    workspace_path: Path | None,
) -> tuple[Path, str] | None:
    """Return the highest-priority workspace guidance file, if one exists.

    Args:
        workspace_path: Host-side directory mapped to sandbox ``/workspace``.

    Returns:
        Tuple of ``(host_path, sandbox_path)`` for the selected file, or
        ``None`` when the workspace has no supported guidance file.
    """
    if workspace_path is None:
        return None

    for filename in _PRIORITIZED_GUIDANCE_FILENAMES:
        candidate = workspace_path / filename
        if candidate.is_file():
            sandbox_path = (_SANDBOX_WORKSPACE_ROOT / filename).as_posix()
            return candidate, sandbox_path
    return None


def build_workspace_guidance_prompt(workspace_path: Path | None) -> str:
    """Build one markdown prompt block for the active workspace guidance file.

    Args:
        workspace_path: Host-side directory mapped to sandbox ``/workspace``.

    Returns:
        Markdown text containing the canonical sandbox path plus the full file
        contents. Returns an empty string when no guidance file exists.
    """
    discovered_guidance = discover_workspace_guidance_file(workspace_path)
    if discovered_guidance is None:
        return ""

    host_path, sandbox_path = discovered_guidance
    content = host_path.read_text(encoding="utf-8").strip()
    return f"# {sandbox_path}\n\n{content}" if content else f"# {sandbox_path}"
