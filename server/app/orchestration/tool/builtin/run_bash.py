"""Built-in sandbox tool: run one shell command in workspace."""

from typing import Any

from app.orchestration.tool import tool
from app.services.sandbox_service import get_sandbox_service

from ._sandbox_common import require_context


@tool(tool_type="sandbox")
def run_bash(command: str, fail_on_nonzero: bool = False) -> dict[str, Any]:
    """Run one bash command from ``/workspace`` and return stdout.

    Args:
        command: Shell command string executed with ``bash -lc``.
        fail_on_nonzero: When true, raise RuntimeError on non-zero exit code.
            Default false keeps recursion robust by returning structured result.

    Returns:
        Structured result dict with ``ok``, ``exit_code``, ``stdout``, ``stderr``.

    Raises:
        RuntimeError: If ``fail_on_nonzero`` is true and command fails.
    """
    username, agent_id, allowed_skills = require_context()
    result = get_sandbox_service().exec(
        username=username,
        agent_id=agent_id,
        cmd=["bash", "-lc", command],
        skills=list(allowed_skills),
    )
    if result.exit_code != 0 and fail_on_nonzero:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"Command failed (exit={result.exit_code}): {message}")
    return {
        "ok": result.exit_code == 0,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
