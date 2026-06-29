"""Built-in tool: read a workspace file with automatic multimodal support."""

from __future__ import annotations

import json
import posixpath
from typing import TYPE_CHECKING, Annotated

from app.orchestration.tool import Param, get_current_tool_execution_context, tool

from ._sandbox_common import exec_in_sandbox, workspace_path

if TYPE_CHECKING:
    from app.orchestration.tool.manager import ToolExecutionContext

_TEXT_EXTENSIONS = frozenset(
    {
        "md",
        "markdown",
        "txt",
        "py",
        "js",
        "ts",
        "jsx",
        "tsx",
        "json",
        "yaml",
        "yml",
        "toml",
        "cfg",
        "ini",
        "sh",
        "bash",
        "zsh",
        "css",
        "html",
        "xml",
        "sql",
        "r",
        "go",
        "rs",
        "java",
        "c",
        "cpp",
        "h",
        "hpp",
        "rb",
        "php",
        "swift",
        "kt",
        "scala",
        "lua",
        "pl",
        "ex",
        "exs",
        "hs",
        "ml",
        "vim",
        "dockerfile",
        "makefile",
        "cmake",
        "gitignore",
        "env",
        "log",
        "csv",
        "tsv",
        "rst",
        "tex",
        "diff",
        "patch",
        "lock",
        "conf",
        "properties",
        "tf",
        "hcl",
        "proto",
        "graphql",
        "gql",
        "prisma",
        "sol",
        "move",
        "zig",
        "nim",
        "v",
        "sv",
        "vue",
        "svelte",
    }
)

_DOCUMENT_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "xlsx"})

_IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})

_READ_FILE_SCRIPT = """
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
start_line = int(sys.argv[2])
max_lines = int(sys.argv[3])
show_line_numbers = sys.argv[4].lower() == "true"

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
content_hash = hashlib.md5(text.encode("utf-8", errors="replace"), usedforsecurity=False).hexdigest()

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
        "content_hash": content_hash,
    }
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

if start_line > total_lines:
    raise RuntimeError(
        f"start_line {start_line} exceeds file length ({total_lines} lines)"
    )

actual_end_line = min(total_lines, start_line + max_lines - 1)
chunk_lines = lines[start_line - 1 : actual_end_line]
if show_line_numbers:
    number_width = len(str(actual_end_line))
    content = "".join(
        f"{line_number:>{number_width}} | {line}"
        for line_number, line in enumerate(chunk_lines, start=start_line)
    )
else:
    content = "".join(chunk_lines)

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
    "content": content,
    "content_hash": content_hash,
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()

_READ_IMAGE_BASE64_SCRIPT = """
from __future__ import annotations

import base64
import json
import mimetypes
import sys
from pathlib import Path

path = Path(sys.argv[1])
display_path = str(path).removeprefix("/workspace/") or "."
if not path.exists():
    print(f"File not found: {display_path}", file=sys.stderr)
    raise SystemExit(1)
if path.is_dir():
    print(f"Path is a directory, not a file: {display_path}", file=sys.stderr)
    raise SystemExit(1)

