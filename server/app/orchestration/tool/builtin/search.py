"""Built-in sandbox tool: search workspace files with ripgrep."""

from __future__ import annotations

import json

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path

_SEARCH_SCRIPT = """
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys

MAX_PREVIEW_CHARS = 140


def _decode_rg_value(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    text = value.get("text")
    if isinstance(text, str):
        return text
    raw_bytes = value.get("bytes")
    if isinstance(raw_bytes, str):
        return base64.b64decode(raw_bytes).decode("utf-8", errors="replace")
    return ""


def _normalize_preview(text: str) -> str:
    preview = text.rstrip("\\n").strip()
    if len(preview) <= MAX_PREVIEW_CHARS:
        return preview
    return preview[: MAX_PREVIEW_CHARS - 3].rstrip() + "..."


target_path = sys.argv[1]
query = sys.argv[2]
regex = sys.argv[3] == "1"
case_sensitive = sys.argv[4] == "1"
max_candidates = int(sys.argv[5])
max_hits_per_file = int(sys.argv[6])

command = [
    "rg",
    "--json",
    "--line-number",
    "--with-filename",
    "--color",
    "never",
]
if not regex:
    command.append("--fixed-strings")
if case_sensitive:
    command.append("--case-sensitive")
else:
    command.append("--ignore-case")
command.extend([query, target_path])

completed = subprocess.run(
    command,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
    check=False,
)
if completed.returncode not in (0, 1):
    sys.stderr.write(completed.stderr)
    raise SystemExit(completed.returncode)

files: dict[str, dict[str, object]] = {}
for raw_line in completed.stdout.splitlines():
    event = json.loads(raw_line)
    if event.get("type") != "match":
        continue

    data = event.get("data", {})
    absolute_path = _decode_rg_value(data.get("path"))
    relative_path = absolute_path
    if absolute_path.startswith("/workspace/"):
        relative_path = os.path.relpath(absolute_path, "/workspace")
    elif absolute_path == "/workspace":
        relative_path = "."

    line_number = int(data.get("line_number", 0))
    entry = files.setdefault(
        relative_path,
        {
            "path": relative_path,
            "match_count": 0,
            "first_match_line": line_number,
            "last_match_line": line_number,
            "anchors": [],
        },
    )
    entry["match_count"] = int(entry["match_count"]) + 1
    entry["first_match_line"] = min(int(entry["first_match_line"]), line_number)
    entry["last_match_line"] = max(int(entry["last_match_line"]), line_number)

    anchors = entry["anchors"]
    if isinstance(anchors, list) and len(anchors) < max_hits_per_file:
        anchors.append(
            {
                "line_number": line_number,
                "preview": _normalize_preview(_decode_rg_value(data.get("lines"))),
            }
        )

candidates = sorted(
    files.values(),
    key=lambda item: (
        -int(item["match_count"]),
        int(item["first_match_line"]),
        str(item["path"]),
    ),
)
limited_candidates = candidates[:max_candidates]
for candidate in limited_candidates:
    anchors = candidate.get("anchors", [])
    candidate["anchors_truncated"] = (
        isinstance(anchors, list) and int(candidate["match_count"]) > len(anchors)
    )

payload = {
    "query": query,
    "path": (
        "."
        if target_path == "/workspace"
        else os.path.relpath(target_path, "/workspace")
    ),
    "regex": regex,
    "case_sensitive": case_sensitive,
    "max_candidates": max_candidates,
    "max_hits_per_file": max_hits_per_file,
    "total_matching_files": len(candidates),
    "returned_candidate_count": len(limited_candidates),
    "truncated": len(candidates) > max_candidates,
    "candidates": limited_candidates,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


@tool(tool_type="sandbox")
def search(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_sensitive: bool = False,
    max_candidates: int = 8,
    max_hits_per_file: int = 3,
) -> dict[str, object]:
    """Search workspace files and return a compact list of read candidates.

    This tool is intentionally terse: it should help the agent decide *where to
    read next*, not dump enough source text to replace ``read_file``.

    Args:
        query (required, str): Text or regex pattern to search for. Must not be
            blank.
        path (optional, str): Relative or absolute workspace path to search
            under. Defaults to ``.``.
        regex (optional, bool): Whether ``query`` should be treated as a
            ripgrep regex. Defaults to ``False``.
        case_sensitive (optional, bool): Whether matching should preserve case.
            Defaults to ``False``.
        max_candidates (optional, int): Maximum number of files returned as
            read candidates. Defaults to ``8``.
        max_hits_per_file (optional, int): Maximum number of anchor hits kept
            per file. Defaults to ``3``.

    Returns:
        Structured payload with ranked file candidates, match counts, and a few
        short anchor previews per file.

    Raises:
        ValueError: If arguments are invalid or path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    normalized_query = query.strip()
    if normalized_query == "":
        raise ValueError("query must not be blank.")
    if max_candidates < 1:
        raise ValueError("max_candidates must be greater than or equal to 1.")
    if max_candidates > 20:
        raise ValueError("max_candidates must be less than or equal to 20.")
    if max_hits_per_file < 1:
        raise ValueError("max_hits_per_file must be greater than or equal to 1.")
    if max_hits_per_file > 5:
        raise ValueError("max_hits_per_file must be less than or equal to 5.")

    target = workspace_path(path)
    output = exec_in_sandbox(
        [
            "python3",
            "-c",
            _SEARCH_SCRIPT,
            target,
            normalized_query,
            "1" if regex else "0",
            "1" if case_sensitive else "0",
            str(max_candidates),
            str(max_hits_per_file),
        ]
    )
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox search returned an invalid payload.")
    return payload
