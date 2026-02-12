"""ReAct System Prompt Template.

This module loads the system prompt template from context_template.md
at server startup and provides utilities to inject context state.
"""

import json
from pathlib import Path

from .context import ReactContext

# Load template from context_template.md at module import time
_TEMPLATE_PATH = Path(__file__).parent / "context_template.md"

try:
    _REACT_SYSTEM_PROMPT_BASE = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError as e:
    raise RuntimeError(
        f"Failed to load ReAct template: {_TEMPLATE_PATH} not found"
    ) from e


def build_system_prompt(context: ReactContext) -> str:
    """
    Build system prompt with injected context state.

    The template is loaded from context_template.md at server startup,
    and this function injects the current state machine snapshot.

    Note: Tool definitions are now passed via the standard 'tools' parameter
    to the LLM API (following OpenAI/GLM standards), not injected into the prompt.

    Args:
        context: ReactContext containing current state machine state

    Returns:
        Complete system prompt with context injected
    """
    # Inject state
    state_json = json.dumps(context.to_dict(), ensure_ascii=False, indent=2)
    prompt = _REACT_SYSTEM_PROMPT_BASE.replace("{{current_state}}", state_json)

    return prompt
