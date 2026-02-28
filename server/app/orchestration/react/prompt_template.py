"""ReAct system prompt template builders.

This module loads the split system prompt templates and injects runtime data
into each part. The final prompt is sent as multiple system messages to improve
cache hit rates for the immutable section.
"""

import json
from pathlib import Path
from typing import Any

from app.orchestration.tool.manager import ToolManager

from .context import ReactContext

_TEMPLATE_DIR = Path(__file__).parent
_IMMUTABLE_TEMPLATE_PATH = _TEMPLATE_DIR / "1.system_prompt_immutable.md"
_WEAK_CACHE_TEMPLATE_PATH = _TEMPLATE_DIR / "2.system_prompt_weak_cache.md"
_NO_CACHE_TEMPLATE_PATH = _TEMPLATE_DIR / "3.system_prompt_no_cache.md"


def _read_template(path: Path) -> str:
    """Read a template file with a clear startup error if missing.

    Args:
        path: Template file path.

    Returns:
        Raw template text.

    Raises:
        RuntimeError: If template file does not exist.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RuntimeError(f"Failed to load ReAct template: {path} not found") from e


_REACT_SYSTEM_PROMPT_IMMUTABLE = _read_template(_IMMUTABLE_TEMPLATE_PATH)
_REACT_SYSTEM_PROMPT_WEAK_CACHE = _read_template(_WEAK_CACHE_TEMPLATE_PATH)
_REACT_SYSTEM_PROMPT_NO_CACHE = _read_template(_NO_CACHE_TEMPLATE_PATH)


def build_system_messages(
    context: ReactContext,
    tool_manager: ToolManager | None = None,
    session_memory: dict[str, Any] | None = None,
    skills: str = "",
) -> list[str]:
    """
    Build split system prompt messages with injected runtime state.

    Message order:
    1) immutable strong-cache section
    2) weak-cache section (tools + session memory)
    3) no-cache section (current state + skills)

    Args:
        context: ReactContext containing current state machine state
        tool_manager: Optional tool manager to get available tools description
        session_memory: Optional session memory dictionary for context injection
        skills: Selected skills full-text block for prompt injection

    Returns:
        Three system prompt message contents in fixed order
    """
    state_json = json.dumps(context.to_dict(), ensure_ascii=False, indent=2)

    tools_description = ""
    if tool_manager:
        tools_description = tool_manager.to_text_catalog()

    if session_memory:
        session_memory_json = json.dumps(session_memory, ensure_ascii=False, indent=2)
    else:
        session_memory_json = json.dumps({}, ensure_ascii=False, indent=2)

    immutable_prompt = _REACT_SYSTEM_PROMPT_IMMUTABLE
    weak_cache_prompt = _REACT_SYSTEM_PROMPT_WEAK_CACHE.replace(
        "{{tools_description}}", tools_description
    ).replace("{{session_memory}}", session_memory_json)
    no_cache_prompt = _REACT_SYSTEM_PROMPT_NO_CACHE.replace(
        "{{current_state}}", state_json
    ).replace("{{skills}}", skills)

    return [immutable_prompt, weak_cache_prompt, no_cache_prompt]


def build_system_prompt(
    context: ReactContext,
    tool_manager: ToolManager | None = None,
    session_memory: dict[str, Any] | None = None,
    skills: str = "",
) -> str:
    """Backward-compatible wrapper returning a single concatenated prompt string.

    Args:
        context: ReactContext containing current state machine state.
        tool_manager: Optional tool manager to get available tools description.
        session_memory: Optional session memory dictionary for context injection.
        skills: Selected skills full-text block for prompt injection.

    Returns:
        Concatenated system prompt text built from the three split templates.
    """
    return "\n\n".join(
        build_system_messages(
            context=context,
            tool_manager=tool_manager,
            session_memory=session_memory,
            skills=skills,
        )
    )
