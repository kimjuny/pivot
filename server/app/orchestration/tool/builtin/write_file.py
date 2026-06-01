"""Built-in sandbox tool: write file content in agent workspace."""

import hashlib
from typing import Annotated

from app.orchestration.tool import (
    Param,
    get_current_tool_execution_context,
    tool,
)

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(
    description="Write UTF-8 text to a file under /workspace. Creates parent directories automatically.",
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
    """Write UTF-8 text to a file under ``/workspace``.

    IMPORTANT: Prefer an absolute sandbox path that starts with ``/workspace/``,
    for example ``/workspace/app/index.html``. Never pass host-machine paths.

    Args:
        path: Target file path.
        content: Text content to write.

    Returns:
        Dict with write confirmation and content hash.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    target = workspace_path(path)
    exec_in_sandbox(
        [
            "python3",
            "-c",
            (
                "import pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "p.parent.mkdir(parents=True, exist_ok=True);"
                "p.write_text(sys.argv[2], encoding='utf-8');"
                "print(f'Wrote {len(sys.argv[2])} bytes to {p}')"
            ),
            target,
            content,
        ]
    )

    content_hash = hashlib.md5(
        content.encode("utf-8"), usedforsecurity=False
    ).hexdigest()
    total_lines = content.count("\n") + (0 if content.endswith("\n") else 1)
    relative_path = target.removeprefix("/workspace/") or "."

    ctx = get_current_tool_execution_context()
    if ctx is not None and ctx.session_id and ctx.db_session_factory:
        from ._file_read_tracker import load_tracker, record_read, save_tracker

        tracker = load_tracker(ctx.session_id, ctx.db_session_factory) or {}
        record_read(tracker, relative_path, content_hash, total_lines, 1, total_lines)
        save_tracker(ctx.session_id, ctx.db_session_factory, tracker)

    return {
        "message": f"Wrote file: {relative_path}",
        "path": relative_path,
        "content_hash": content_hash,
        "total_lines": total_lines,
    }
