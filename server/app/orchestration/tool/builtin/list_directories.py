"""Built-in sandbox tool: list direct children in agent workspace."""

import json

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def list_directories(
    dir_path: str = ".",
    ignore: list[str] | None = None,
) -> str:
    """List direct files and subdirectories under one workspace directory.

    Args:
        dir_path(string, required): Relative or absolute directory path under workspace.
        ignore(array, optional): Optional glob patterns used to exclude direct children.

    Returns:
        Newline-separated child names. Directory names end with ``/``.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    target = workspace_path(dir_path)
    patterns = ignore or []
    return exec_in_sandbox(
        [
            "python3",
            "-c",
            (
                "import fnmatch,json,pathlib,sys;"
                "root=pathlib.Path(sys.argv[1]);"
                "patterns=json.loads(sys.argv[2]);"
                "if not root.is_dir():"
                " raise NotADirectoryError(f'{root} is not a directory');"
                "def ignored(path):"
                " rel=path.relative_to(root).as_posix();"
                " return any("
                "  fnmatch.fnmatch(path.name, pattern)"
                "  or fnmatch.fnmatch(rel, pattern)"
                "  for pattern in patterns"
                " );"
                "items=["
                " path for path in sorted(root.iterdir(), key=lambda item: item.name)"
                " if not ignored(path)"
                "];"
                "print('\\n'.join("
                " f'{path.name}/' if path.is_dir() else path.name"
                " for path in items"
                "))"
            ),
            target,
            json.dumps(patterns, ensure_ascii=False),
        ]
    )
