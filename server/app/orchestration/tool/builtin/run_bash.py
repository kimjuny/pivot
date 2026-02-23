"""
run_bash — execute a bash command inside the workspace sandbox.

The command runs in a subprocess with the workspace root as the working
directory.  stdout / stderr are captured and returned as strings.

Security notes
--------------
- The command inherits a *clean* environment (only a minimal set of vars is
  forwarded) to avoid leaking host secrets into the sidecar.
- A hard timeout prevents runaway commands from blocking the agent loop.
- Shell expansion is intentional — the command is passed to ``bash -c``
  so the agent can use pipes, redirects, etc.  The sidecar container
  provides the isolation boundary; this tool should only be enabled for
  agents that are trusted to run arbitrary commands.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from app.orchestration.tool import tool
from app.orchestration.tool.builtin._workspace import resolve_path

# Default wall-clock timeout in seconds
_DEFAULT_TIMEOUT = 30


@tool(
    name="run_bash",
    description=(
        "Execute a bash command inside the agent's workspace sandbox and return "
        "the stdout, stderr, and exit code. "
        "The command runs with the workspace root as the working directory. "
        "Supports pipes, redirects, and multi-statement commands."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command (or script snippet) to execute.",
            },
            "workdir": {
                "type": "string",
                "description": (
                    "Working directory for the command, relative to the workspace root. "
                    "Defaults to the workspace root."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": (
                    f"Maximum execution time in seconds.  Defaults to {_DEFAULT_TIMEOUT}."
                ),
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    },
)
def run_bash(
    command: str,
    workdir: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Execute a bash command inside the workspace sandbox.

    Args:
        command: Bash command string to execute.
        workdir: Working directory relative to the workspace root.
                 Defaults to the workspace root.
        timeout: Wall-clock timeout in seconds.  Defaults to 30.

    Returns:
        A dict with ``stdout``, ``stderr``, ``exit_code``, and
        ``timed_out`` (bool).
    """
    try:
        cwd = resolve_path(workdir)
    except ValueError as exc:
        return {"error": str(exc)}

    if not cwd.exists():
        return {"error": f"Working directory '{workdir}' does not exist."}
    if not cwd.is_dir():
        return {"error": f"'{workdir}' is a file, not a directory."}

    # Build a minimal, safe environment for the subprocess.
    # Always forward PATH and the workspace dir so scripts can call standard
    # utilities and reference the workspace root.
    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
        "HOME": os.environ.get("HOME", "/root"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PIVOT_WORKSPACE_DIR": os.environ.get("PIVOT_WORKSPACE_DIR", str(cwd)),
    }

    timed_out = False
    try:
        proc = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=safe_env,
            timeout=timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        exit_code = -1

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
