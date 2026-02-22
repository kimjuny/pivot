"""
Tool module for function calling capabilities.

Provides decorator-based tool registration and management for agent function calling.

Execution Modes:
- sidecar: Tools execute in isolated Podman containers (default in development)
- local: Tools execute directly in the current process
"""

from .decorator import tool
from .manager import ToolManager, get_tool_manager
from .metadata import ToolMetadata
from .sandbox import (
    ExecutionResult,
    LocalExecutor,
    PodmanSidecarExecutor,
    SidecarConfig,
    get_sidecar_config,
)

__all__ = [
    "ExecutionResult",
    "LocalExecutor",
    "PodmanSidecarExecutor",
    "SidecarConfig",
    "ToolManager",
    "ToolMetadata",
    "get_sidecar_config",
    "get_tool_manager",
    "tool",
]
