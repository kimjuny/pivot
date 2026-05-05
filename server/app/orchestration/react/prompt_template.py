"""ReAct prompt template builders."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.orchestration.tool.manager import ToolManager

_TEMPLATE_DIR = Path(__file__).parent
_SYSTEM_TEMPLATE_PATH = _TEMPLATE_DIR / "system_prompt.md"
_USER_TEMPLATE_PATH = _TEMPLATE_DIR / "user_prompt.md"


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


_REACT_SYSTEM_PROMPT = _read_template(_SYSTEM_TEMPLATE_PATH)
_REACT_USER_PROMPT = _read_template(_USER_TEMPLATE_PATH)


def build_runtime_system_prompt() -> str:
    """Build the stable system prompt used once for an entire session.

    Returns:
        System prompt text containing only stable role/schema guidance.
    """
    return _REACT_SYSTEM_PROMPT


def _format_task_start_time(
    now: datetime | None = None,
    *,
    timezone_name: str | None = None,
) -> str:
    """Format the task-start time for prompt injection."""
    selected_timezone_name = timezone_name or get_settings().SYSTEM_TIME_ZONE
    try:
        timezone = ZoneInfo(selected_timezone_name)
    except ZoneInfoNotFoundError:
        selected_timezone_name = "UTC"
        timezone = ZoneInfo(selected_timezone_name)

    task_start_time = (now or datetime.now(timezone)).astimezone(timezone)
    offset = task_start_time.strftime("%z")
    formatted_offset = f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"
    return (
        f"{task_start_time:%Y-%m-%d %H:%M:%S} "
        f"{selected_timezone_name} (UTC{formatted_offset})"
    )


def build_runtime_user_prompt(
    tool_manager: ToolManager | None = None,
    skills: str = "",
    mandatory_skills: str = "[]",
    workspace_guidance: str = "",
    prefix_blocks: list[str] | None = None,
    suffix_blocks: list[str] | None = None,
) -> str:
    """Build the task bootstrap user prompt injected once per task.

    Args:
        tool_manager: Optional tool manager to describe available tools.
        skills: Runtime-visible skill metadata JSON for prompt injection.
        mandatory_skills: User-selected mandatory skill payload JSON injected
            into the task bootstrap prompt.
        workspace_guidance: Project-local repository guidance injected into the
            task bootstrap prompt.
        prefix_blocks: Additional prompt blocks inserted before the standard
            bootstrap template body.
        suffix_blocks: Additional prompt blocks inserted after the standard
            bootstrap template body.

    Returns:
        Rendered user prompt text with task-scoped dynamic context injected.
    """
    tools_description = ""
    if tool_manager:
        tools_description = tool_manager.to_text_catalog()

    rendered_prompt = (
        _REACT_USER_PROMPT.replace("{{tools_description}}", tools_description)
        .replace("{{system_time}}", _format_task_start_time())
        .replace("{{skills}}", skills)
        .replace("{{mandatory_skills}}", mandatory_skills)
        .replace("{{workspace_guidance}}", workspace_guidance)
    )
    ordered_sections = [
        *[block.strip() for block in (prefix_blocks or []) if block.strip()],
        rendered_prompt.strip(),
        *[block.strip() for block in (suffix_blocks or []) if block.strip()],
    ]
    return "\n\n".join(ordered_sections)


def build_runtime_task_bootstrap_message(user_prompt: str) -> dict[str, Any]:
    """Build the task-opening user prompt message.

    Args:
        user_prompt: Rendered task bootstrap prompt.

    Returns:
        One chat message dictionary ready for persistence or transport.
    """
    return {"role": "user", "content": user_prompt}


def build_runtime_payload_message(
    payload: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one runtime payload user message.

    Args:
        payload: Structured recursion payload injected into the user turn.
        attachments: Optional multimodal blocks appended after the text payload.

    Returns:
        One chat message dictionary ready for persistence or transport.
    """
    message_content: str | list[dict[str, Any]] = json.dumps(
        payload,
        ensure_ascii=False,
    )
    if attachments:
        message_content = [{"type": "text", "text": message_content}, *attachments]
    return {"role": "user", "content": message_content}
