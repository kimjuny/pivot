"""Workspace service for managing per-user private tool files.

Each user has an isolated workspace directory under ``server/workspace/{username}/``.
This service provides CRUD operations over the ``tools/`` sub-folder of that
workspace, keeping private tools as plain ``.py`` source files on disk.

The service intentionally works with raw source code strings so that:
1. The frontend can display and edit the full file contents in an editor.
2. The backend can pass the code to static-analysis tools (AST / ruff / pyright)
   without an extra round-trip.
"""

import ast
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.orchestration.tool.metadata import ToolMetadata
from app.utils.logging_config import get_logger

logger = get_logger("workspace_service")

# Root that contains per-user subdirectories.
# Resolved relative to this file: server/app/services/ -> server/
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent / "workspace"


def _user_tools_dir(username: str) -> Path:
    """Return (and create if needed) the tools directory for a user.

    Args:
        username: The authenticated username.

    Returns:
        Absolute path to ``server/workspace/{username}/tools/``.
    """
    tools_dir = _WORKSPACE_ROOT / username / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


# ---------------------------------------------------------------------------
# Source-file CRUD
# ---------------------------------------------------------------------------


def list_user_tools(username: str) -> list[dict[str, str]]:
    """List all tool source files owned by a user.

    Args:
        username: The authenticated username.

    Returns:
        List of dicts with ``name`` (stem) and ``filename`` keys.
    """
    tools_dir = _user_tools_dir(username)
    return [
        {"name": f.stem, "filename": f.name}
        for f in sorted(tools_dir.glob("*.py"))
        if not f.name.startswith("_")
    ]


def read_user_tool(username: str, tool_name: str) -> str:
    """Read the source code of a user's tool file.

    Args:
        username: The authenticated username.
        tool_name: Stem of the tool file (without ``.py``).

    Returns:
        Source code string.

    Raises:
        FileNotFoundError: If the tool file does not exist.
    """
    tool_path = _user_tools_dir(username) / f"{tool_name}.py"
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool '{tool_name}' not found for user '{username}'.")
    return tool_path.read_text(encoding="utf-8")


def write_user_tool(username: str, tool_name: str, source: str) -> None:
    """Create or overwrite a user's tool file.

    Args:
        username: The authenticated username.
        tool_name: Stem of the tool file (without ``.py``).
        source: Python source code to write.
    """
    tool_path = _user_tools_dir(username) / f"{tool_name}.py"
    tool_path.write_text(source, encoding="utf-8")
    logger.info("Wrote tool '%s' for user '%s'", tool_name, username)


def delete_user_tool(username: str, tool_name: str) -> None:
    """Delete a user's tool file.

    Args:
        username: The authenticated username.
        tool_name: Stem of the tool file (without ``.py``).

    Raises:
        FileNotFoundError: If the tool file does not exist.
    """
    tool_path = _user_tools_dir(username) / f"{tool_name}.py"
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool '{tool_name}' not found for user '{username}'.")
    tool_path.unlink()
    logger.info("Deleted tool '%s' for user '%s'", tool_name, username)


# ---------------------------------------------------------------------------
# Dynamic metadata loading (for listing tools with metadata)
# ---------------------------------------------------------------------------


def load_all_user_tool_metadata(username: str) -> list[ToolMetadata]:
    """Load ToolMetadata for every private tool file belonging to a user.

    Args:
        username: The authenticated username.

    Returns:
        List of ToolMetadata instances for all valid decorated tool functions.
        Files that fail to load or contain no ``@tool`` function are silently skipped.
    """
    tools_dir = _user_tools_dir(username)
    results: list[ToolMetadata] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        metadata = load_user_tool_metadata(username, py_file.stem)
        if metadata is not None:
            results.append(metadata)
    return results


