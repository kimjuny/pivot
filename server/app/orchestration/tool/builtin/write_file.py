"""Built-in sandbox tool: write file content in agent workspace."""

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def write_file(path: str, content: str) -> str:
    """Write UTF-8 text to a file under ``/workspace``.

    Parent directories are created automatically.

    Args:
        path (required, str): Relative or absolute workspace path to file.
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
