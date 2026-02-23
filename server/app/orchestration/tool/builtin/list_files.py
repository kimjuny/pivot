"""
list_files — list directory contents with metadata.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _entry(path: Path, root: Path) -> dict[str, Any]:
    """Build a metadata dict for a single filesystem entry."""
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path.relative_to(root)),
        "type": "directory" if path.is_dir() else "file",
        "size": stat.st_size if path.is_file() else None,
        "last_modified": _fmt_time(stat.st_mtime),
    }


def _list_recursive(directory: Path, root: Path) -> list[dict[str, Any]]:
    """Recursively build the entry list for *directory*."""
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
    except PermissionError:
        return entries

    for child in children:
        entry = _entry(child, root)
        if child.is_dir():
            entry["children"] = _list_recursive(child, root)
        entries.append(entry)
    return entries


@tool(
    name="list_files",
    description=(
        "List files and directories inside the agent's workspace sandbox. "
        "Returns metadata (name, relative path, type, size, last_modified) "
        "for each entry.  Set recursive=true to traverse sub-directories."
    ),
    parameters={
        "type": "object",
        "properties": {
            "dir": {
                "type": "string",
                "description": (
                    "Directory to list, relative to the workspace root. "
                    "Defaults to the workspace root when omitted."
                ),
            },
            "recursive": {
                "type": "boolean",
                "description": (
                    "When true, list all files and directories recursively "
                    "including nested sub-directories. Defaults to false."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
def list_files(
    dir: str | None = None,
    recursive: bool = False,
) -> dict[str, Any]:
    """List directory contents with metadata.

    Args:
        dir: Directory path relative to the workspace root.
             Defaults to the workspace root.
        recursive: When True, traverse sub-directories recursively.

    Returns:
        A dict with ``cwd`` (the listed directory relative to workspace root)
        and ``entries`` (list of file/directory metadata dicts).  Each entry
        contains ``name``, ``path``, ``type``, ``size``, and ``last_modified``.
        Directory entries additionally carry a ``children`` key when
        *recursive* is True.
    """
    target = resolve_path(dir)
    root = target if not dir else resolve_path(None)

    if not target.exists():
        return {"error": f"Directory '{dir}' does not exist."}
    if not target.is_dir():
        return {"error": f"'{dir}' is a file, not a directory."}

    cwd_rel = str(target.relative_to(root)) if target != root else "."

    if recursive:
        entries = _list_recursive(target, root)
    else:
        entries = []
        try:
            children = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return {"error": f"Permission denied reading '{dir}'."}
        for child in children:
            entry = _entry(child, root)
            if child.is_dir():
                # Show directory child count even in non-recursive mode
                try:
                    entry["child_count"] = sum(1 for _ in child.iterdir())
                except PermissionError:
                    entry["child_count"] = None
            entries.append(entry)

    return {
        "cwd": cwd_rel,
        "entries": entries,
        "total": len(entries),
    }
