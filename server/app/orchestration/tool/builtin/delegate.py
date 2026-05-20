"""Delegation tool — allows an agent to call another agent during ReAct execution.

This tool is registered for catalog visibility only (so the LLM sees it in the
tool catalog). The actual execution is handled directly by ReactEngine when it
detects a tool call named "delegate_to_agent", bypassing the normal sync tool
execution path because delegation requires running an async sub-engine.
"""

from typing import Annotated, Any

from app.orchestration.tool.decorator import Param, tool


@tool(
    description=(
        "Call another agent to handle a sub-task. Choose the most appropriate "
        "agent from the Delegation Agents section in your instructions. "
        "Provide a clear, self-contained instruction so the target agent can "
        "work independently. "
        "If the delegated agent returned a clarify result, respond using "
        "delegation_context_id and response to continue the delegation."
    )
)
def delegate_to_agent(
    agent: Annotated[
        str | None,
        Param(
            "Agent identifier from the Delegation Agents section. "
            "Required for new delegations, omitted when responding to a clarify."
        ),
    ] = None,
    instruction: Annotated[
        str | None,
        Param(
            "Clear, self-contained task instruction for the target agent. "
            "Include all context the agent needs since it cannot see your "
            "conversation history. Required for new delegations."
        ),
    ] = None,
    delegation_context_id: Annotated[
        str | None,
        Param(
            "Context ID from a previous clarify result. "
            "Provide this (along with response) to resume a paused delegation."
        ),
    ] = None,
    response: Annotated[
        str | None,
        Param(
            "Your answer to the delegated agent's clarify question. "
            "Only used when delegation_context_id is provided."
        ),
    ] = None,
) -> dict[str, Any]:
    """Placeholder — actual execution handled by ReactEngine."""
    return {
        "error": "Delegation must be executed by the engine, not directly",
        "success": False,
    }
