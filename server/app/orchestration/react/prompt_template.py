"""ReAct System Prompt Template.

This module loads the system prompt template from context_template.md
at server startup and provides utilities to inject context state.
"""

import json
from pathlib import Path

from app.orchestration.tool.manager import ToolManager

from .context import ReactContext

# Load template from context_template.md at module import time
_TEMPLATE_PATH = Path(__file__).parent / "context_template.md"

try:
    _REACT_SYSTEM_PROMPT_BASE = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError as e:
    raise RuntimeError(
        f"Failed to load ReAct template: {_TEMPLATE_PATH} not found"
    ) from e


def build_system_prompt(
    context: ReactContext, tool_manager: ToolManager | None = None
) -> str:
    """
    Build system prompt with injected context state and available tools.

    The template is loaded from context_template.md at server startup,
    and this function injects the current state machine snapshot and tool descriptions.

    Args:
        context: ReactContext containing current state machine state
        tool_manager: Optional tool manager to get available tools description

    Returns:
        Complete system prompt with context and tools injected
    """
    # Inject state
    state_json = json.dumps(context.to_dict(), ensure_ascii=False, indent=2)
    prompt = _REACT_SYSTEM_PROMPT_BASE.replace("{{current_state}}", state_json)

    # Inject tools description
    tools_description = ""
    if tool_manager:
        tools_description = tool_manager.to_text_catalog()

    prompt = prompt.replace("{{tools_description}}", tools_description)

    return prompt
