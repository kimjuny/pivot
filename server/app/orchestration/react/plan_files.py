"""File-based plan storage for ReAct tasks.

Plans live as two co-located files in the workspace:
  - {workspace}/.pivot/plans/{task_id}.md   — free-form Markdown (agent context)
  - {workspace}/.pivot/plans/{task_id}.json  — structured step tracking (UI + SSE)

The JSON file is the authoritative source for step status.  The Markdown file
is pure free-form text with zero format requirements.

The ``plan`` tool writes the ``.md`` file; the ``task`` tool writes/updates the
``.json`` file.  The two are fully independent.
"""

from __future__ import annotations

import json
from pathlib import Path

_ALLOWED_STEP_STATUSES = {"pending", "in_progress", "completed", "error"}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _plan_dir(workspace: str | Path) -> Path:
    """Return the ``.pivot/plans`` directory inside *workspace*."""
    return Path(workspace) / ".pivot" / "plans"


def _md_path(workspace: str | Path, task_id: str) -> Path:
    return _plan_dir(workspace) / f"{task_id}.md"


def _json_path(workspace: str | Path, task_id: str) -> Path:
    return _plan_dir(workspace) / f"{task_id}.json"


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def plan_exists(workspace: str | Path, task_id: str) -> bool:
    """Return True when a plan JSON file exists for *task_id*."""
    return _json_path(workspace, task_id).is_file()


def read_plan_text(workspace: str | Path, task_id: str) -> str:
    """Read the Markdown plan content.  Returns empty string if missing."""
    p = _md_path(workspace, task_id)
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def read_steps(workspace: str | Path, task_id: str) -> list[dict[str, str]]:
    """Read the structured steps from the JSON sidecar.

    Returns an empty list when no plan exists.
    """
    p = _json_path(workspace, task_id)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("steps", [])


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


def write_plan_text(
    workspace: str | Path,
    task_id: str,
    plan_text: str,
) -> None:
    """Create or replace the Markdown plan file."""
    dir_path = _plan_dir(workspace)
    dir_path.mkdir(parents=True, exist_ok=True)
    _md_path(workspace, task_id).write_text(plan_text, encoding="utf-8")


def write_steps(
    workspace: str | Path,
    task_id: str,
    steps: list[dict[str, str]],
) -> None:
    """Create or replace the structured steps JSON file.

    All *steps* entries receive ``status: pending`` if the key is absent.
    """
    dir_path = _plan_dir(workspace)
    dir_path.mkdir(parents=True, exist_ok=True)

    normalised: list[dict[str, str]] = []
    for s in steps:
        normalised.append(
            {
                "step_id": str(s.get("step_id", "")),
                "subject": str(s.get("subject", "")),
                "description": str(s.get("description", "")),
                "status": str(s.get("status", "pending")),
            }
        )

    _json_path(workspace, task_id).write_text(
        json.dumps({"steps": normalised}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def update_steps(
    workspace: str | Path,
    task_id: str,
    updates: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Apply incremental status *updates* and return the new step list.

    Raises ``ValueError`` when a ``step_id`` is not found in the current plan.
    """
    steps = read_steps(workspace, task_id)
    if not steps:
        raise ValueError(f"No plan found for task {task_id}")

    index = {s["step_id"]: i for i, s in enumerate(steps)}
    for u in updates:
        sid = str(u["step_id"])
        new_status = str(u["status"])
        if new_status not in _ALLOWED_STEP_STATUSES:
            raise ValueError(
                f"Invalid status '{new_status}'. Allowed: {sorted(_ALLOWED_STEP_STATUSES)}"
            )
        if sid not in index:
            raise ValueError(f"step_id '{sid}' not found in current plan")
        steps[index[sid]]["status"] = new_status

    _json_path(workspace, task_id).write_text(
        json.dumps({"steps": steps}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return steps


# ---------------------------------------------------------------------------
# Formatting helpers (used by runtime_payload)
# ---------------------------------------------------------------------------


def format_plan_status_line(steps: list[dict[str, str]]) -> str:
    """Build a one-line status summary like ``'Step 1,2 completed, Step 3 in_progress'``."""
    if not steps:
        return ""
    parts: list[str] = []
    completed_ids: list[str] = []
    in_progress_ids: list[str] = []
    pending_ids: list[str] = []
    error_ids: list[str] = []

    for s in steps:
        sid = s["step_id"]
        status = s["status"]
        if status == "completed":
            completed_ids.append(sid)
        elif status == "in_progress":
            in_progress_ids.append(sid)
        elif status == "error":
            error_ids.append(sid)
        else:
            pending_ids.append(sid)

    if completed_ids:
        parts.append(f"Step {','.join(completed_ids)} completed")
    if in_progress_ids:
        parts.append(f"Step {','.join(in_progress_ids)} in_progress")
    if error_ids:
        parts.append(f"Step {','.join(error_ids)} error")
    if pending_ids:
        parts.append(f"Step {','.join(pending_ids)} pending")
    return ", ".join(parts)


def format_plan_full(steps: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return the step list as-is for full payload injection after compaction."""
    return steps
