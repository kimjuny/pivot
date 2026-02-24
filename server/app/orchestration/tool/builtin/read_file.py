"""Built-in sandbox tool: read file content from agent workspace."""

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def read_file(path: str) -> str:
    """Read UTF-8 text from a file under ``/workspace``.

    Args:
        path: Relative or absolute workspace path to file.

    Returns:
        Full file content as text.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    target = workspace_path(path)
    return exec_in_sandbox(
        [
            "python3",
            "-c",
            (
                "import pathlib,sys;"
                "print(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'), end='')"
            ),
            target,
        ]
    )
