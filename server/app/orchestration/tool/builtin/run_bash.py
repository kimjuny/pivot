"""Built-in sandbox tool: run one shell command in workspace."""

from typing import Annotated, Any

from app.orchestration.tool import Param, tool
from app.services.sandbox_service import get_sandbox_service

from ._sandbox_common import require_context


@tool(
    description="Run one bash command from /workspace and return stdout.",
    tool_type="sandbox",
)
def run_bash(
    command: Annotated[str, Param("Shell command string executed with bash -lc.")],
    fail_on_nonzero: Annotated[
        bool, Param("Raise RuntimeError on non-zero exit code.")
    ] = False,
) -> dict[str, Any]:
    """Run one bash command from ``/workspace`` and return stdout.

    Args:
        command: Shell command string.
        fail_on_nonzero: When true, raise on non-zero exit.

    Returns:
        Structured result dict with ok, exit_code, stdout, stderr.

    Raises:
        RuntimeError: If ``fail_on_nonzero`` is true and command fails.
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
        cmd=["bash", "-lc", command],
        skills=list(allowed_skills),
        timeout_seconds=sandbox_timeout_seconds,
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
