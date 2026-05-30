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
_TASK_TEMPLATE_PATH = _TEMPLATE_DIR / "task_prompt.md"


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
_REACT_TASK_PROMPT = _read_template(_TASK_TEMPLATE_PATH)


def build_runtime_system_prompt(
    tool_manager: ToolManager | None = None,
    skills: str = "[]",
    delegation_agents: str = "",
    channel_context: str = "",
) -> str:
    """Build the stable system prompt used once for an entire session.

    The system prompt includes session-level context (tool catalog and skills
    index) that remains constant across all tasks within the same session.
    Because the system prompt is always restored after context compaction,
    this content never needs to be re-injected per-task.

    Args:
        tool_manager: Optional tool manager to describe available tools.
        skills: Runtime-visible skill metadata JSON for prompt injection.
        delegation_agents: Markdown section listing delegatable agents.
        channel_context: Markdown section for channel environment awareness.

    Returns:
        Rendered system prompt text with tool catalog and skills embedded.
    """
    tools_description = ""
    if tool_manager:
        tools_description = tool_manager.to_text_catalog()

    rendered = _REACT_SYSTEM_PROMPT.replace(
        "{{tools_description}}", tools_description
    ).replace("{{skills}}", skills)

    # Strip the entire delegation section (header + body) when empty
    delegation_section = "## Delegation Agents\n\n{{delegation_agents}}"
    if delegation_agents:
        rendered = rendered.replace(
            delegation_section,
            f"## Delegation Agents\n\n{delegation_agents}",
        )
    else:
        rendered = rendered.replace(delegation_section, "")

    # Inject or strip channel context section
    if channel_context:
        rendered = rendered.replace("{{channel_context}}", channel_context)
    else:
        rendered = rendered.replace("\n{{channel_context}}", "")

    return rendered


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
    mandatory_skills: str = "[]",
    workspace_guidance: str = "",
    prefix_blocks: list[str] | None = None,
    suffix_blocks: list[str] | None = None,
    *,
    timezone_name: str | None = None,
) -> str:
    """Build the task bootstrap user prompt injected once per task.

    Task-level context (mandatory skills, workspace guidance, timestamps) that
    may change between tasks within the same session. Session-stable content
    (tools, skills index) lives in the system prompt instead.

    Sections are included only when they have content — empty mandatory skills
    or missing workspace guidance are omitted entirely to save tokens.

    Args:
        mandatory_skills: User-selected mandatory skill payload JSON. When
            non-empty, a section is added instructing the agent to read each
            skill's SKILL.md on demand.
        workspace_guidance: Project-local repository guidance (from AGENTS.md
            or CLAUDE.md). When non-empty, a section is added telling the agent
            to follow these rules.
        prefix_blocks: Additional prompt blocks inserted before the standard
            bootstrap template body.
        suffix_blocks: Additional prompt blocks inserted after the standard
            bootstrap template body.
        timezone_name: IANA timezone name to use for displaying the current
            time. When ``None``, falls back to the ``SYSTEM_TIME_ZONE`` env var.

    Returns:
        Rendered task prompt text with conditional sections injected.
    """
    sections: list[str] = []

    base = _REACT_TASK_PROMPT.replace(
        "{{system_time}}", _format_task_start_time(timezone_name=timezone_name)
    ).strip()
    sections.append(base)

    if mandatory_skills and mandatory_skills != "[]":
        sections.append(
            "## Mandatory Skills\n\n"
            "User-selected skills for this task. Read each skill's SKILL.md "
            "at the given path before applying it. If you already know a skill "
            "from prior context, you may skip re-reading.\n\n"
            f"```json\n{mandatory_skills}\n```"
        )

    if workspace_guidance:
        sections.append(
            "## Workspace Guidance\n\n"
            "You MUST follow the rules in this file:\n\n"
            f"````markdown\n{workspace_guidance}\n````"
        )

    all_blocks: list[str] = [
        *[block.strip() for block in (prefix_blocks or []) if block.strip()],
        *sections,
        *[block.strip() for block in (suffix_blocks or []) if block.strip()],
    ]
    return "\n\n".join(all_blocks)


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
