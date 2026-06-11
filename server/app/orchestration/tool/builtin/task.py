"""Task tool — create or update structured execution steps.

This tool is registered for catalog visibility only (so the LLM sees it in the
tool catalog). The actual execution is handled directly by ReactEngine when it
detects a tool call named ``task``, bypassing the normal sync tool execution
path because step operations need access to the workspace filesystem.
"""

from typing import Annotated, Any, Literal

from app.orchestration.tool.decorator import Param, tool


@tool(
    description=(
        "Create or update structured execution steps to track progress.\n"
        "\n"
        "Create: batch-create steps after plan approval, or directly for clear "
        "multi-step tasks (3+ steps). Assign step_id in execution order.\n"
        "\n"
        "Update: batch-update only the steps whose status changed this iteration.\n"
        "\n"
        "Skip when: single straightforward task, or trivial 1-2 step work."
    ),
)
def task(
    action: Annotated[
        Literal["create", "update"],
        Param("create = new steps, update = change existing step statuses"),
    ],
    steps: Annotated[
        list[dict[str, str]],
        Param(
            "create mode: [{step_id, subject, description, status?}]. "
            "update mode: [{step_id, status}]. "
            "Valid statuses: pending, in_progress, completed, error. "
            "Defaults to pending if status is omitted in create mode."
        ),
    ],
) -> dict[str, Any]:
    """Placeholder — actual execution handled by ReactEngine."""
    return {
        "error": "Task tool must be executed by the engine, not directly",
        "success": False,
    }
