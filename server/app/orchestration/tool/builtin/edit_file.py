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
ANCHOR_SEARCH_RADIUS = 5
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
        body_entries: list[tuple[str, str]] = []
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
                if previous_prefix in (" ", "-", "+") and body_entries:
                    entry_prefix, entry_content = body_entries[-1]
                    body_entries[-1] = (entry_prefix, entry_content.removesuffix("\n"))
                index += 1
                continue
            if body_line == "\n":
                fail(f"Patch failed: hunk {hunk_index} contains an empty patch line.")
            prefix = body_line[:1]
            content = body_line[1:]
            if prefix == " ":
                old_lines.append(content)
                new_lines.append(content)
                body_entries.append((prefix, content))
            elif prefix == "-":
                old_lines.append(content)
                body_entries.append((prefix, content))
                removed_line_count += 1
            elif prefix == "+":
                new_lines.append(content)
                body_entries.append((prefix, content))
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
                "body_entries": body_entries,
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


def split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def line_body(line: str) -> str:
    return split_line_ending(line)[0]


def normalized_line_bodies(lines: list[str]) -> list[str]:
    return [line_body(line) for line in lines]


def dominant_line_ending(lines: list[str]) -> str:
    counts: dict[str, int] = {"\r\n": 0, "\n": 0, "\r": 0}
    for line in lines:
        ending = split_line_ending(line)[1]
        if ending:
            counts[ending] += 1
    return max(counts, key=lambda ending: counts[ending]) if any(counts.values()) else "\n"


def line_ending_near(lines: list[str], old_cursor: int, fallback: str) -> str:
    if 0 <= old_cursor - 1 < len(lines):
        previous = split_line_ending(lines[old_cursor - 1])[1]
        if previous:
            return previous
    if 0 <= old_cursor < len(lines):
        current = split_line_ending(lines[old_cursor])[1]
        if current:
            return current
    return fallback


def materialize_new_lines(
    body_entries: list[tuple[str, str]],
    current_slice: list[str],
    fallback_line_ending: str,
) -> list[str]:
    materialized: list[str] = []
    old_cursor = 0
    for prefix, content in body_entries:
        if prefix == " ":
            materialized.append(current_slice[old_cursor])
            old_cursor += 1
            continue
        if prefix == "-":
            old_cursor += 1
            continue
        body, ending = split_line_ending(content)
        if ending:
            ending = line_ending_near(current_slice, old_cursor, fallback_line_ending)
        materialized.append(f"{body}{ending}")
    return materialized


def find_nearby_unique_match(
    lines: list[str],
    old_lines: list[str],
    expected_start_index: int,
    radius: int,
) -> list[int]:
    if not old_lines:
        return []

    old_bodies = normalized_line_bodies(old_lines)
    max_start_index = len(lines) - len(old_lines)
    if max_start_index < 0:
        return []

    window_start = max(0, expected_start_index - radius)
    window_end = min(max_start_index, expected_start_index + radius)
    matches: list[int] = []
    for candidate_start in range(window_start, window_end + 1):
        candidate_slice = lines[candidate_start : candidate_start + len(old_lines)]
        if normalized_line_bodies(candidate_slice) == old_bodies:
            matches.append(candidate_start)
    return matches


if not path.exists():
    fail(f"Cannot edit file because it does not exist: {display_path(path)}")
if path.is_dir():
    fail(f"Cannot edit directory: {display_path(path)}")

expected_path = target_relative_path(path)
hunks, warnings = parse_diff(diff)
with path.open("r", encoding="utf-8", newline="") as source_file:
    original_lines = source_file.read().splitlines(keepends=True)
updated_lines = list(original_lines)
fallback_line_ending = dominant_line_ending(original_lines)
line_delta = 0

for hunk in hunks:
    hunk_index = int(hunk["index"])
    old_start = int(hunk["old_start"])
    old_lines = hunk["old_lines"]
    body_entries = hunk["body_entries"]
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
    if normalized_line_bodies(current_slice) != normalized_line_bodies(old_lines):
        nearby_matches = find_nearby_unique_match(
            updated_lines,
            old_lines,
            start_index,
            ANCHOR_SEARCH_RADIUS,
        )
        if len(nearby_matches) == 1:
            corrected_start_index = nearby_matches[0]
            corrected_old_start = corrected_start_index - line_delta + 1
            warnings.append(
                f"Hunk {hunk_index} header old_start={old_start} did not match "
                f"exactly. edit_file applied the hunk at nearby original line "
                f"{corrected_old_start} after finding a unique match within "
                f"+/-{ANCHOR_SEARCH_RADIUS} lines."
            )
            start_index = corrected_start_index
            end_index = start_index + len(old_lines)
            current_slice = updated_lines[start_index:end_index]
        else:
            current_line = start_index + 1
            search_result = (
                "no nearby match"
                if not nearby_matches
                else "multiple nearby matches at original lines "
                + ", ".join(str(candidate - line_delta + 1) for candidate in nearby_matches)
            )
            fail(
                f"Patch failed at hunk {hunk_index}: context did not match at "
                f"original line {old_start} (current file line {current_line}). "
                f"edit_file searched within +/-{ANCHOR_SEARCH_RADIUS} lines and "
                f"found {search_result}. Re-run read_file for the current lines "
                "and try again.\nExpected old/context lines:\n"
                f"{format_preview(old_lines, old_start)}\nActual file lines there:\n"
                f"{format_preview(current_slice, current_line)}\nNo changes were written."
            )
    new_lines = materialize_new_lines(body_entries, current_slice, fallback_line_ending)
    updated_lines[start_index:end_index] = new_lines
    line_delta += len(new_lines) - len(old_lines)

with path.open("w", encoding="utf-8", newline="") as target_file:
    target_file.write("".join(updated_lines))
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
    """Apply simplified unified diff hunks to one file under ``/workspace``.

    Use this after ``read_file``. The ``read_file`` line numbers are snapshot
    data, so after any successful write to the same file you must re-run
    ``read_file`` before editing that file again.

    IMPORTANT:
    - In one recursion, call ``edit_file`` at most once per file.
    - If one file needs multiple changes, send one ``edit_file`` call with
      multiple ``@@`` hunks instead of multiple calls.
    - Use the ``read_file`` numbers in hunk headers, but never include the
      ``N | `` prefixes in diff body lines.
    - ``old_start`` should point to the first old/context line. The tool tries
      that exact anchor first, then may auto-correct within a small nearby
      window when the old/context block has one unique match.
    - Keep ``old_count`` and ``new_count`` accurate; mismatches only warn today,
      but they make future edits less reliable.

    Example with multiple hunks:

    @@ -10,3 +10,3 @@
     unchanged context
    -old line
    +new line
    @@ -40,2 +40,3 @@
     another context line
    +inserted line
     final context line

    Args:
        path (required, str): Target file path under ``/workspace``.
        diff (required, str): Simplified unified diff hunks for that file.

    Returns:
        A dict with message, path, hunk_count, line counts, and warnings.
    """
    if not diff.strip():
        raise ValueError("diff must be a non-empty unified diff patch.")

    target = workspace_path(path)
    output = exec_in_sandbox(["python3", "-c", _EDIT_FILE_SCRIPT, target, diff])
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox edit_file returned an invalid payload.")
    return payload
