"""Workspace service for managing workspace-backed runtime paths.

User-owned runtime files live under the unified storage namespace
``users/{username}/...``. This service provides CRUD operations over the
workspace-backed ``tools/`` sub-folder, keeping user-authored tools as plain ``.py``
source files on disk.

The service intentionally works with raw source code strings so that:
1. The frontend can display and edit the full file contents in an editor.
2. The backend can pass the code to static-analysis tools (AST / ruff / pyright)
   without an extra round-trip.
"""

import ast
import importlib.util
import inspect
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models.workspace import Workspace
from app.orchestration.tool.metadata import ToolMetadata
from app.storage import get_resolved_storage_profile
from app.utils.logging_config import get_logger
from sqlmodel import Session as DBSession, select

logger = get_logger("workspace_service")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def workspace_root() -> Path:
    """Return the root directory that stores all user workspaces."""
    root = get_resolved_storage_profile().posix_workspace.local_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def backend_workspace_root() -> str:
    """Return the workspace root path visible inside the backend container."""
    root = get_resolved_storage_profile().posix_workspace.local_root()
    return str(root).rstrip("/") or "/"


def _user_tools_dir(username: str) -> Path:
    """Return (and create if needed) the tools directory for a user.

    Args:
        username: The authenticated username.

    Returns:
        Absolute path to ``users/{username}/tools/`` under the active POSIX root.
    """
    tools_dir = workspace_root() / "users" / username / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def _validate_tool_name(tool_name: str) -> None:
    """Reject names that cannot be both a .py stem and Python function name."""
    if not _TOOL_NAME_PATTERN.fullmatch(tool_name):
        raise ValueError(
            "Tool name must be a Python identifier using letters, numbers, "
            "and underscores, and cannot start with a number."
        )


def _validate_tool_source_name(tool_name: str, source: str) -> None:
    """Require the tool source to define the function named by the file stem."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Tool source has invalid Python syntax: {exc.msg}") from exc
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == tool_name:
            return
    raise ValueError(f"Tool source must define function '{tool_name}'.")


def ensure_agent_workspace(username: str, agent_id: int) -> Path:
    """Return (and create) an agent workspace directory.

    Path format: ``users/{username}/agents/{agent_id}/``.
    """
    agent_dir = workspace_root() / "users" / username / "agents" / str(agent_id)
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir


def session_workspace_logical_root(
    username: str,
    agent_id: int,
    session_id: str,
) -> str:
    """Return the logical root for one private session workspace."""
    return f"users/{username}/agents/{agent_id}/sessions/{session_id}/workspace"


def project_workspace_logical_root(
    username: str,
    agent_id: int,
    project_id: str,
) -> str:
    """Return the logical root for one shared project workspace."""
    return f"users/{username}/agents/{agent_id}/projects/{project_id}/workspace"


def session_workspace_dir(username: str, agent_id: int, session_id: str) -> Path:
    """Return the directory reserved for one private session workspace."""
    handle = get_resolved_storage_profile().posix_workspace.ensure_workspace(
        session_workspace_logical_root(username, agent_id, session_id)
    )
    return handle.host_path


def project_workspace_dir(username: str, agent_id: int, project_id: str) -> Path:
    """Return the directory reserved for one shared project workspace."""
    handle = get_resolved_storage_profile().posix_workspace.ensure_workspace(
        project_workspace_logical_root(username, agent_id, project_id)
    )
    return handle.host_path


class WorkspaceService:
    """CRUD-style service for runtime workspace records and paths."""

    def __init__(self, db: DBSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Active database session.
        """
        self.db = db

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Return one workspace by public identifier."""
        statement = select(Workspace).where(Workspace.workspace_id == workspace_id)
        return self.db.exec(statement).first()

    def create_workspace(
        self,
        *,
        agent_id: int,
        username: str,
        scope: str,
        session_id: str | None = None,
        project_id: str | None = None,
    ) -> Workspace:
        """Create and persist one workspace record plus its directory.

        Args:
            agent_id: Owning agent identifier.
            username: Workspace owner.
            scope: Workspace scope string.
            session_id: Optional bound private session UUID.
            project_id: Optional bound shared project UUID.

        Returns:
            Persisted workspace row.

        Raises:
            ValueError: If the requested scope/ownership combination is invalid.
        """
        if scope == "session_private":
            if session_id is None or project_id is not None:
                raise ValueError("session_private workspaces require session_id only.")
        elif scope == "project_shared":
            if project_id is None or session_id is not None:
                raise ValueError("project_shared workspaces require project_id only.")
        else:
            raise ValueError(f"Unsupported workspace scope '{scope}'.")

        now = datetime.now(UTC)
        workspace = Workspace(
            workspace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            user=username,
            scope=scope,
            session_id=session_id,
            project_id=project_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.db.add(workspace)
        self.db.commit()
        self.db.refresh(workspace)
        self.get_workspace_path(workspace)
        return workspace

    def get_workspace_path(self, workspace: Workspace) -> Path:
        """Resolve and create the host-side directory for one workspace.

        Args:
            workspace: Workspace row to resolve.

        Returns:
            Absolute host-side path.

        Raises:
            ValueError: If the row is missing the scope-specific identifier.
        """
        if workspace.scope == "session_private":
            if workspace.session_id is None:
                raise ValueError("Workspace row is missing session_id.")
            return session_workspace_dir(
                workspace.user,
                workspace.agent_id,
                workspace.session_id,
            )
        if workspace.scope == "project_shared":
            if workspace.project_id is None:
                raise ValueError("Workspace row is missing project_id.")
            return project_workspace_dir(
                workspace.user,
                workspace.agent_id,
                workspace.project_id,
            )
        raise ValueError(f"Unsupported workspace scope '{workspace.scope}'.")

    def get_workspace_logical_root(self, workspace: Workspace) -> str:
        """Return the logical storage root for one workspace row."""
        if workspace.scope == "session_private":
            if workspace.session_id is None:
                raise ValueError("Workspace row is missing session_id.")
            return session_workspace_logical_root(
                workspace.user,
                workspace.agent_id,
                workspace.session_id,
            )
        if workspace.scope == "project_shared":
            if workspace.project_id is None:
                raise ValueError("Workspace row is missing project_id.")
            return project_workspace_logical_root(
                workspace.user,
                workspace.agent_id,
                workspace.project_id,
            )
        raise ValueError(f"Unsupported workspace scope '{workspace.scope}'.")

    def get_workspace_backend_path(self, workspace: Workspace) -> str:
        """Return the path visible inside the backend container for one workspace."""
        backend_root = backend_workspace_root()
        logical_root = self.get_workspace_logical_root(workspace)
        return f"{backend_root}/{logical_root}"

    def get_workspace_uploads_path(self, workspace: Workspace) -> Path:
        """Return the runtime `.uploads` directory for one workspace.

        Why: upload and assistant-generated file references should always stay
        under the active workspace root so both local and external POSIX
        providers expose the same runtime layout.
        """
        uploads_dir = self.get_workspace_path(workspace) / ".uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        return uploads_dir

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete one workspace record and its host-side directory.

        Args:
            workspace_id: Public workspace identifier.

        Returns:
            ``True`` when a workspace existed and was removed.
        """
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            return False

        get_resolved_storage_profile().posix_workspace.delete_workspace(
            self.get_workspace_logical_root(workspace)
        )
        self.db.delete(workspace)
        self.db.commit()
        return True


