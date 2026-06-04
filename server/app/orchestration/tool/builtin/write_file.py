"""Built-in sandbox tool: write file content in agent workspace."""

from __future__ import annotations

import json
from typing import Annotated

from app.orchestration.tool import (
    Param,
    get_current_tool_execution_context,
    tool,
)

from ._sandbox_common import exec_in_sandbox, workspace_path

_WRITE_FILE_SCRIPT = r"""
from __future__ import annotations

import difflib
import hashlib
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
content = sys.argv[2]
expected_hash = sys.argv[3]


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def display_path(value: pathlib.Path) -> str:
    return str(value).removeprefix("/workspace/") or "."


def target_relative_path(value: pathlib.Path) -> str:
    normalized = value.as_posix()
    if not normalized.startswith("/workspace/"):
        return value.name
    if normalized == "/workspace":
        fail("Path must point to a file, not /workspace.")
    return normalized.removeprefix("/workspace/")


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()


def line_count(text: str) -> int:
    return 0 if text == "" else len(text.splitlines())


def build_diff(relative_path: str, original_text: str, updated_text: str) -> str:
    return "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )


def count_diff_lines(diff_text: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions


if path.exists() and path.is_dir():
    fail(f"Cannot write directory: {display_path(path)}")

relative_path = target_relative_path(path)
file_exists = path.exists()
if file_exists:
    with path.open("r", encoding="utf-8", newline="") as source_file:
        original_text = source_file.read()
    current_hash = content_hash(original_text)
    if not expected_hash:
        fail(f"Read the full file with read_file before overwriting it: {relative_path}")
    if current_hash != expected_hash:
        fail(
            "File has changed since it was read. "
            f"Re-run read_file on this file before writing it: {relative_path}"
        )
    write_type = "update"
else:
    original_text = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_type = "create"

with path.open("w", encoding="utf-8", newline="") as target_file:
    target_file.write(content)

diff = build_diff(relative_path, original_text, content) if file_exists else ""
added_lines, removed_lines = count_diff_lines(diff)
final_hash = content_hash(content)
payload = {
    "message": f"Wrote file: {relative_path}",
    "path": relative_path,
    "type": write_type,
    "added_lines": added_lines,
    "removed_lines": removed_lines,
    "diff": diff,
    "content_hash": final_hash,
    "total_lines": line_count(content),
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


def _expected_hash_for_write(path: str) -> str:
    """Return tracked hash when the session has fully read this file."""
    ctx = get_current_tool_execution_context()
    if ctx is None or not ctx.session_id or ctx.db_session_factory is None:
        return ""

    from app.services.file_read_tracker_service import FileReadTrackerService

    with ctx.db_session_factory() as db:
        try:
            return FileReadTrackerService(db).require_full_read_hash(
                session_id=ctx.session_id,
                path=path,
            )
        except RuntimeError:
            return ""


def _record_full_file_state(path: str, content_hash: str, total_lines: int) -> None:
    """Record the post-write file state for this session when possible."""
    ctx = get_current_tool_execution_context()
    if ctx is None or not ctx.session_id or ctx.db_session_factory is None:
        return

    from app.services.file_read_tracker_service import FileReadTrackerService

    with ctx.db_session_factory() as db:
        FileReadTrackerService(db).record_full_file_state(
            session_id=ctx.session_id,
            path=path,
            content_hash=content_hash,
            total_lines=total_lines,
        )


@tool(
    description=(
        "Write UTF-8 text to a file under /workspace. Creates parent directories "
        "automatically. Use this for new files or complete rewrites. Existing "
        "files must be fully read with read_file first; prefer edit_file for "
        "small modifications."
    ),
    tool_type="sandbox",
)
def write_file(
    path: Annotated[
        str,
        Param(
            "Absolute /workspace/... path to the target file. "
            "Workspace-relative paths are accepted but absolute sandbox paths are clearer."
        ),
    ],
    content: Annotated[
        str,
        Param("UTF-8 text content to write. Expects a string, not a JSON object."),
    ],
) -> dict[str, object]:
    """Write UTF-8 text to a file under ``/workspace``."""
    target = workspace_path(path)
    relative_path = target.removeprefix("/workspace/") or "."
    output = exec_in_sandbox(
        [
            "python3",
            "-c",
            _WRITE_FILE_SCRIPT,
            target,
            content,
            _expected_hash_for_write(relative_path),
        ]
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox write_file returned an invalid payload.")

    _record_full_file_state(
        str(payload.get("path", relative_path)),
        str(payload.get("content_hash", "")),
        int(payload.get("total_lines", 0)),
    )
    return payload
