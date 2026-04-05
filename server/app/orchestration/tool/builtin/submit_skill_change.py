"""Built-in tool for staging sandbox-authored skill changes for approval."""

from __future__ import annotations

from app.orchestration.tool import get_current_tool_execution_context, tool
from app.services.skill_change_service import submit_skill_change_for_agent


@tool
def submit_skill_change(
    skill_path: str = "",
    message: str = "",
) -> dict[str, object]:
    """Stage one skill change authored inside the sandbox.

    Use this tool for any skill work written under ``/workspace/skills``.

    **Important:** This tool is to submit skill files change only, other files are not allowed to submit.

    Workflow:
    1. Create or edit one skill directory inside ``/workspace/skills/<name>``.
    2. When the draft is ready for review, call this tool with ``skill_path`` set to
       that top-level directory.
    3. The system will freeze a snapshot, ask the user to approve or reject it, and
       resume the task automatically after the user decides.

    Notes:
        - V1 only syncs to creator-owned private skills.
        - Built-in, foreign-owned, and shared skill targets are rejected.

    Args:
        skill_path: Sandbox-local skill directory under ``/workspace/skills``.
        message: Optional reviewer-facing explanation of what changed and why.

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
        username=context.username,
        agent_id=context.agent_id,
        workspace_id=context.workspace_id,
        workspace_backend_path=context.workspace_backend_path,
        skill_path=skill_path,
        message=message,
    )
