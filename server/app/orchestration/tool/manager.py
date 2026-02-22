"""
Tool manager for discovering, registering, and managing tools.

Supports two execution modes:
- sidecar: Tools run in isolated Podman containers for security and isolation
- local: Tools run directly in the current process (fallback mode)
"""

import importlib
import inspect
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

from .metadata import ToolMetadata
from .sandbox import ExecutionResult, LocalExecutor, PodmanSidecarExecutor

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Manages tool registration, discovery, and execution.

    The ToolManager is responsible for:
    - Auto-discovering tools from the built-in tools directory
    - Registering tools dynamically at runtime
    - Providing access to tool metadata for LLM consumption
    - Executing tools by name (in sidecar or local mode)

    Execution Modes:
    - sidecar: Tools execute in isolated Podman containers (default)
    - local: Tools execute directly in the current process
    """

    def __init__(
        self,
        sandbox_mode: str | None = None,
    ) -> None:
        """
        Initialize the ToolManager with an empty registry.

        Args:
            sandbox_mode: Override the sandbox mode from settings.
                If None, uses the SANDBOX_MODE from environment.
                Values: "sidecar" or "local".
        """
        self._registry: dict[str, ToolMetadata] = {}

        # Determine sandbox mode
        settings = get_settings()
        self._sandbox_mode = sandbox_mode or settings.SANDBOX_MODE

        # Initialize executors lazily
        self._sidecar_executor: PodmanSidecarExecutor | None = None
        self._local_executor: LocalExecutor | None = None

        logger.info(f"ToolManager initialized with sandbox_mode={self._sandbox_mode}")

    @property
    def sandbox_mode(self) -> str:
        """
        Get the current sandbox execution mode.

        Returns:
            The sandbox mode: "sidecar" or "local".
        """
        return self._sandbox_mode

    def _get_sidecar_executor(self) -> PodmanSidecarExecutor:
        """
        Get or create the sidecar executor instance.

        Returns:
            The PodmanSidecarExecutor instance.
        """
        if self._sidecar_executor is None:
            self._sidecar_executor = PodmanSidecarExecutor()
        return self._sidecar_executor

    def _get_local_executor(self) -> LocalExecutor:
        """
        Get or create the local executor instance.

        Returns:
            The LocalExecutor instance.
        """
        if self._local_executor is None:
            self._local_executor = LocalExecutor()
        return self._local_executor

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

        The execution happens either in a sidecar container (default) or
        locally in the current process, depending on the configured mode.

        Args:
            name: The name of the tool to execute.
            *args: Positional arguments (not used in sidecar mode).
            **kwargs: Keyword arguments to pass to the tool.

        Returns:
            The result of the tool execution.

        Raises:
            KeyError: If the tool is not found in the registry.
            RuntimeError: If tool execution fails in sidecar mode.
            Exception: Any exception raised by the tool in local mode.
        """
        tool_metadata = self.get_tool(name)
        if tool_metadata is None:
            raise KeyError(f"Tool '{name}' not found in registry.")

        # Execute based on sandbox mode
        if self._sandbox_mode == "sidecar":
            return self._execute_sidecar(name, kwargs)
        else:
            return self._execute_local(name, tool_metadata.func, kwargs)

    def _execute_sidecar(self, name: str, kwargs: dict[str, Any]) -> Any:
        """
        Execute a tool in a sidecar container.

        Args:
            name: The name of the tool to execute.
            kwargs: Keyword arguments to pass to the tool.

        Returns:
            The result from the tool execution.

        Raises:
            RuntimeError: If sidecar execution fails.
        """
        executor = self._get_sidecar_executor()
        result: ExecutionResult = executor.execute(name, kwargs)

        if not result.success:
            raise RuntimeError(
                f"Tool '{name}' execution failed in sidecar: {result.error}"
            )

        return result.result

    def _execute_local(
        self, name: str, func: Any, kwargs: dict[str, Any]
    ) -> Any:
        """
        Execute a tool locally in the current process.

        Args:
            name: The name of the tool (for logging).
            func: The callable tool function.
            kwargs: Keyword arguments to pass to the tool.

        Returns:
            The result from the tool execution.

        Raises:
            Exception: Any exception raised by the tool function.
        """
        executor = self._get_local_executor()
        result: ExecutionResult = executor.execute(name, kwargs, func)

        if not result.success:
            # Re-raise the original error for local execution
            raise RuntimeError(
                f"Tool '{name}' execution failed: {result.error}"
            )

        return result.result

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

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """
        Generate OpenAI function calling format tool list.

        Returns:
            List of tool definitions in OpenAI tools format.
        """
        return [tool.to_openai_format() for tool in self._registry.values()]

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