data = base64.b64encode(path.read_bytes()).decode("ascii")
mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
payload = {"data": data, "mime_type": mime_type, "size_bytes": path.stat().st_size}
print(json.dumps(payload, ensure_ascii=False))
""".strip()


def _classify_extension(path: str) -> str:
    """Return 'text', 'document', 'image', or 'unknown' based on file extension."""
    normalized = posixpath.basename(path).rsplit(".", 1)[-1].lower()
    if normalized in _TEXT_EXTENSIONS:
        return "text"
    if normalized in _DOCUMENT_EXTENSIONS:
        return "document"
    if normalized in _IMAGE_EXTENSIONS:
        return "image"
    return "unknown"


def _resolve_workspace_relative_path(abs_path: str) -> str:
    """Strip /workspace/ prefix to get the workspace-relative path."""
    if abs_path.startswith("/workspace/"):
        return abs_path[len("/workspace/") :]
    if abs_path.startswith("/workspace"):
        return abs_path[len("/workspace") :]
    return abs_path


def _require_db_session(ctx: ToolExecutionContext):
    """Return a db session from the context factory, or raise."""
    if ctx.db_session_factory is None:
        raise RuntimeError("read_file requires database access for this file type.")
    return ctx.db_session_factory()


def _read_text_in_sandbox(
    path: str,
    start_line: int,
    max_lines: int,
    show_line_numbers: bool,
) -> dict[str, object]:
    """Read a text file inside the sandbox with optional line-numbered output."""
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
                "true" if show_line_numbers else "false",
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


def _read_document(path: str) -> dict[str, object]:
    """Read a document file using just-in-time markdown conversion (cached)."""
    from app.services.file_service import FileService

    ctx = get_current_tool_execution_context()
    if ctx is None:
        raise RuntimeError("Tool execution context is missing.")
    target = workspace_path(path)
    relative_path = _resolve_workspace_relative_path(target)

    with _require_db_session(ctx) as db:
        service = FileService(db)
        file_asset = service.get_file_by_workspace_path(relative_path)
        if file_asset is None:
            raise FileNotFoundError(
                f"File not found in workspace uploads: {relative_path}"
            )
        markdown_text = service._load_document_markdown(file_asset)
        return {
            "path": relative_path,
            "kind": "document",
            "content": markdown_text,
        }


def _read_image(path: str) -> dict[str, object]:
    """Read an image file from the sandbox and return multimodal blocks."""

    from app.services.file_service import FileService

    ctx = get_current_tool_execution_context()
    if ctx is None:
        raise RuntimeError("Tool execution context is missing.")
    target = workspace_path(path)
    relative_path = _resolve_workspace_relative_path(target)

    # Read image bytes directly from the sandbox filesystem
    try:
        raw_output = exec_in_sandbox(
            ["python3", "-c", _READ_IMAGE_BASE64_SCRIPT, target]
        )
    except RuntimeError as exc:
        message = str(exc)
        not_found_prefix = "Sandbox command failed (exit=1): File not found: "
        if message.startswith(not_found_prefix):
            raise FileNotFoundError(
                f"File not found: {message.removeprefix(not_found_prefix)}"
            ) from exc
        raise

    payload = json.loads(raw_output)
    if not isinstance(payload, dict):
        raise RuntimeError("Sandbox read_image returned an invalid payload.")

    # Look up metadata from DB if available
    original_name = relative_path
    mime_type = payload.get("mime_type", "")
    dimensions = payload.get("dimensions", "unknown")

    if ctx.db_session_factory is not None:
        with ctx.db_session_factory() as db:
            service = FileService(db)
            file_asset = service.get_file_by_workspace_path(relative_path)
            if file_asset is not None:
                original_name = file_asset.original_name
                dimensions = (
                    f"{file_asset.width}x{file_asset.height}"
                    if file_asset.width and file_asset.height
                    else dimensions
                )

    encoded_data = payload["data"]
    return {
        "path": relative_path,
        "kind": "image",
        "dimensions": dimensions,
        "_pivot_multimodal_blocks": [
            {
                "type": "text",
                "text": (
                    f'Image loaded: "{original_name}"\n'
                    f"MIME type: {mime_type}\n"
                    f"Dimensions: {dimensions}"
                ),
            },
            {
                "type": "image",
                "media_type": mime_type,
                "data": encoded_data,
            },
        ],
    }


@tool(
    description=(
        "Read a file under /workspace. Auto-selects reading strategy by extension: "
        "text/code files (and any unknown extension) get raw text output by default, "
        "documents (pdf/docx/pptx/xlsx) get converted to markdown, "
        "images (png/jpg/jpeg/webp) are made visible to the model. "
        "IMPORTANT: Always prefer read_file over bash tools (cat, head, tail, etc.) "
        "for reading files. Only fall back to bash if read_file explicitly reports "
        "that the file type is not supported."
    ),
)
def read_file(
    path: Annotated[str, Param("Relative or absolute workspace path.")],
    start_line: Annotated[
        int,
        Param(
            "1-based starting line for text files. " "Ignored for documents and images."
        ),
    ] = 1,
    max_lines: Annotated[
        int,
        Param(
            "Maximum returned lines for text files. "
            "Ignored for documents and images."
        ),
    ] = 1200,
    show_line_numbers: Annotated[
        bool,
        Param(
            "Whether to include line number prefixes in text output. "
            "Default false so content can be copied directly into edit_file.old_string."
        ),
    ] = False,
) -> dict[str, object]:
    """Read a file under ``/workspace``. Automatically selects the appropriate
    reading strategy based on file extension:

    - **Text/code files** (.py, .js, .json, .yaml, .md, .csv, .txt, etc.) and
      any unknown extension: Returns raw content with pagination hints.
    - **Documents** (.pdf, .docx, .pptx, .xlsx): Returns markdown content
      extracted by a lightweight per-format parser.
    - **Images** (.png, .jpg, .jpeg, .webp): Makes the image visible to the
      model in the next iteration.

    Returns:
        Structured dict with file content and metadata.

    Raises:
        ValueError: If arguments are invalid or file type is unsupported.
        FileNotFoundError: If the file does not exist.
    """
    file_type = _classify_extension(path)

    if file_type == "text" or file_type == "unknown":
        if start_line < 1:
            raise ValueError("start_line must be greater than or equal to 1.")
        if max_lines < 1:
            raise ValueError("max_lines must be greater than or equal to 1.")
        if max_lines > 2000:
            raise ValueError("max_lines must be less than or equal to 2000.")

        result = _read_text_in_sandbox(path, start_line, max_lines, show_line_numbers)

        ctx = get_current_tool_execution_context()
        can_track = ctx is not None and ctx.session_id and ctx.db_session_factory
        if can_track:
            from app.services.file_read_tracker_service import (
                FileReadTrackerService,
            )

            content_hash = str(result.get("content_hash", ""))
            relative_path = str(result.get("path", path))
            actual_start = int(result["start_line"])  # type: ignore[arg-type]
            actual_end = int(result["end_line"])  # type: ignore[arg-type]
            total_lines = int(result["total_lines"])  # type: ignore[arg-type]

            assert ctx is not None
            assert ctx.session_id is not None
            assert ctx.db_session_factory is not None

            with ctx.db_session_factory() as db:
                FileReadTrackerService(db).record_read(
                    session_id=ctx.session_id,
                    path=relative_path,
                    content_hash=content_hash,
                    total_lines=total_lines,
                    start_line=actual_start,
                    end_line=actual_end,
                )

        return result

    if file_type == "document":
        return _read_document(path)

    if file_type == "image":
        return _read_image(path)

    raise AssertionError(f"Unhandled file type: {file_type}")
