"""Built-in sandbox tool: batch line-range edits in workspace files."""

from __future__ import annotations

import json
from typing import Any

from app.orchestration.tool import tool

from ._sandbox_common import exec_in_sandbox, workspace_path


@tool(tool_type="sandbox")
def edit_file(path: str, patches: list[dict[str, Any]]) -> str:
    """Apply multiple line-range replacements to one file under ``/workspace``.

    The patch coordinates are intentionally defined against the **original file**
    to avoid line-number drift for LLM callers. All ranges are interpreted as:
    - 1-based line numbers
    - inclusive ``start_line`` and inclusive ``end_line``

    Each patch object must contain:
    - ``start_line`` (int)
    - ``end_line`` (int)
    - ``content`` (str, replacement text for that full range)

    Validation rules:
    - ``start_line`` >= 1
    - ``end_line`` >= ``start_line``
    - ranges must be within the original file line count
    - ranges must not overlap with each other

    Example ``patches``:
        [
          {"start_line": 10, "end_line": 12, "content": "new block A\\n"},
          {"start_line": 40, "end_line": 40, "content": "new single line\\n"}
        ]

    Args:
        path: Relative or absolute workspace path to file.
        patches: Batch line-range replacements.

    Returns:
        Human-readable edit confirmation.

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
                "import json\n"
                "import pathlib\n"
                "import sys\n"
                "p=pathlib.Path(sys.argv[1])\n"
                "raw_patches=json.loads(sys.argv[2])\n"
                "if not isinstance(raw_patches, list) or len(raw_patches) == 0:\n"
                "    raise RuntimeError('patches must be a non-empty list')\n"
                "text=p.read_text(encoding='utf-8')\n"
                "lines=text.splitlines(keepends=True)\n"
                "line_count=len(lines)\n"
                "normalized=[]\n"
                "for idx, patch in enumerate(raw_patches):\n"
                "    if not isinstance(patch, dict):\n"
                "        raise RuntimeError(f'patch[{idx}] must be an object')\n"
                "    if 'start_line' not in patch or 'end_line' not in patch or 'content' not in patch:\n"
                "        raise RuntimeError(f'patch[{idx}] requires start_line/end_line/content')\n"
                "    start_line=patch['start_line']\n"
                "    end_line=patch['end_line']\n"
                "    content=patch['content']\n"
                "    if not isinstance(start_line, int) or not isinstance(end_line, int):\n"
                "        raise RuntimeError(f'patch[{idx}] start_line/end_line must be int')\n"
                "    if not isinstance(content, str):\n"
                "        raise RuntimeError(f'patch[{idx}] content must be string')\n"
                "    if start_line < 1:\n"
                "        raise RuntimeError(f'patch[{idx}] start_line must be >= 1')\n"
                "    if end_line < start_line:\n"
                "        raise RuntimeError(f'patch[{idx}] end_line must be >= start_line')\n"
                "    if end_line > line_count:\n"
                "        raise RuntimeError(f'patch[{idx}] line range exceeds file length ({line_count})')\n"
                "    normalized.append((start_line, end_line, content, idx))\n"
                "normalized.sort(key=lambda x: x[0])\n"
                "for i in range(1, len(normalized)):\n"
                "    prev_start, prev_end, _prev_content, prev_idx = normalized[i-1]\n"
                "    cur_start, _cur_end, _cur_content, cur_idx = normalized[i]\n"
                "    if cur_start <= prev_end:\n"
                "        raise RuntimeError(f'patch[{cur_idx}] overlaps patch[{prev_idx}]')\n"
                "result=[]\n"
                "cursor=1\n"
                "for start_line, end_line, content, _idx in normalized:\n"
                "    result.extend(lines[cursor-1:start_line-1])\n"
                "    result.append(content)\n"
                "    cursor=end_line+1\n"
                "result.extend(lines[cursor-1:])\n"
                "updated=''.join(result)\n"
                "p.write_text(updated, encoding='utf-8')\n"
                "print(f'Edited {p} (patches={len(normalized)})')\n"
            ),
            target,
            json.dumps(patches, ensure_ascii=False),
        ]
    )
