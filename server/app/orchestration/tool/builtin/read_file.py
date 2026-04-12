"""Built-in sandbox tool: read a focused chunk from a workspace file."""

from __future__ import annotations

import json

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path

_READ_FILE_SCRIPT = """
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
start_line = int(sys.argv[2])
max_lines = int(sys.argv[3])

text = path.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines(keepends=True)
total_lines = len(lines)

if total_lines == 0:
    payload = {
        "path": str(path).removeprefix("/workspace/") or ".",
        "total_lines": 0,
        "start_line": 1,
        "end_line": 0,
        "returned_line_count": 0,
        "has_more_before": False,
        "has_more_after": False,
        "truncated": False,
        "next_start_line": None,
        "previous_start_line": None,
        "content": "",
    }
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

if start_line > total_lines:
    raise RuntimeError(
        f"start_line {start_line} exceeds file length ({total_lines} lines)"
    )

actual_end_line = min(total_lines, start_line + max_lines - 1)
chunk_lines = lines[start_line - 1 : actual_end_line]

payload = {
    "path": str(path).removeprefix("/workspace/") or ".",
    "total_lines": total_lines,
    "start_line": start_line,
    "end_line": actual_end_line,
    "returned_line_count": len(chunk_lines),
    "has_more_before": start_line > 1,
    "has_more_after": actual_end_line < total_lines,
    "truncated": actual_end_line < total_lines,
    "next_start_line": actual_end_line + 1 if actual_end_line < total_lines else None,
    "previous_start_line": max(1, start_line - max_lines) if start_line > 1 else None,
    "content": "".join(chunk_lines),
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


@tool(tool_type="sandbox")
def read_file(
    path: str,
    start_line: int = 1,
    max_lines: int = 400,
) -> dict[str, object]:
    """Read an exact text chunk from a UTF-8 file under ``/workspace``.

    This tool is optimized for ``search -> read -> edit`` workflows. It returns
    the original text exactly as it appears in the file so the agent can pass
    precise snippets into ``edit_file`` without stripping synthetic line-number
    prefixes. Chunk metadata is still included to help with pagination.

    Args:
        path: Relative or absolute workspace path to a text file.
        start_line: 1-based starting line to read.
        max_lines: Hard upper bound on returned lines from ``start_line``. This
            keeps reads focused while still allowing larger single-pass reads.

    Returns:
        Structured payload with chunk bounds, pagination hints, and exact file
        ``content`` for the requested line range.

    Raises:
        ValueError: If path escapes ``/workspace`` or line arguments are invalid.
        RuntimeError: If sandbox execution fails.
    """
    if start_line < 1:
        raise ValueError("start_line must be greater than or equal to 1.")
    if max_lines < 1:
        raise ValueError("max_lines must be greater than or equal to 1.")
    if max_lines > 800:
        raise ValueError("max_lines must be less than or equal to 800.")

    target = workspace_path(path)
    output = exec_in_sandbox(
        [
            "python3",
            "-c",
            _READ_FILE_SCRIPT,
            target,
            str(start_line),
            str(max_lines),
        ]
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox read_file returned an invalid payload.")
    return payload
