"""Built-in sandbox tool: write file content in agent workspace."""

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def write_file(path: str, content: str) -> str:
    """Write UTF-8 text to a file under ``/workspace``.

    Parent directories are created automatically.
    IMPORTANT: Prefer an absolute sandbox path that starts with ``/workspace/``,
    for example ``/workspace/app/index.html``. Never pass host-machine paths
    such as ``/Users/...`` or ``/tmp/...``; paths outside ``/workspace`` are
    rejected.

    Args:
        path (required, str): Absolute ``/workspace/...`` path to the target
            file. Workspace-relative paths are accepted, but absolute sandbox
            paths are clearer and less error-prone.
        content (required, str): UTF-8 text content to write. This tool expects
            a string, not a JSON object or other structured value.

    Returns:
        Human-readable write confirmation.

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
    return f"Wrote file: {target}"
