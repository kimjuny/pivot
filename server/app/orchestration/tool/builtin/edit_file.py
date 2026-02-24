"""Built-in sandbox tool: replace text in workspace file."""

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def edit_file(
    path: str, old_text: str, new_text: str, replace_all: bool = False
) -> str:
    """Replace text in a file under ``/workspace``.

    Args:
        path: Relative or absolute workspace path to file.
        old_text: Existing text fragment to replace.
        new_text: New text fragment.
        replace_all: Replace all matches when true; otherwise first match only.

    Returns:
        Human-readable edit confirmation.

    Raises:
        ValueError: If path escapes ``/workspace``.
        RuntimeError: If sandbox execution fails.
    """
    target = workspace_path(path)
    mode = "all" if replace_all else "first"
    return exec_in_sandbox(
        [
            "python3",
            "-c",
            (
                "import pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "old=sys.argv[2];new=sys.argv[3];mode=sys.argv[4];"
                "text=p.read_text(encoding='utf-8');"
                "count=text.count(old);"
                "if count==0: raise RuntimeError('old_text not found');"
                "updated=text.replace(old,new) if mode=='all' else text.replace(old,new,1);"
                "p.write_text(updated,encoding='utf-8');"
                "print(f'Edited {p} (replacements={count if mode==\"all\" else 1})')"
            ),
            target,
            old_text,
            new_text,
            mode,
        ]
    )
