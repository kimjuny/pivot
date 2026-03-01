"""ReAct prompt template builders."""

import json
from pathlib import Path
from typing import Any

from app.orchestration.tool.manager import ToolManager

_TEMPLATE_DIR = Path(__file__).parent
_MONO_TEMPLATE_PATH = _TEMPLATE_DIR / "system_prompt.md"


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


_REACT_SYSTEM_PROMPT_MONO = _read_template(_MONO_TEMPLATE_PATH)


def build_runtime_system_prompt(
    tool_manager: ToolManager | None = None,
    session_memory: dict[str, Any] | None = None,
    skills: str = "",
) -> str:
    """Build a single system prompt used for an entire task lifecycle.

    This prompt intentionally excludes per-recursion mutable fields so that task
    execution can append user/assistant messages incrementally without mutating
    existing prompt tokens, which improves provider-side context cache hit rates.

    Args:
        tool_manager: Optional tool manager to get available tools description.
        session_memory: Optional session memory dictionary for context injection.
        skills: Selected skills full-text block for prompt injection.

    Returns:
        System prompt text with tools/session-memory/skills injected.
    """
    tools_description = ""
    if tool_manager:
        tools_description = tool_manager.to_text_catalog()

    if session_memory:
        session_memory_json = json.dumps(session_memory, ensure_ascii=False, indent=2)
    else:
        session_memory_json = json.dumps({}, ensure_ascii=False, indent=2)

    return (
        _REACT_SYSTEM_PROMPT_MONO.replace("{{tools_description}}", tools_description)
        .replace("{{session_memory}}", session_memory_json)
        .replace("{{skills}}", skills)
    )
