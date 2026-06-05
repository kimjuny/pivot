"""Built-in sandbox tool: edit a file with exact string replacement."""

from __future__ import annotations

import json
from typing import Annotated

from app.orchestration.tool import Param, get_current_tool_execution_context, tool

from ._sandbox_common import (
    exec_in_sandbox,
    verify_backend_visible_text_file,
    workspace_path,
)

_EDIT_FILE_SCRIPT = r"""
from __future__ import annotations

import contextlib
import difflib
import hashlib
import json
import os
import pathlib
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
old_string = sys.argv[2]
new_string = sys.argv[3]
replace_all = sys.argv[4].lower() == "true"
expected_hash = sys.argv[5]


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


def write_text_durably(target_path: pathlib.Path, text: str) -> None:
    def fsync_best_effort(fd: int) -> None:
        with contextlib.suppress(OSError):
            os.fsync(fd)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.",
        suffix=".tmp",
        dir=str(target_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as target_file:
            target_file.write(text)
            target_file.flush()
            fsync_best_effort(target_file.fileno())
        os.replace(temp_name, target_path)
        dir_fd = os.open(target_path.parent, os.O_RDONLY)
        try:
            fsync_best_effort(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise


if old_string == new_string:
    fail("No changes to make: old_string and new_string are exactly the same.")
if path.exists() and path.is_dir():
    fail(f"Cannot edit directory: {display_path(path)}")

relative_path = target_relative_path(path)
file_exists = path.exists()

if file_exists:
    with path.open("r", encoding="utf-8", newline="") as source_file:
        original_text = source_file.read()

    current_hash = content_hash(original_text)
    if not expected_hash:
        fail(f"Read the full file with read_file before editing it: {relative_path}")
    if current_hash != expected_hash:
        fail(
            "File has changed since it was read. "
            f"Re-run read_file on this file before editing it: {relative_path}"
        )

    if old_string == "":
        if original_text != "":
            fail("Cannot create new file because the target file already exists.")
        updated_text = new_string
        replacement_count = 1
    else:
        replacement_count = original_text.count(old_string)
        if replacement_count == 0:
            fail(f"String to replace not found in file: {relative_path}")
        if replacement_count > 1 and not replace_all:
            fail(
                f"Found {replacement_count} matches of old_string in {relative_path}. "
                "Provide a more specific old_string or set replace_all=true."
            )
        updated_text = (
            original_text.replace(old_string, new_string)
            if replace_all
            else original_text.replace(old_string, new_string, 1)
        )
        if not replace_all:
            replacement_count = 1
else:
    if old_string != "":
        fail(f"Cannot edit file because it does not exist: {relative_path}")
    original_text = ""
    updated_text = new_string
    replacement_count = 1

if updated_text == original_text:
    fail("Original and edited file match exactly. No changes were written.")

write_text_durably(path, updated_text)

diff = build_diff(relative_path, original_text, updated_text)
added_lines, removed_lines = count_diff_lines(diff)
final_hash = content_hash(updated_text)
payload = {
    "message": "Edited file successfully.",
    "path": relative_path,
    "replacement_count": replacement_count,
    "added_lines": added_lines,
    "removed_lines": removed_lines,
    "diff": diff,
    "content_hash": final_hash,
    "total_lines": line_count(updated_text),
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


def _expected_hash_for_edit(path: str, old_string: str) -> str:
    """Return the full-read hash for existing-file edits when available."""
    ctx = get_current_tool_execution_context()
    if ctx is None or not ctx.session_id or ctx.db_session_factory is None:
        if old_string != "":
            raise RuntimeError("edit_file requires read_file before editing a file.")
        return ""

    from app.services.file_read_tracker_service import FileReadTrackerService

    with ctx.db_session_factory() as db:
        service = FileReadTrackerService(db)
        try:
            return service.require_full_read_hash(session_id=ctx.session_id, path=path)
        except RuntimeError:
            if old_string != "":
                raise
            return ""


def _record_full_file_state(path: str, content_hash: str, total_lines: int) -> None:
    """Record the post-edit file state for this session when possible."""
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
        "Edit one UTF-8 text file under /workspace by exact string replacement. "
        "ALWAYS call read_file on an existing target file first, then copy the "
        "exact text to replace into old_string. old_string must be unique unless "
        "replace_all=true. Do not pass unified diffs or line numbers."
    ),
    tool_type="sandbox",
)
def edit_file(
    path: Annotated[str, Param("Target file path under /workspace.")],
    old_string: Annotated[str, Param("Exact text to replace.")],
    new_string: Annotated[str, Param("Replacement text.")],
    replace_all: Annotated[
        bool,
        Param("Replace all occurrences of old_string. Defaults to false."),
    ] = False,
) -> dict[str, object]:
    """Edit a file under ``/workspace`` with exact string replacement."""
    target = workspace_path(path)
    relative_path = target.removeprefix("/workspace/") or "."
    expected_hash = _expected_hash_for_edit(relative_path, old_string)
    output = exec_in_sandbox(
        [
            "python3",
            "-c",
            _EDIT_FILE_SCRIPT,
            target,
            old_string,
            new_string,
            "true" if replace_all else "false",
            expected_hash,
        ]
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox edit_file returned an invalid payload.")

    result_path = str(payload.get("path", relative_path))
    result_hash = str(payload.get("content_hash", ""))
    result_total_lines = int(payload.get("total_lines", 0))
    verify_backend_visible_text_file(
        result_path,
        expected_hash=result_hash,
        expected_total_lines=result_total_lines,
    )
    _record_full_file_state(
        result_path,
        result_hash,
        result_total_lines,
    )
    return payload
