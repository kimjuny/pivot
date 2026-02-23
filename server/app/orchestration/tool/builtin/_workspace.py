"""
Shared workspace helper for built-in file-system tools.

Every tool that operates on files reads the agent's sandbox root from the
``PIVOT_WORKSPACE_DIR`` environment variable, which is injected by the
sidecar executor (or set by the local executor) before the tool runs.

If the variable is not set the current working directory is used as a
fallback, which is the correct behaviour when a tool is run standalone or
in a test.

All public helpers enforce that resolved paths stay inside the workspace
root to prevent path-traversal attacks.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_workspace_root() -> Path:
    """Return the absolute workspace root for the current execution context.

    Reads ``PIVOT_WORKSPACE_DIR`` from the environment.  Falls back to the
    current working directory when the variable is absent.

    Returns:
        Absolute, resolved :class:`~pathlib.Path` of the workspace root.
    """
    raw = os.environ.get("PIVOT_WORKSPACE_DIR", "")
    if raw:
        return Path(raw).resolve()
    return Path.cwd().resolve()


def resolve_path(relative: str | None) -> Path:
    """Resolve a user-supplied path against the workspace root.

    Empty / ``None`` inputs resolve to the workspace root itself.

    Args:
        relative: A path string that may be relative or absolute.
            Absolute paths are treated as relative to the workspace root
            (the leading ``/`` is stripped) to prevent escaping the sandbox.

    Returns:
        A resolved :class:`~pathlib.Path` guaranteed to be inside the
        workspace root.

    Raises:
        ValueError: If the resolved path would fall outside the workspace.
    """
    root = get_workspace_root()

    if not relative:
        return root

    # Strip a leading slash so that "/foo" is treated as "foo" inside the workspace
    stripped = relative.lstrip("/")
    candidate = (root / stripped).resolve()

    # Path-traversal guard
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Path '{relative}' resolves outside the workspace sandbox."
        ) from None

    return candidate
