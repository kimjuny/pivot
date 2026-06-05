"""Shared helpers for sandbox built-in tools."""

from __future__ import annotations

import hashlib
import posixpath
from pathlib import Path

from app.orchestration.tool import get_current_tool_execution_context
from app.services.sandbox_service import get_sandbox_service


def require_context() -> tuple[int, int, str, str, int, tuple[dict[str, str], ...]]:
    """Read tool execution context for sandbox tools.

    Returns:
        Tuple of ``(user_id, agent_id, workspace_id, workspace_backend_path,``
        ``sandbox_timeout_seconds, allowed_skills)``.

    Raises:
        RuntimeError: If the current call is missing execution context.
    """
    ctx = get_current_tool_execution_context()
    if ctx is None:
        raise RuntimeError("Sandbox tool execution context is missing.")
    return (
        ctx.user_id,
        ctx.agent_id,
        ctx.workspace_id,
        ctx.workspace_backend_path,
        ctx.sandbox_timeout_seconds,
        ctx.allowed_skills,
    )


def workspace_path(path: str) -> str:
    """Resolve and validate a path inside ``/workspace``.

    Args:
        path: Relative or absolute path provided by tool caller.

    Returns:
        Absolute normalized path under ``/workspace``.

    Raises:
        ValueError: If path escapes ``/workspace``.
    """
    raw = (path or ".").strip()
    if raw == "":
        raw = "."

    if raw.startswith("/"):
        full = posixpath.normpath(raw)
    else:
        full = posixpath.normpath(posixpath.join("/workspace", raw))

    if full == "/workspace" or full.startswith("/workspace/"):
        return full
    raise ValueError("Path must stay within /workspace.")


def workspace_relative_path(path: str) -> str:
    """Return a normalized workspace-relative path."""
    target = workspace_path(path)
    return target.removeprefix("/workspace/") or "."


def backend_workspace_file_path(path: str) -> Path | None:
    """Resolve one workspace file path as visible to the backend process."""
    ctx = get_current_tool_execution_context()
    if ctx is None or not ctx.workspace_backend_path:
        return None

    relative_path = workspace_relative_path(path)
    if relative_path == ".":
        raise ValueError("Path must point to a file, not /workspace.")

    root = Path(ctx.workspace_backend_path).resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path must stay within workspace_backend_path.")
    return candidate


def verify_backend_visible_text_file(
    path: str,
    *,
    expected_hash: str,
    expected_total_lines: int,
) -> None:
    """Ensure a sandbox write is immediately visible from the backend workspace.

    Why: the session Files tracker is a cross-tool safety ledger. If a sandbox
    write reports success but the backend-visible workspace still has different
    content, recording the sandbox-reported hash would poison future stale-file
    checks.
    """
    if not expected_hash:
        raise RuntimeError("Cannot verify workspace write without content_hash.")

    backend_path = backend_workspace_file_path(path)
    if backend_path is None:
        return
    if not backend_path.exists():
        raise RuntimeError(
            "Sandbox write was not visible from backend workspace: "
            f"{workspace_relative_path(path)}"
        )
    if backend_path.is_dir():
        raise RuntimeError(
            "Sandbox write target is a directory from backend workspace: "
            f"{workspace_relative_path(path)}"
        )

    text = backend_path.read_text(encoding="utf-8", errors="replace")
    actual_hash = hashlib.md5(
        text.encode("utf-8", errors="replace"),
        usedforsecurity=False,
    ).hexdigest()
    actual_total_lines = 0 if text == "" else len(text.splitlines())
    if actual_hash != expected_hash or actual_total_lines != expected_total_lines:
        raise RuntimeError(
            "Sandbox write was not visible from backend workspace. "
            f"path={workspace_relative_path(path)} "
            f"expected_hash={expected_hash} actual_hash={actual_hash} "
            f"expected_total_lines={expected_total_lines} "
            f"actual_total_lines={actual_total_lines}"
        )


def exec_in_sandbox(cmd: list[str]) -> str:
    """Execute one non-interactive command in sandbox.

    Args:
        cmd: Command array (argv-style).

    Returns:
        Command stdout.

    Raises:
        RuntimeError: If command exits with non-zero code.
    """
    (
        user_id,
        _agent_id,
        workspace_id,
        workspace_backend_path,
        sandbox_timeout_seconds,
        allowed_skills,
    ) = require_context()
    result = get_sandbox_service().exec(
        user_id=user_id,
        workspace_id=workspace_id,
        workspace_backend_path=workspace_backend_path,
        cmd=cmd,
        skills=list(allowed_skills),
        timeout_seconds=sandbox_timeout_seconds,
    )
    if result.exit_code != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Sandbox command failed (exit={result.exit_code}): {message}"
        )
    return result.stdout
