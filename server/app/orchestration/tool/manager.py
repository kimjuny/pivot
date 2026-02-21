"""
Tool manager for discovering, registering, and managing tools.
"""

import importlib
import inspect
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .metadata import ToolMetadata
from .podman_sidecar_executor import PodmanSidecarConfig, PodmanSidecarExecutor

logger = logging.getLogger(__name__)
_PIVOT_CONTEXT_KEY = "__pivot_context"


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
        self._podman_sidecar_executor: PodmanSidecarExecutor | None = None

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

    def execute_local(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """
        Execute a tool in-process by name with the given arguments.

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
        pivot_context = kwargs.pop(_PIVOT_CONTEXT_KEY, None)
        if pivot_context is not None and not isinstance(pivot_context, dict):
            pivot_context = None

        tool_metadata = self.get_tool(name)
        if tool_metadata is None:
            raise KeyError(f"Tool '{name}' not found in registry.")

        from app.config import get_settings

        settings = get_settings()
        start_ts = time.perf_counter()
        thread_id = threading.get_ident()
        if settings.TOOL_EXECUTION_MODE == "podman_sidecar":
            if args:
                raise ValueError("Sidecar tool execution only supports kwargs.")
            logger.info(
                "tool_execute_start mode=podman_sidecar tool=%s thread_id=%s context=%s",
                name,
                thread_id,
                pivot_context,
            )
            try:
                result = self._execute_via_podman_sidecar(
                    name=name, kwargs=kwargs, pivot_context=pivot_context
                )
                elapsed_ms = (time.perf_counter() - start_ts) * 1000
                logger.info(
                    "tool_execute_end mode=podman_sidecar tool=%s thread_id=%s elapsed_ms=%.2f",
                    name,
                    thread_id,
                    elapsed_ms,
                )
                return result
            except Exception:
                elapsed_ms = (time.perf_counter() - start_ts) * 1000
                logger.exception(
                    "tool_execute_error mode=podman_sidecar tool=%s thread_id=%s elapsed_ms=%.2f",
                    name,
                    thread_id,
                    elapsed_ms,
                )
                raise

        logger.info(
            "tool_execute_start mode=local tool=%s thread_id=%s context=%s",
            name,
            thread_id,
            pivot_context,
        )
        try:
            result = tool_metadata.func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            logger.info(
                "tool_execute_end mode=local tool=%s thread_id=%s elapsed_ms=%.2f",
                name,
                thread_id,
                elapsed_ms,
            )
            return result
        except Exception:
            elapsed_ms = (time.perf_counter() - start_ts) * 1000
            logger.exception(
                "tool_execute_error mode=local tool=%s thread_id=%s elapsed_ms=%.2f",
                name,
                thread_id,
                elapsed_ms,
            )
            raise

    def _execute_via_podman_sidecar(
        self,
        name: str,
        kwargs: dict[str, Any],
        pivot_context: dict[str, Any] | None,
    ) -> Any:
        if self._podman_sidecar_executor is None:
            from app.config import get_settings

            settings = get_settings()
            self._podman_sidecar_executor = PodmanSidecarExecutor(
                PodmanSidecarConfig(
                    podman_host=settings.PODMAN_HOST,
                    timeout_seconds=settings.TOOL_SIDECAR_TIMEOUT_SECONDS,
                    network=settings.TOOL_SIDECAR_NETWORK,
                    image=settings.TOOL_SIDECAR_IMAGE,
                )
            )

        return self._podman_sidecar_executor.execute(
            tool_name=name,
            tool_kwargs=kwargs,
            pivot_context=pivot_context,
        )

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
