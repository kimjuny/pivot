"""
Tool manager for discovering, registering, and managing tools.
"""

import importlib
import inspect
from pathlib import Path
from typing import Any

from .metadata import ToolMetadata


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

    def execute(self, name: str, *args: Any, **kwargs: Any) -> Any:
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
        return tool_metadata.func(*args, **kwargs)

    def to_text_catalog(self) -> str:
        """
        Generate a text catalog of all registered tools for LLM consumption.

        Returns:
            A formatted string containing all tool descriptions.
        """
        if not self._registry:
            return "No tools available."

        tool_descriptions = [metadata.to_text() for metadata in self._registry.values()]
        return "\n\n".join(tool_descriptions)

    def refresh(self, tools_dir: Path) -> None:
        """
        Refresh the tool registry by scanning a directory for tool modules.

        This method discovers all Python modules in the given directory,
        imports them, and registers any functions decorated with @tool.

        Args:
            tools_dir: Path to the directory containing tool modules.

        Note:
            This method clears the existing registry before scanning.
            Existing tools will be lost unless they are re-discovered.
        """
        self._registry.clear()
        self._discover_tools(tools_dir)

    def _discover_tools(self, tools_dir: Path) -> None:
        """
        Discover and register tools from a directory.

        Scans all Python files in the directory (excluding __init__.py),
        imports them, and registers any decorated tool functions.

        Args:
            tools_dir: Path to the directory containing tool modules.
        """
        if not tools_dir.exists() or not tools_dir.is_dir():
            return

        # Find all Python files in the directory
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                # Skip private modules and __init__.py
                continue

            # Import the module dynamically
            module_name = f"app.orchestration.tool.builtin.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)

                # Scan the module for decorated functions
                for _name, obj in inspect.getmembers(module, inspect.isfunction):
                    # Check if the function has tool metadata
                    metadata = getattr(obj, "__tool_metadata__", None)
                    if (
                        metadata is not None
                        and isinstance(metadata, ToolMetadata)
                        and metadata.name not in self._registry
                    ):
                        self.add_entry(metadata)
            except ImportError:
                # Skip modules that fail to import
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
