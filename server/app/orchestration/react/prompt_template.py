"""ReAct System Prompt Template.

This module loads the system prompt template from context_template.md
at server startup and provides utilities to inject context state.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.orchestration.tool.manager import ToolManager

from .context import ReactContext

if TYPE_CHECKING:
    from sqlmodel import Session

# Load template from context_template.md at module import time
_TEMPLATE_PATH = Path(__file__).parent / "context_template.md"

try:
    _REACT_SYSTEM_PROMPT_BASE = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError as e:
    raise RuntimeError(
        f"Failed to load ReAct template: {_TEMPLATE_PATH} not found"
    ) from e


def build_system_prompt(
    context: ReactContext,
    tool_manager: ToolManager | None = None,
    session_memory: dict[str, Any] | None = None,
    agent_id: int | None = None,
    db: "Session | None" = None,
) -> str:
    """
    Build system prompt with injected context state, available tools, and session memory.

    The template is loaded from context_template.md at server startup,
    and this function injects the current state machine snapshot, tool descriptions,
    and session memory.

    If agent_id and db are provided, only tools enabled for that agent will be
    included in the prompt. Otherwise, all registered tools are included.

    Args:
        context: ReactContext containing current state machine state
        tool_manager: Optional tool manager to get available tools description
        session_memory: Optional session memory dictionary for context injection
        agent_id: Optional agent ID to filter tools by agent configuration
        db: Optional database session required when agent_id is provided

    Returns:
        Complete system prompt with context, tools, and session memory injected
    """
    # Inject state
    state_json = json.dumps(context.to_dict(), ensure_ascii=False, indent=2)
    prompt = _REACT_SYSTEM_PROMPT_BASE.replace("{{current_state}}", state_json)

    # Inject tools description
    tools_description = ""
    if tool_manager:
        if agent_id is not None and db is not None:
            # Use agent-specific tools
            tools_description = tool_manager.to_text_catalog_for_agent(agent_id, db)
        else:
            # Fallback to all tools (for backward compatibility)
            tools_description = tool_manager.to_text_catalog()

    prompt = prompt.replace("{{tools_description}}", tools_description)

    # Inject session memory
    if session_memory:
        session_memory_json = json.dumps(session_memory, ensure_ascii=False, indent=2)
    else:
        # Empty session memory for new sessions
        session_memory_json = json.dumps({}, ensure_ascii=False, indent=2)

    prompt = prompt.replace("{{session_memory}}", session_memory_json)

    return prompt
