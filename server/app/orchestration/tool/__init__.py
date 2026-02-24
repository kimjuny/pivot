"""
Tool module for function calling capabilities.

Provides decorator-based tool registration and management for agent function calling.
"""

from .decorator import tool
from .manager import (
    ToolExecutionContext,
    ToolManager,
    get_current_tool_execution_context,
    get_tool_manager,
)
from .metadata import ToolMetadata

__all__ = [
    "ToolExecutionContext",
    "ToolManager",
    "ToolMetadata",
    "get_current_tool_execution_context",
    "get_tool_manager",
    "tool",
]
