"""
Tool manager for discovering, registering, and managing tools.
"""

import importlib
import inspect
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .metadata import ToolMetadata

_tool_execution_context: ContextVar["ToolExecutionContext | None"] = ContextVar(
    "tool_execution_context",
    default=None,
)


@dataclass(frozen=True)
class ToolExecutionContext:
    """Execution context for a single tool call."""

    username: str
    agent_id: int
    workspace_id: str
    workspace_backend_path: str
    session_id: str | None = None
    sandbox_timeout_seconds: int = 60
    web_search_provider: str | None = None
    allowed_skills: tuple[dict[str, str], ...] = ()


def get_current_tool_execution_context() -> ToolExecutionContext | None:
    """Return the current tool execution context, if any."""
    return _tool_execution_context.get()


class ToolManager:
    """
    Manages tool registration, discovery, and execution.

    The ToolManager is responsible for:
    - Auto-discovering tools from the built-in tools directory
    - Registering tools dynamically at runtime
    - Providing access to tool metadata for LLM consumption
    - Executing tools by name
    """

    def __init__(self) -> None:
        """Initialize the ToolManager with an empty registry."""
        self._registry: dict[str, ToolMetadata] = {}

    def add_entry(self, metadata: ToolMetadata) -> None:
        """
        Register a single tool with the manager.

        Args:
            metadata: The tool metadata to register.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if metadata.name in self._registry:
            raise ValueError(
                f"Tool '{metadata.name}' is already registered. "
                "Use a different name or remove the existing tool first."
            )
        self._registry[metadata.name] = metadata

    def remove_entry(self, name: str) -> None:
        """
        Remove a tool from the registry.

        Args:
            name: The name of the tool to remove.

        Raises:
            KeyError: If the tool is not found in the registry.
        """
        if name not in self._registry:
            raise KeyError(f"Tool '{name}' not found in registry.")
        del self._registry[name]

    def get_tool(self, name: str) -> ToolMetadata | None:
        """
        Retrieve tool metadata by name.

        Args:
            name: The name of the tool to retrieve.

        Returns:
            The tool metadata if found, None otherwise.
        """
        return self._registry.get(name)

    def list_tools(self) -> list[ToolMetadata]:
        """
        Get a list of all registered tools.

        Returns:
            List of all tool metadata in the registry.
        """
        return list(self._registry.values())

    def execute(
        self,
        name: str,
        *args: Any,
        context: ToolExecutionContext | None = None,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a tool by name with the given arguments.

        Args:
            name: The name of the tool to execute.
            *args: Positional arguments to pass to the tool.
            **kwargs: Keyword arguments to pass to the tool.

        Returns:
            The result of the tool execution.

        Raises:
            KeyError: If the tool is not found in the registry.
        """
        tool_metadata = self.get_tool(name)
        if tool_metadata is None:
            raise KeyError(f"Tool '{name}' not found in registry.")
        token = None
        if context is not None:
            token = _tool_execution_context.set(context)
        try:
            return tool_metadata.func(*args, **kwargs)
        finally:
            if token is not None:
                _tool_execution_context.reset(token)

    def to_text_catalog(self) -> str:
        """Generate a JSON-structured catalog of all registered tools for LLM consumption.

        Each tool is represented as a JSON object with ``name``, ``description``,
        and ``parameters`` fields.  The entire catalog is a JSON array so the LLM
        receives a consistently structured, unambiguous tool list regardless of
        how complex the individual descriptions are.

        Returns:
            Pretty-printed JSON array string, or the string ``"[]"`` when empty.
        """
        import json

        tools = [meta.to_dict() for meta in self._registry.values()]
        return json.dumps(tools, ensure_ascii=False, indent=2)

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """
        Generate OpenAI function calling format tool list.

        Returns:
            List of tool definitions in OpenAI tools format.
        """
        return [tool.to_openai_format() for tool in self._registry.values()]

    def refresh(
        self, tools_dir: Path, *, module_prefix: str = "app.orchestration.tool.builtin"
    ) -> None:
        """Refresh the tool registry by scanning a directory for tool modules.

        Clears the existing registry then re-discovers all tools from the given
        directory. Pass a custom ``module_prefix`` when loading tools from a
        non-builtin location (e.g. a user workspace directory).

        Args:
            tools_dir: Path to the directory containing tool modules.
            module_prefix: Dotted Python module prefix used when importing files
                from ``tools_dir``. Defaults to the builtin package prefix.

        Note:
            This method clears the existing registry before scanning.
            Existing tools will be lost unless they are re-discovered.
        """
        self._registry.clear()
        self._discover_tools(tools_dir, module_prefix=module_prefix)

    def _discover_tools(
        self, tools_dir: Path, *, module_prefix: str = "app.orchestration.tool.builtin"
    ) -> None:
        """Discover and register tools from a directory.

        Scans all Python files in the directory (excluding ``__init__.py`` and
        other private modules), imports them, and registers any functions
        decorated with ``@tool``.

        Args:
            tools_dir: Path to the directory containing tool modules.
            module_prefix: Dotted Python module prefix for dynamic imports.
        """
        if not tools_dir.exists() or not tools_dir.is_dir():
            return

        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_name = f"{module_prefix}.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)

                for _name, obj in inspect.getmembers(module, inspect.isfunction):
                    metadata = getattr(obj, "__tool_metadata__", None)
                    if (
                        metadata is not None
                        and isinstance(metadata, ToolMetadata)
                        and metadata.name not in self._registry
                    ):
                        self.add_entry(metadata)
            except ImportError:
                continue


# Global singleton instance
_tool_manager: ToolManager | None = None


def get_tool_manager() -> ToolManager:
    """
    Get the global ToolManager singleton instance.

    Returns:
        The global ToolManager instance.
    """
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = ToolManager()
    return _tool_manager
