"""Shared helpers for sandbox built-in tools."""

from __future__ import annotations

import posixpath

from app.orchestration.tool import get_current_tool_execution_context
from app.services.sandbox_service import get_sandbox_service


def require_context() -> tuple[str, int]:
    """Read tool execution context for sandbox tools.

    Returns:
        Tuple of ``(username, agent_id)``.

    Raises:
        RuntimeError: If the current call is missing execution context.
    """
    ctx = get_current_tool_execution_context()
    if ctx is None:
        raise RuntimeError("Sandbox tool execution context is missing.")
    return ctx.username, ctx.agent_id


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


def exec_in_sandbox(cmd: list[str]) -> str:
    """Execute one non-interactive command in sandbox.

    Args:
        cmd: Command array (argv-style).

    Returns:
        Command stdout.

    Raises:
        RuntimeError: If command exits with non-zero code.
    """
    username, agent_id = require_context()
    result = get_sandbox_service().exec(username=username, agent_id=agent_id, cmd=cmd)
    if result.exit_code != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"Sandbox command failed (exit={result.exit_code}): {message}"
        )
    return result.stdout
