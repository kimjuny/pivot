"""Built-in sandbox tool: list files in agent workspace."""

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def list_files(path: str = ".", recursive: bool = True) -> str:
    """List files under ``/workspace``.

    Args:
        path: Relative or absolute directory path under workspace.
        recursive: Whether to recursively include descendants.

    Returns:
        Newline-separated absolute paths.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    target = workspace_path(path)
    recursive_flag = "1" if recursive else "0"
    return exec_in_sandbox(
        [
            "python3",
            "-c",
            (
                "import pathlib,sys;"
                "root=pathlib.Path(sys.argv[1]);"
                "recursive=sys.argv[2]=='1';"
                "items=(root.rglob('*') if recursive else root.glob('*'));"
                "print('\\n'.join(str(p) for p in sorted(items)))"
            ),
            target,
            recursive_flag,
        ]
    )
