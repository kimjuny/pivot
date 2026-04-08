"""Workspace service for runtime workspace records, cache paths, and code checks."""

import ast
import json
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models.workspace import Workspace
from app.services.workspace_storage_service import WorkspaceStorageService
from sqlmodel import Session as DBSession, select

# Root that contains persisted local service data.
# Resolved relative to this file: server/app/services/ -> server/
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent / "workspace"
def workspace_root() -> Path:
    """Return the root directory that stores all user workspaces."""
    _WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return _WORKSPACE_ROOT

def ensure_agent_workspace(username: str, agent_id: int) -> Path:
    """Return (and create) an agent workspace directory.

    Path format: ``server/workspace/users/{username}/agents/{agent_id}/``.
    """
    agent_dir = (
        workspace_root()
        / "users"
        / username
        / "agents"
        / str(agent_id)
    )
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir


def session_workspace_dir(username: str, agent_id: int, session_id: str) -> Path:
    """Return the directory reserved for one private session workspace."""
    path = ensure_agent_workspace(username, agent_id) / "sessions" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_workspace_dir(username: str, agent_id: int, project_id: str) -> Path:
    """Return the directory reserved for one shared project workspace."""
    path = ensure_agent_workspace(username, agent_id) / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


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
        """Create and persist one workspace record plus its storage identity.

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
        storage_service = WorkspaceStorageService()
        workspace = Workspace(
            workspace_id=str(uuid.uuid4()),
            agent_id=agent_id,
            user=username,
            scope=scope,
            session_id=session_id,
            project_id=project_id,
            status="active",
            storage_backend=storage_service.default_storage_backend(),
            logical_path=storage_service.build_logical_path(
                scope=scope,
                username=username,
                agent_id=agent_id,
                session_id=session_id,
                project_id=project_id,
            ),
            mount_mode=storage_service.default_mount_mode(),
            created_at=now,
            updated_at=now,
        )
        self.db.add(workspace)
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete one workspace record.

        Args:
            workspace_id: Public workspace identifier.

        Returns:
            ``True`` when a workspace existed and was removed.
        """
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            return False

        self.db.delete(workspace)
        self.db.commit()
        return True

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
