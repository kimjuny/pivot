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

display_path = str(path).removeprefix("/workspace/") or "."
if not path.exists():
    print(f"File not found: {display_path}", file=sys.stderr)
    raise SystemExit(1)
if path.is_dir():
    print(f"Path is a directory, not a file: {display_path}", file=sys.stderr)
    raise SystemExit(1)

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
number_width = len(str(actual_end_line))
numbered_chunk = "".join(
    f"{line_number:>{number_width}} | {line}"
    for line_number, line in enumerate(chunk_lines, start=start_line)
)

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
    "content": numbered_chunk,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


@tool(tool_type="sandbox")
def read_file(
    path: str,
    start_line: int = 1,
    max_lines: int = 400,
) -> dict[str, object]:
    """Read a numbered text chunk from a UTF-8 file under ``/workspace``.

    This tool is optimized for ``search -> read -> edit`` workflows. It returns
    one chunk with stable line-number prefixes so the agent can produce
    line-accurate unified diffs for ``edit_file``. The line-number prefixes are
    display aids only; use them for ``@@`` hunk headers and remove them from
    diff body lines.

    Args:
        path (required, str): Relative or absolute workspace path to a text
            file.
        start_line (optional, int): 1-based starting line to read. Defaults to
            ``1``.
        max_lines (optional, int): Hard upper bound on returned lines from
            ``start_line``. Defaults to ``400``.

    Returns:
        Structured payload with chunk bounds, pagination hints, and numbered
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
    try:
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
    except RuntimeError as exc:
        message = str(exc)
        not_found_prefix = "Sandbox command failed (exit=1): File not found: "
        directory_prefix = (
            "Sandbox command failed (exit=1): Path is a directory, not a file: "
        )
        if message.startswith(not_found_prefix):
            raise FileNotFoundError(
                f"File not found: {message.removeprefix(not_found_prefix)}"
            ) from exc
        if message.startswith(directory_prefix):
            raise IsADirectoryError(
                f"Path is a directory, not a file: {message.removeprefix(directory_prefix)}"
            ) from exc
        raise
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox read_file returned an invalid payload.")
    return payload
