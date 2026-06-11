"""Plan tool — generate a markdown plan for the user to review.

This tool is registered for catalog visibility only (so the LLM sees it in the
tool catalog). The actual execution is handled directly by ReactEngine when it
detects a tool call named ``plan``, bypassing the normal sync tool execution
path because plan operations need access to the workspace filesystem and the
engine's approval-flow machinery.
"""

from typing import Annotated, Any

from app.orchestration.tool.decorator import Param, tool


@tool(
    description=(
        "Generate a markdown plan for the user to review before execution. "
        "Pauses the task until the user approves, edits, or rejects the plan.\n"
        "\n"
        "Use when: ambiguous requirements, multiple valid approaches, or high-impact "
        "changes where getting sign-off first prevents rework.\n"
        "\n"
        "Skip when: straightforward tasks, clear implementation path, or the user "
        "gave specific detailed instructions.\n"
        "\n"
        "After approval, use the `task` tool to create execution steps based on the "
        "(possibly edited) plan."
    ),
)
def plan(
    plan_text: Annotated[
        str | None,
        Param(
            "Full plan in markdown. Include: brief context, step-by-step approach, "
            "key files to modify, and how to verify. Concise and actionable."
        ),
    ] = None,
) -> dict[str, Any]:
    """Placeholder — actual execution handled by ReactEngine."""
    return {
        "error": "Plan tool must be executed by the engine, not directly",
        "success": False,
    }
