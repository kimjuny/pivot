"""Built-in sandbox tool: apply a single-file unified diff atomically."""

from __future__ import annotations

import json

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path

_EDIT_FILE_SCRIPT = r"""
from __future__ import annotations

import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
diff = sys.argv[2]

HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)
REJECTED_GIT_PREFIXES = (
    "diff --git ",
    "index ",
    "new file mode ",
    "deleted file mode ",
    "similarity index ",
    "rename from ",
    "rename to ",
)
OPTIONAL_FILE_HEADER_PREFIXES = ("--- ", "+++ ")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def display_path(value: pathlib.Path) -> str:
    return str(value).removeprefix("/workspace/") or "."


def target_relative_path(value: pathlib.Path) -> str:
    normalized = value.as_posix()
    if not normalized.startswith("/workspace/"):
        # Unit tests execute this helper script directly against temporary
        # files. Production calls pass through workspace_path() first.
        return value.name
    if normalized == "/workspace":
        fail("Path must point to a file, not /workspace.")
    return normalized.removeprefix("/workspace/")


def parse_hunk_header(line: str, hunk_index: int) -> tuple[int, int, int, int]:
    match = HUNK_HEADER_RE.match(line)
    if match is None:
        fail(f"Patch failed: hunk {hunk_index} has an invalid header.")
    old_start = int(match.group("old_start"))
    old_count = int(match.group("old_count") or "1")
    new_start = int(match.group("new_start"))
    new_count = int(match.group("new_count") or "1")
    return old_start, old_count, new_start, new_count


def parse_diff(diff_text: str) -> tuple[list[dict[str, object]], list[str]]:
    if not diff_text.strip():
        fail("edit_file expects a unified diff patch.")
    if diff_text.lstrip().startswith("```"):
        fail("Do not wrap the diff in markdown fences.")

    lines = diff_text.splitlines(keepends=True)
    for line in lines:
        if line.startswith(REJECTED_GIT_PREFIXES):
            fail("edit_file expects simplified unified diff, not full git diff metadata.")

    if len(lines) < 1:
        fail("edit_file expects at least one hunk.")

    hunks: list[dict[str, object]] = []
    warnings: list[str] = []
    index = 0
    if len(lines) >= 2 and lines[0].startswith("--- ") and lines[1].startswith("+++ "):
        index = 2
    hunk_index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith(OPTIONAL_FILE_HEADER_PREFIXES):
            fail(
                "Patch failed: file headers are only allowed before the first hunk. "
                "edit_file edits exactly one path, so pass only @@ hunks."
            )
        if not line.startswith("@@ "):
            fail(f"Patch failed: expected hunk header at diff line {index + 1}.")
        hunk_index += 1
        old_start, old_count, new_start, new_count = parse_hunk_header(
            line, hunk_index
        )
        index += 1
        old_lines: list[str] = []
        new_lines: list[str] = []
        added_line_count = 0
        removed_line_count = 0
        previous_prefix = ""
        while index < len(lines) and not lines[index].startswith("@@ "):
            body_line = lines[index]
            if body_line.startswith(OPTIONAL_FILE_HEADER_PREFIXES):
                fail(
                    "Patch failed: file headers are only allowed before the first "
                    "hunk. edit_file edits exactly one path, so pass only @@ hunks."
                )
            if body_line.startswith("\\"):
                if previous_prefix in (" ", "-") and old_lines:
                    old_lines[-1] = old_lines[-1].removesuffix("\n")
                if previous_prefix in (" ", "+") and new_lines:
                    new_lines[-1] = new_lines[-1].removesuffix("\n")
                index += 1
                continue
            if body_line == "\n":
                fail(f"Patch failed: hunk {hunk_index} contains an empty patch line.")
            prefix = body_line[:1]
            content = body_line[1:]
            if prefix == " ":
                old_lines.append(content)
                new_lines.append(content)
            elif prefix == "-":
                old_lines.append(content)
                removed_line_count += 1
            elif prefix == "+":
                new_lines.append(content)
                added_line_count += 1
            else:
                fail(
                    f"Patch failed: hunk {hunk_index} has invalid line prefix "
                    f"at diff line {index + 1}."
                )
            previous_prefix = prefix
            index += 1

        if len(old_lines) != old_count:
            warnings.append(
                f"Hunk {hunk_index} header old_count={old_count}, but its body "
                f"contains {len(old_lines)} old/context lines. edit_file used "
                "the body line count; keep counts accurate to avoid confusing "
                "future edits."
            )
        if len(new_lines) != new_count:
            warnings.append(
                f"Hunk {hunk_index} header new_count={new_count}, but its body "
                f"contains {len(new_lines)} new/context lines. edit_file used "
                "the body line count; keep counts accurate to avoid confusing "
                "future edits."
            )
        hunks.append(
            {
                "index": hunk_index,
                "old_start": old_start,
                "new_start": new_start,
                "old_lines": old_lines,
                "new_lines": new_lines,
                "added_line_count": added_line_count,
                "removed_line_count": removed_line_count,
            }
        )

    if not hunks:
        fail("edit_file expects at least one hunk.")
    return hunks, warnings


def format_preview(lines: list[str], start_line: int, limit: int = 8) -> str:
    if not lines:
        return "<empty>"
    width = len(str(start_line + min(len(lines), limit) - 1))
    preview = []
    for offset, line in enumerate(lines[:limit]):
        preview.append(f"{start_line + offset:>{width}} | {line.rstrip()}")
    if len(lines) > limit:
        preview.append(f"... ({len(lines) - limit} more line(s))")
    return "\n".join(preview)


if not path.exists():
    fail(f"Cannot edit file because it does not exist: {display_path(path)}")
if path.is_dir():
    fail(f"Cannot edit directory: {display_path(path)}")

expected_path = target_relative_path(path)
hunks, warnings = parse_diff(diff)
original_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
updated_lines = list(original_lines)
line_delta = 0

for hunk in hunks:
    hunk_index = int(hunk["index"])
    old_start = int(hunk["old_start"])
    old_lines = hunk["old_lines"]
    new_lines = hunk["new_lines"]
    if old_start == 0 and not old_lines:
        start_index = 0
    else:
        start_index = old_start - 1 + line_delta
    end_index = start_index + len(old_lines)
    if start_index < 0 or end_index > len(updated_lines):
        fail(
            f"Patch failed at hunk {hunk_index}: line range starts outside "
            "the current file. No changes were written."
        )
    current_slice = updated_lines[start_index:end_index]
    if current_slice != old_lines:
        fail(
            f"Patch failed at hunk {hunk_index}: context did not match around "
            f"original line {old_start}. old_start is the strict location anchor; "
            "edit_file will not search elsewhere because repeated code could be "
            "modified incorrectly. Re-run read_file for the current lines and try "
            "again.\nExpected old/context lines:\n"
            f"{format_preview(old_lines, old_start)}\nActual file lines there:\n"
            f"{format_preview(current_slice, old_start)}\nNo changes were written."
        )
    updated_lines[start_index:end_index] = new_lines
    line_delta += len(new_lines) - len(old_lines)

path.write_text("".join(updated_lines), encoding="utf-8")
payload = {
    "message": "Applied patch successfully.",
    "path": expected_path,
    "hunk_count": len(hunks),
    "added_lines": sum(int(hunk["added_line_count"]) for hunk in hunks),
    "removed_lines": sum(int(hunk["removed_line_count"]) for hunk in hunks),
    "warnings": warnings,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


@tool(tool_type="sandbox")
def edit_file(path: str, diff: str) -> dict[str, object]:
    """Apply simplified single-file unified diff hunks under ``/workspace``.

    Use this after ``read_file``. ``read_file`` returns line-numbered content;
    use those numbers to write accurate ``@@`` hunk headers, but do not include
    the line-number prefixes in diff body lines.

    The diff should contain only one or more ``@@`` hunks, without markdown
    fences, file headers, or full git metadata such as ``diff --git`` /
    ``index`` lines:

    @@ -10,3 +10,3 @@
     unchanged context
    -old line
    +new line

    ``old_start`` in each hunk header is the strict location anchor. The tool
    applies the hunk only at that line and will not search elsewhere, because
    repeated code could otherwise be modified incorrectly. Keep ``old_count``
    and ``new_count`` accurate too; count mismatches are tolerated with warnings,
    but accurate counts make future edits more reliable.

    Behavior:
    - Edits exactly one existing UTF-8 text file.
    - Allows multiple hunks in that one file.
    - Applies atomically: if any hunk fails, no changes are written.
    - Treats optional leading ``---``/``+++`` file headers as compatibility
      noise and ignores them; ``path`` is the only target file.

    Args:
        path (required, str): Relative or absolute workspace path to the target
            file.
        diff (required, str): Simplified unified diff hunks for that file.

    Returns:
        Structured summary with message, path, hunk_count, added_lines, and
        removed_lines, plus warnings when hunk counts are inconsistent.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails or the patch does not apply.
    """
    if not diff.strip():
        raise ValueError("diff must be a non-empty unified diff patch.")

    target = workspace_path(path)
    output = exec_in_sandbox(["python3", "-c", _EDIT_FILE_SCRIPT, target, diff])
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox edit_file returned an invalid payload.")
    return payload
