"""ReAct System Prompt Template.

This module loads the system prompt template from context_template.md
at server startup and provides utilities to inject context state.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .context import ReactContext

if TYPE_CHECKING:
    from app.orchestration.tool.manager import ToolManager

# Load template from context_template.md at module import time
_TEMPLATE_PATH = Path(__file__).parent / "context_template.md"

try:
    _REACT_SYSTEM_PROMPT_BASE = _TEMPLATE_PATH.read_text(encoding="utf-8")
except FileNotFoundError as e:
    raise RuntimeError(
        f"Failed to load ReAct template: {_TEMPLATE_PATH} not found"
    ) from e


def build_system_prompt(
    context: ReactContext, tool_manager: "ToolManager | None" = None
) -> str:
    """
    Build system prompt with injected context state and available tools.

    The template is loaded from context_template.md at server startup,
    and this function injects the current state machine snapshot and tool definitions.

    Args:
        context: ReactContext containing current state machine state
        tool_manager: Optional ToolManager to include available tools in prompt

    Returns:
        Complete system prompt with context and tools injected
    """
    # Inject state
    state_json = json.dumps(context.to_dict(), ensure_ascii=False, indent=2)
    prompt = _REACT_SYSTEM_PROMPT_BASE.replace("{{current_state}}", state_json)

    # Inject tools if available
    if tool_manager:
        tools_info = tool_manager.to_openai_tools()
        tools_section = "\n\n## 可用工具列表\n\n"
        tools_section += "你可以在 CALL_TOOL action 中使用以下工具:\n\n"

        for tool in tools_info:
            func = tool.get("function", {})
            tools_section += f"### {func.get('name', 'unknown')}\n"
            tools_section += f"**描述**: {func.get('description', 'N/A')}\n"

            params = func.get("parameters", {}).get("properties", {})
            if params:
                tools_section += "**参数**:\n"
                for param_name, param_info in params.items():
                    param_type = param_info.get("type", "unknown")
                    param_desc = param_info.get("description", "")
                    tools_section += f"- `{param_name}` ({param_type}): {param_desc}\n"
            tools_section += "\n"

        # Insert tools section before "真实动态状态机注入"
        prompt = prompt.replace(
            "## 真实动态状态机注入", f"{tools_section}## 真实动态状态机注入"
        )

    return prompt