def load_user_tool_metadata(username: str, tool_name: str) -> ToolMetadata | None:
    """Dynamically import a user tool file and extract its ToolMetadata.

    Uses a fresh ``importlib`` spec load so that re-saves are reflected
    without a server restart.

    Args:
        username: The authenticated username.
        tool_name: Stem of the tool file (without ``.py``).

    Returns:
        ToolMetadata if a decorated function is found, None otherwise.
    """
    tool_path = _user_tools_dir(username) / f"{tool_name}.py"
    if not tool_path.exists():
        return None

    # Use a unique module name to avoid collisions in sys.modules
    module_key = f"_pivot_workspace_{username}_{tool_name}"
    spec = importlib.util.spec_from_file_location(module_key, tool_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load tool module '%s': %s", tool_name, exc)
        return None

    from app.orchestration.tool.metadata import ToolMetadata as _TM  # noqa: PLC0415

    for _name, obj in inspect.getmembers(module, inspect.isfunction):
        metadata = getattr(obj, "__tool_metadata__", None)
        if metadata is not None and isinstance(metadata, _TM):
            return metadata

    return None


# ---------------------------------------------------------------------------
# Code analysis helpers (AST / ruff / pyright)
# ---------------------------------------------------------------------------


def check_ast(source: str) -> list[dict[str, Any]]:
    """Parse Python source with the built-in ``ast`` module.

    Args:
        source: Python source code string.

    Returns:
        List of error dicts with ``line``, ``col``, and ``message`` keys.
        Empty list if the source is valid.
    """
    try:
        ast.parse(source)
        return []
    except SyntaxError as exc:
        return [
            {
                "line": exc.lineno or 1,
                "col": exc.offset or 1,
                "message": str(exc.msg),
                "source": "ast",
            }
        ]


def check_ruff(source: str) -> list[dict[str, Any]]:
    """Lint Python source using ``ruff`` with the project's configuration.

    Writes the source to a temporary stdin pipe so no temp files are created.

    Args:
        source: Python source code string.

    Returns:
        List of diagnostic dicts compatible with Monaco editor markers.
        Each dict has ``line``, ``col``, ``endLine``, ``endCol``,
        ``message``, and ``severity`` keys.
    """
    # Resolve pyproject.toml from the repo root (two levels above server/)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        result = subprocess.run(
            [
                "ruff",
                "check",
                "--stdin-filename",
                "tool.py",
                "--output-format",
                "json",
                "--config",
                str(repo_root / "pyproject.toml"),
                "-",
            ],
            input=source,
            capture_output=True,
            text=True,
            timeout=15,
        )
        diagnostics: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        return [
            {
                "line": d["location"]["row"],
                "col": d["location"]["column"],
                "endLine": d["end_location"]["row"],
                "endCol": d["end_location"]["column"],
                "message": f"[{d['code']}] {d['message']}",
                "severity": "warning",
                "source": "ruff",
            }
            for d in diagnostics
        ]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, FileNotFoundError):
        return []


def check_pyright(source: str) -> list[dict[str, Any]]:
    """Type-check Python source using ``pyright`` with the project's configuration.

    Writes source to a temporary file because pyright does not support stdin.

    Args:
        source: Python source code string.

    Returns:
        List of diagnostic dicts compatible with Monaco editor markers.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py",
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=repo_root,
        ) as tmp:
            tmp.write(source)
            tmp_path = Path(tmp.name)

        result = subprocess.run(
            [
                "pyright",
                "--outputjson",
                "--project",
                str(repo_root / "pyproject.toml"),
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(repo_root),
        )
        tmp_path.unlink(missing_ok=True)
        tmp_path = None

        payload = json.loads(result.stdout or "{}")
        diagnostics = payload.get("generalDiagnostics", [])
        return [
            {
                "line": d["range"]["start"]["line"] + 1,
                "col": d["range"]["start"]["character"] + 1,
                "endLine": d["range"]["end"]["line"] + 1,
                "endCol": d["range"]["end"]["character"] + 1,
                "message": d.get("message", ""),
                "severity": d.get("severity", "error"),
                "source": "pyright",
            }
            for d in diagnostics
        ]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, FileNotFoundError):
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return []
