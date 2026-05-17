"""Built-in tool for staging sandbox-authored skill changes for approval."""

from __future__ import annotations

from typing import Annotated

from app.orchestration.tool import Param, get_current_tool_execution_context, tool
from app.services.skill_change_service import submit_skill_change_for_agent


@tool(
    description="Stage one skill change authored inside the sandbox for user approval.",
)
def submit_skill_change(
    skill_path: Annotated[
        str, Param("Sandbox-local skill directory under /workspace/skills.")
    ] = "",
    message: Annotated[
        str, Param("Reviewer-facing explanation of what changed and why.")
    ] = "",
) -> dict[str, object]:
    """Stage one skill change authored inside ``/workspace/skills``.

    Workflow: create/edit skill directory → call this tool → system freezes
    snapshot → user approves/rejects → task resumes automatically.

    Args:
        skill_path: Sandbox-local skill directory under /workspace/skills.
        message: Reviewer-facing explanation of what changed and why.

    Returns:
        Structured submission result including a system-owned pending approval action.

    Raises:
        RuntimeError: If the tool execution context is unavailable.
        ValueError: If the draft path is invalid or the user cannot submit it.
    """
    context = get_current_tool_execution_context()
    if context is None:
        raise RuntimeError("Tool execution context is missing.")

    return submit_skill_change_for_agent(
        user_id=context.user_id,
        agent_id=context.agent_id,
        workspace_id=context.workspace_id,
        workspace_backend_path=context.workspace_backend_path,
        skill_path=skill_path,
        message=message,
    )
