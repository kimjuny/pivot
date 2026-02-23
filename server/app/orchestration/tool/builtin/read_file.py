"""
read_file — read the content of a file inside the workspace sandbox.
"""

from __future__ import annotations

from typing import Any

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path

# Maximum number of bytes returned to avoid flooding the LLM context window.
_MAX_BYTES = 256 * 1024  # 256 KB


@tool(
    name="read_file",
    description=(
        "Read the text content of a file inside the agent's workspace sandbox. "
        "Returns the file content as a string.  Binary files are not supported. "
        "Large files are truncated at 256 KB."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the workspace root.",
            },
            "encoding": {
                "type": "string",
                "description": "Text encoding to use. Defaults to 'utf-8'.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
)
def read_file(
    path: str,
    encoding: str = "utf-8",
) -> dict[str, Any]:
    """Read a file and return its contents.

    Args:
        path: File path relative to the workspace root.
        encoding: Character encoding.  Defaults to ``"utf-8"``.

    Returns:
        A dict with ``content`` (string), ``size`` (bytes), and
        ``truncated`` (bool indicating whether the file was truncated).
    """
    try:
        target = resolve_path(path)
    except ValueError as exc:
        return {"error": str(exc)}

    if not target.exists():
        return {"error": f"File '{path}' does not exist."}
    if target.is_dir():
        return {"error": f"'{path}' is a directory, not a file."}

    size = target.stat().st_size
    truncated = size > _MAX_BYTES

    try:
        raw = target.read_bytes()
        content = raw[:_MAX_BYTES].decode(encoding, errors="replace")
    except UnicodeDecodeError:
        return {
            "error": (
                f"File '{path}' could not be decoded as {encoding}. "
                "It may be a binary file."
            )
        }
    except OSError as exc:
        return {"error": f"Could not read '{path}': {exc}"}

    return {
        "content": content,
        "size": size,
        "truncated": truncated,
    }
