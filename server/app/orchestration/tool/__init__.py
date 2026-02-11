"""
Tool module for function calling capabilities.

Provides decorator-based tool registration and management for agent function calling.
"""

from .decorator import tool
from .manager import ToolManager, get_tool_manager
from .metadata import ToolMetadata

__all__ = [
    "ToolManager",
    "ToolMetadata",
    "get_tool_manager",
    "tool",
]
