"""
Tool manager for discovering, registering, and managing tools.

Supports two execution modes:
- sidecar: Tools run in isolated Podman containers for security and isolation
- local: Tools run directly in the current process (fallback mode)

Supports two tool sources:
- builtin: Shared tools in app/orchestration/tool/builtin/
- user: Private tools in server/workspace/{username}/tools/
"""

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from sqlmodel import Session

from .metadata import ToolMetadata
from .sandbox import ExecutionResult, LocalExecutor, PodmanSidecarExecutor

logger = logging.getLogger(__name__)

# Workspace base directory
WORKSPACE_BASE = Path(__file__).resolve().parent.parent.parent.parent / "workspace"


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

        For user tools in sidecar mode, the tool source code is passed
        to the sidecar container since the workspace directory is not
        accessible from the Podman VM.

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
            # For user tools, we need to pass the source code to the sidecar
            tool_source = self._get_user_tool_source(name)
            return self._execute_sidecar(name, kwargs, tool_source=tool_source)
        else:
            return self._execute_local(name, tool_metadata.func, kwargs)

    def _is_builtin_tool(self, name: str) -> bool:
        """
        Check if a tool is a builtin (shared) tool.

        Args:
            name: The name of the tool to check.

        Returns:
            True if the tool is a builtin tool, False otherwise.
        """
        builtin_tools_dir = Path(__file__).parent / "builtin"
        tool_file = builtin_tools_dir / f"{name}.py"
        return tool_file.exists()

    def _get_user_tool_source(self, name: str) -> str | None:
        """
        Get the source code of a user tool.

        Args:
            name: The name of the tool.

        Returns:
            The source code if it's a user tool, None if it's a builtin tool.
        """
        if self._is_builtin_tool(name):
            return None

        # Find the user tool file in the workspace
        if not WORKSPACE_BASE.exists():
            return None

        for user_dir in WORKSPACE_BASE.iterdir():
            if user_dir.is_dir():
                tool_file = user_dir / "tools" / f"{name}.py"
                if tool_file.exists():
                    try:
                        return tool_file.read_text(encoding="utf-8")
                    except Exception as e:
                        logger.warning(f"Failed to read user tool {name}: {e}")
                        return None

        return None

    def _execute_sidecar(
        self, name: str, kwargs: dict[str, Any], tool_source: str | None = None
    ) -> Any:
        """
        Execute a tool in a sidecar container.

        Args:
            name: The name of the tool to execute.
            kwargs: Keyword arguments to pass to the tool.
            tool_source: Optional source code for user tools. If provided,
                the sidecar will execute this source instead of loading from
                the builtin directory.

        Returns:
            The result from the tool execution.

        Raises:
            RuntimeError: If sidecar execution fails.
        """
        executor = self._get_sidecar_executor()
        result: ExecutionResult = executor.execute(
            name, kwargs, tool_source=tool_source
        )

        if not result.success:
            raise RuntimeError(
                f"Tool '{name}' execution failed in sidecar: {result.error}"
            )

        return result.result

    def _execute_local(self, name: str, func: Any, kwargs: dict[str, Any]) -> Any:
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
            raise RuntimeError(f"Tool '{name}' execution failed: {result.error}")

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

    def get_tools_for_agent(self, agent_id: int, db: "Session") -> list[ToolMetadata]:
        """
        Get tools enabled for a specific agent.

        If no tools are configured for the agent, returns an empty list.
        This enforces explicit tool assignment per agent.

        Args:
            agent_id: The ID of the agent.
            db: Database session for querying agent tool assignments.

        Returns:
            List of ToolMetadata for tools enabled for this agent.
        """
        from app.models.agent_tool import AgentTool
        from sqlmodel import select

        # Get enabled tool names for this agent
        enabled_tool_names = db.exec(
            select(AgentTool.tool_name).where(AgentTool.agent_id == agent_id)
        ).all()
        enabled_set = set(enabled_tool_names)

        # Return only enabled tools
        result = []
        for name in enabled_set:
            if name in self._registry:
                result.append(self._registry[name])

        return result

    def to_text_catalog_for_agent(self, agent_id: int, db: "Session") -> str:
        """
        Generate a text catalog of tools enabled for a specific agent.

        Args:
            agent_id: The ID of the agent.
            db: Database session for querying agent tool assignments.

        Returns:
            A formatted string containing descriptions of enabled tools.
        """
        tools = self.get_tools_for_agent(agent_id, db)

        if not tools:
            return "No tools available for this agent."

        tool_descriptions = [metadata.to_text() for metadata in tools]
        return "\n\n".join(tool_descriptions)

    def execute_for_agent(
        self,
        agent_id: int,
        name: str,
        db: "Session",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute a tool by name for a specific agent.

        This method checks if the tool is enabled for the agent before
        executing it. If the tool is not enabled, raises a KeyError.

        Args:
            agent_id: The ID of the agent.
            name: The name of the tool to execute.
            db: Database session for querying agent tool assignments.
            *args: Positional arguments (not used in sidecar mode).
            **kwargs: Keyword arguments to pass to the tool.

        Returns:
            The result of the tool execution.

        Raises:
            KeyError: If the tool is not found in registry or not enabled for agent.
            RuntimeError: If tool execution fails in sidecar mode.
            Exception: Any exception raised by the tool in local mode.
        """
        from app.models.agent_tool import AgentTool
        from sqlmodel import select

        # Check if tool is enabled for this agent
        enabled_tool_names = db.exec(
            select(AgentTool.tool_name).where(AgentTool.agent_id == agent_id)
        ).all()
        enabled_set = set(enabled_tool_names)

        if name not in enabled_set:
            available = list(enabled_set) if enabled_set else ["(none configured)"]
            raise KeyError(
                f"Tool '{name}' is not enabled for agent {agent_id}. "
                f"Enabled tools: {', '.join(available)}"
            )

        # Execute the tool using the standard execute method
        return self.execute(name, *args, **kwargs)

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
        self._discover_builtin_tools(tools_dir)
        self._discover_all_user_tools()

    def _discover_builtin_tools(self, tools_dir: Path) -> None:
        """
        Discover and register builtin tools from the builtin directory.

        Args:
            tools_dir: Path to the builtin tools directory.
        """
        if not tools_dir.exists() or not tools_dir.is_dir():
            return

        # Find all Python files in the directory
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            # Import the module dynamically using package path
            module_name = f"app.orchestration.tool.builtin.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                self._register_tools_from_module(module)
            except ImportError as e:
                logger.warning(
                    f"Failed to import builtin tool module {module_name}: {e}"
                )

    def _discover_all_user_tools(self) -> None:
        """
        Discover and register all user tools from workspace directories.

        Scans server/workspace/{username}/tools/ for all users.
        """
        if not WORKSPACE_BASE.exists():
            return

        # Scan each user's workspace
        for user_dir in WORKSPACE_BASE.iterdir():
            if user_dir.is_dir():
                tools_dir = user_dir / "tools"
                if tools_dir.exists() and tools_dir.is_dir():
                    self._discover_user_tools(tools_dir, user_dir.name)

    def _discover_user_tools(self, tools_dir: Path, username: str) -> None:
        """
        Discover and register user tools from a specific user's workspace.

        Args:
            tools_dir: Path to the user's tools directory.
            username: The username (for logging purposes).
        """
        logger.info(f"Discovering user tools for {username} in {tools_dir}")
        for py_file in tools_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            try:
                # Load module from file path
                module_name = f"user_tool.{username}.{py_file.stem}"
                logger.debug(f"Loading user tool module: {module_name} from {py_file}")
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    logger.warning(f"Could not create spec for {py_file}")
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self._register_tools_from_module(module)
                logger.info(
                    f"Successfully loaded user tool: {py_file.stem} from {username}"
                )
            except Exception as e:
                logger.warning(f"Failed to load user tool {py_file}: {e}")

    def _register_tools_from_module(self, module: Any) -> None:
        """
        Register all tools found in a module.

        Args:
            module: The Python module to scan for tools.
        """
        for _name, obj in inspect.getmembers(module, inspect.isfunction):
            metadata = getattr(obj, "__tool_metadata__", None)
            if metadata is not None and isinstance(metadata, ToolMetadata):
                if metadata.name in self._registry:
                    logger.debug(f"Tool {metadata.name} already registered, skipping")
                else:
                    self.add_entry(metadata)
                    logger.debug(f"Registered tool: {metadata.name}")

    def refresh_user_tools(self, username: str) -> None:
        """
        Refresh tools for a specific user.

        Removes all existing tools from this user and reloads them.
        This should be called after creating/updating/deleting a user tool.

        Args:
            username: The username whose tools should be refreshed.
        """
        # Remove existing user tools for this username
        # Note: We can't easily track which tools belong to which user,
        # so we reload all user tools
        tools_dir = WORKSPACE_BASE / username / "tools"
        if tools_dir.exists():
            self._discover_user_tools(tools_dir, username)


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
