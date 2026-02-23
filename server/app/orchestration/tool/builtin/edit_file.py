"""
edit_file — apply a targeted patch to an existing file in the workspace sandbox.

Supports two complementary edit strategies:

- **replace**: replace the first (or all) occurrence(s) of ``old_str`` with
  ``new_str``.  Raises an error if ``old_str`` is not found or is ambiguous
  (appears more than once when ``replace_all`` is False).
- **insert**: insert ``new_str`` after a specific line number (1-based).
"""

from __future__ import annotations

from typing import Any, Literal

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path


@tool(
    name="edit_file",
    description=(
        "Apply a targeted edit to an existing file inside the agent's workspace "
        "sandbox without rewriting the entire file. "
        "Two modes are available: "
        "'replace' — find and replace a substring; "
        "'insert'  — insert text after a given line number."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the workspace root.",
            },
            "mode": {
                "type": "string",
                "enum": ["replace", "insert"],
                "description": (
                    "'replace': substitute old_str with new_str. "
                    "'insert': insert new_str after after_line."
                ),
            },
            "old_str": {
                "type": "string",
                "description": (
                    "[replace mode] The exact string to find and replace. "
                    "Must match the file content exactly (whitespace included)."
                ),
            },
            "new_str": {
                "type": "string",
                "description": "The replacement string (replace) or the text to insert (insert).",
            },
            "replace_all": {
                "type": "boolean",
                "description": (
                    "[replace mode] When true, replace every occurrence of old_str. "
                    "Defaults to false (replace only the first occurrence)."
                ),
            },
            "after_line": {
                "type": "integer",
                "description": (
                    "[insert mode] Insert new_str after this 1-based line number. "
                    "Use 0 to insert before the first line."
                ),
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding.  Defaults to 'utf-8'.",
            },
        },
        "required": ["path", "mode", "new_str"],
        "additionalProperties": False,
    },
)
def edit_file(
    path: str,
    mode: Literal["replace", "insert"],
    new_str: str,
    old_str: str | None = None,
    replace_all: bool = False,
    after_line: int = 0,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Apply a targeted edit to an existing file.

    Args:
        path: File path relative to the workspace root.
        mode: ``"replace"`` to substitute a substring;
              ``"insert"`` to add lines at a specific position.
        new_str: Replacement text (replace) or text to insert (insert).
        old_str: [replace] Exact substring to find and replace.
        replace_all: [replace] Replace every occurrence when True.
        after_line: [insert] Insert after this line number (1-based; 0 = prepend).
        encoding: Character encoding.  Defaults to ``"utf-8"``.

    Returns:
        A dict with ``path``, ``lines_before``, ``lines_after``, and
        ``changes`` (number of replacements made or 1 for insert).
    """
    try:
        target = resolve_path(path)
    except ValueError as exc:
        return {"error": str(exc)}

    if not target.exists():
        return {"error": f"File '{path}' does not exist."}
    if target.is_dir():
        return {"error": f"'{path}' is a directory."}

    try:
        original = target.read_text(encoding=encoding)
    except OSError as exc:
        return {"error": f"Could not read '{path}': {exc}"}

    lines_before = original.count("\n") + 1

    if mode == "replace":
        if not old_str:
            return {"error": "old_str is required for replace mode."}

        count = original.count(old_str)
        if count == 0:
            return {"error": f"old_str not found in '{path}'."}
        if count > 1 and not replace_all:
            return {
                "error": (
                    f"old_str appears {count} times in '{path}'. "
                    "Set replace_all=true to replace all occurrences, or "
                    "provide more context to make it unique."
                )
            }

        if replace_all:
            updated = original.replace(old_str, new_str)
            changes = count
        else:
            updated = original.replace(old_str, new_str, 1)
            changes = 1

    elif mode == "insert":
        lines = original.splitlines(keepends=True)
        # Clamp after_line to valid range
        insert_at = max(0, min(after_line, len(lines)))
        # Ensure new_str ends with a newline so subsequent lines aren't joined
        insert_text = new_str if new_str.endswith("\n") else new_str + "\n"
        lines.insert(insert_at, insert_text)
        updated = "".join(lines)
        changes = 1

    else:
        return {"error": f"Unknown mode '{mode}'. Use 'replace' or 'insert'."}

    try:
        target.write_text(updated, encoding=encoding)
    except OSError as exc:
        return {"error": f"Could not write '{path}': {exc}"}

    lines_after = updated.count("\n") + 1

    return {
        "path": path,
        "lines_before": lines_before,
        "lines_after": lines_after,
        "changes": changes,
    }
