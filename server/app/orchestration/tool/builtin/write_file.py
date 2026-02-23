"""
write_file — create or overwrite a file inside the workspace sandbox.
"""

from __future__ import annotations

from typing import Any

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path


@tool(
    name="write_file",
    description=(
        "Create a new file or completely overwrite an existing file inside the "
        "agent's workspace sandbox.  Parent directories are created automatically. "
        "Use edit_file when you only need to change part of an existing file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Destination file path relative to the workspace root.",
            },
            "content": {
                "type": "string",
                "description": "Full text content to write to the file.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding to use. Defaults to 'utf-8'.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
)
def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Write content to a file, creating it (and parent dirs) if necessary.

    Args:
        path: Destination path relative to the workspace root.
        content: Full text content to write.
        encoding: Character encoding.  Defaults to ``"utf-8"``.

    Returns:
        A dict with ``path`` (relative path written) and ``size`` (bytes written).
    """
    try:
        target = resolve_path(path)
    except ValueError as exc:
        return {"error": str(exc)}

    if target.is_dir():
        return {"error": f"'{path}' is an existing directory, cannot write a file there."}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode(encoding)
        target.write_bytes(encoded)
    except OSError as exc:
        return {"error": f"Could not write '{path}': {exc}"}

    return {
        "path": path,
        "size": len(encoded),
    }
