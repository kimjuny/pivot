"""Built-in sandbox tool: replace exact text inside one workspace file."""

from __future__ import annotations

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path

_EDIT_FILE_SCRIPT = """
from __future__ import annotations

import pathlib
import sys

path = pathlib.Path(sys.argv[1])
old_string = sys.argv[2]
new_string = sys.argv[3]
expected_replacements = int(sys.argv[4])

if expected_replacements < 1:
    raise RuntimeError("expected_replacements must be >= 1")

if old_string == "":
    if path.exists():
        raise RuntimeError(
            "Cannot create file because it already exists. "
            "Provide old_string to edit an existing file."
        )
    path.write_text(new_string, encoding="utf-8")
    print(f"Created new file: {path}")
    raise SystemExit(0)

if not path.exists():
    raise RuntimeError("Cannot edit file because it does not exist.")

text = path.read_text(encoding="utf-8")
occurrences = text.count(old_string)
if occurrences != expected_replacements:
    raise RuntimeError(
        "Failed to edit: expected "
        f"{expected_replacements} occurrence(s) of old_string but found {occurrences}."
    )

updated = text.replace(old_string, new_string, expected_replacements)
path.write_text(updated, encoding="utf-8")
print(
    f"Successfully modified file: {path} "
    f"({expected_replacements} replacements)."
)
""".strip()


@tool(tool_type="sandbox")
def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    expected_replacements: int = 1,
) -> str:
    """Replace exact text inside one file under ``/workspace``.

    This tool is intentionally simple: the caller should first use ``read_file``
    to fetch the exact source text, then pass the precise ``old_string`` it wants
    to replace. Include enough surrounding context in ``old_string`` to make the
    target unique and stable.

    Behavior:
    - When ``old_string`` is non-empty, the tool requires the file to exist and
      replaces exactly ``expected_replacements`` literal occurrences.
    - When ``old_string`` is empty, the tool creates a new file with
      ``new_string`` as its content, but only if the file does not already exist.

    Args:
        path (required, str): Relative or absolute workspace path to the target
            file.
        old_string (required, str): Exact literal text to replace. Use ``""``
            only when creating a brand new file.
        new_string (required, str): Replacement text, or initial file content
            during creation.
        expected_replacements (optional, int): Exact number of literal
            occurrences expected in the current file content. Defaults to ``1``.

    Returns:
        Human-readable success message.

    Raises:
        ValueError: If path escapes ``/workspace`` or ``expected_replacements``
            is invalid.
        RuntimeError: If sandbox execution fails or the match count is wrong.
    """
    if expected_replacements < 1:
        raise ValueError("expected_replacements must be greater than or equal to 1.")

    target = workspace_path(path)
    return exec_in_sandbox(
        [
            "python3",
            "-c",
            _EDIT_FILE_SCRIPT,
            target,
            old_string,
            new_string,
            str(expected_replacements),
        ]
    )