# ---------------------------------------------------------------------------
# Source-file CRUD
# ---------------------------------------------------------------------------


def list_user_tools(username: str) -> list[dict[str, str]]:
    """List all tool source files owned by a user.

    Args:
        username: The authenticated username.

    Returns:
        List of dicts with ``name`` (stem), ``filename``, and ``tool_type`` keys.
    """
    tools_dir = _user_tools_dir(username)
    tools: list[dict[str, str]] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        metadata = load_user_tool_metadata(username, py_file.stem)
        tools.append(
            {
                "name": py_file.stem,
                "filename": py_file.name,
                "tool_type": metadata.tool_type if metadata is not None else "normal",
            }
        )
    return tools


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
    _validate_tool_name(tool_name)
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
    _validate_tool_name(tool_name)
    _validate_tool_source_name(tool_name, source)
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
    _validate_tool_name(tool_name)
    tool_path = _user_tools_dir(username) / f"{tool_name}.py"
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool '{tool_name}' not found for user '{username}'.")
    tool_path.unlink()
    logger.info("Deleted tool '%s' for user '%s'", tool_name, username)


# ---------------------------------------------------------------------------
# Dynamic metadata loading (for listing tools with metadata)
# ---------------------------------------------------------------------------


def load_all_user_tool_metadata(username: str) -> list[ToolMetadata]:
    """Load ToolMetadata for every user-authored tool file belonging to a user.

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
    _validate_tool_name(tool_name)
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
    except Exception as exc:
        logger.warning("Failed to load tool module '%s': %s", tool_name, exc)
        return None

    from app.orchestration.tool.metadata import ToolMetadata

    for _name, obj in inspect.getmembers(module, inspect.isfunction):
        metadata = getattr(obj, "__tool_metadata__", None)
        if metadata is not None and isinstance(metadata, ToolMetadata):
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
    except (
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        KeyError,
        FileNotFoundError,
    ):
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
    except (
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        KeyError,
        FileNotFoundError,
    ):
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        return []
