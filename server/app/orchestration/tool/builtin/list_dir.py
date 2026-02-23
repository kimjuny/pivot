"""
list_dir — print an ASCII tree of the workspace directory structure.

Complements list_files (which returns structured JSON) by providing a
human-readable tree that fits naturally in an LLM prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path

# Hard cap on entries to prevent enormous outputs
_MAX_ENTRIES = 500


def _tree(
    directory: Path,
    root: Path,
    prefix: str = "",
    depth: int = 0,
    max_depth: int | None = None,
    counter: list[int] | None = None,
) -> list[str]:
    """Recursively build an ASCII-art directory tree.

    Args:
        directory: Current directory to expand.
        root: Workspace root (used for relative paths in output).
        prefix: Current line prefix for tree drawing.
        depth: Current recursion depth.
        max_depth: Maximum recursion depth (None = unlimited).
        counter: Mutable single-element list tracking total entries emitted.

    Returns:
        List of formatted tree lines.
    """
    if counter is None:
        counter = [0]

    lines: list[str] = []

    if max_depth is not None and depth >= max_depth:
        return lines

    try:
        children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return [f"{prefix}[permission denied]"]

    for i, child in enumerate(children):
        if counter[0] >= _MAX_ENTRIES:
            lines.append(f"{prefix}... (truncated, >{_MAX_ENTRIES} entries)")
            break

        is_last = i == len(children) - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if child.is_dir() else ""
        lines.append(f"{prefix}{connector}{child.name}{suffix}")
        counter[0] += 1

        if child.is_dir():
            extension = "    " if is_last else "│   "
            lines.extend(
                _tree(
                    child,
                    root,
                    prefix=prefix + extension,
                    depth=depth + 1,
                    max_depth=max_depth,
                    counter=counter,
                )
            )

    return lines


@tool(
    name="list_dir",
    description=(
        "Display the directory structure of the agent's workspace sandbox as an "
        "ASCII tree — similar to the Unix 'tree' command.  Useful for quickly "
        "understanding the overall layout of the workspace."
    ),
    parameters={
        "type": "object",
        "properties": {
            "dir": {
                "type": "string",
                "description": (
                    "Root directory to display, relative to the workspace root. "
                    "Defaults to the workspace root."
                ),
            },
            "max_depth": {
                "type": "integer",
                "description": (
                    "Maximum depth to recurse. "
                    "Defaults to 3.  Set to 0 for unlimited depth."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
def list_dir(
    dir: str | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Display the workspace directory tree.

    Args:
        dir: Root directory relative to workspace root.  Defaults to workspace root.
        max_depth: Maximum traversal depth.  ``0`` means unlimited.  Defaults to 3.

    Returns:
        A dict with ``tree`` (multi-line ASCII string) and ``root``
        (the displayed directory relative to the workspace root).
    """
    try:
        target = resolve_path(dir)
    except ValueError as exc:
        return {"error": str(exc)}

    if not target.exists():
        return {"error": f"Directory '{dir}' does not exist."}
    if not target.is_dir():
        return {"error": f"'{dir}' is a file, not a directory."}

    root = resolve_path(None)
    root_label = str(target.relative_to(root)) if target != root else "."

    depth_limit: int | None = max_depth if max_depth > 0 else None

    lines = [f"{root_label}/"]
    lines.extend(_tree(target, root, max_depth=depth_limit))

    return {
        "root": root_label,
        "tree": "\n".join(lines),
    }
