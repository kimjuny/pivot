"""
Sidecar container entrypoint for isolated tool execution.

This module serves as the entry point when running tool functions inside
a Podman sidecar container. It receives the tool name and arguments via
command-line arguments, executes the tool, and outputs the result as JSON
to stdout.

For user tools, the source code is passed via --tool-source argument
(base64 encoded) since the workspace directory is not accessible from
the Podman VM on macOS.
"""

import argparse
import base64
import contextlib
import importlib.util
import inspect
import json
import logging
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# Mark this process as running in a sidecar container
os.environ["PIVOT_SIDECAR"] = "1"

# Configure minimal logging to stderr (stdout is reserved for JSON output)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the sidecar entrypoint.

    Returns:
        Parsed arguments containing tool_name, tool_args, and optionally tool_source.
    """
    parser = argparse.ArgumentParser(
        description="Execute a tool function in a sidecar container"
    )
    parser.add_argument(
        "--tool-name",
        required=True,
        help="Name of the registered tool to execute",
    )
    parser.add_argument(
        "--tool-args",
        required=True,
        help="JSON-encoded keyword arguments for the tool",
    )
    parser.add_argument(
        "--tool-source",
        required=False,
        default=None,
        help="Base64-encoded tool source code (for user tools)",
    )
    return parser.parse_args()


def load_tool_from_source(tool_name: str, tool_source_b64: str) -> Any:
    """
    Load a tool function from base64-encoded source code.

    This is used for user tools that are not available in the sidecar's
    builtin directory. The source code is written to a temp file and
    loaded dynamically.

    Args:
        tool_name: The name of the tool to retrieve.
        tool_source_b64: Base64-encoded Python source code.

    Returns:
        The callable tool function.

    Raises:
        KeyError: If the tool is not found in the source code.
        RuntimeError: If the source code fails to load.
    """
    try:
        # Decode the source code
        tool_source = base64.b64decode(tool_source_b64).decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to decode tool source: {e}") from e

    # Write to a temp file and load
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as temp_file:
            temp_file.write(tool_source)
            temp_path = temp_file.name

        # Load the module from the temp file
        module_name = f"user_tool.sidecar.{tool_name}"
        spec = importlib.util.spec_from_file_location(module_name, temp_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not create module spec for {tool_name}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Find the tool function with matching name
        for _name, obj in inspect.getmembers(module, inspect.isfunction):
            # Check if this function has tool metadata
            metadata = getattr(obj, "__tool_metadata__", None)
            if (
                metadata is not None
                and hasattr(metadata, "name")
                and metadata.name == tool_name
            ):
                logger.info(f"Loaded user tool '{tool_name}' from source")
                return obj

        # If no matching tool found, raise error
        raise KeyError(
            f"Tool '{tool_name}' not found in provided source code. "
            f"Make sure the @tool decorator has the correct name."
        )

    finally:
        # Clean up temp file
        if temp_path is not None:
            with contextlib.suppress(Exception):
                Path(temp_path).unlink()


def discover_builtin_tool(tool_name: str) -> Any:
    """
    Discover a builtin tool from the builtin directory.

    Args:
        tool_name: The name of the tool to retrieve.

    Returns:
        The callable tool function.

    Raises:
        KeyError: If the tool is not found in the registry.
        RuntimeError: If tool discovery fails.
    """
    from pathlib import Path

    from app.orchestration.tool.manager import get_tool_manager

    # Get the tool manager and discover built-in tools
    tool_manager = get_tool_manager()

    # Discover tools from the builtin directory
    builtin_tools_dir = Path(__file__).parent / "builtin"
    if builtin_tools_dir.exists():
        tool_manager.refresh(builtin_tools_dir)

    # Get the requested tool
    tool_metadata = tool_manager.get_tool(tool_name)
    if tool_metadata is None:
        available_tools = [t.name for t in tool_manager.list_tools()]
        raise KeyError(
            f"Tool '{tool_name}' not found. Available tools: {available_tools}"
        )

    return tool_metadata.func


def execute_tool(
    tool_name: str, tool_args: dict[str, Any], tool_source: str | None = None
) -> dict[str, Any]:
    """
    Execute a tool function with the given arguments.

    Args:
        tool_name: The name of the tool to execute.
        tool_args: Keyword arguments to pass to the tool function.
        tool_source: Optional base64-encoded source code for user tools.

    Returns:
        A dictionary containing the execution result or error.
    """
    try:
        # Get the tool function
        if tool_source:
            # User tool - load from source code
            tool_func = load_tool_from_source(tool_name, tool_source)
        else:
            # Builtin tool - discover from builtin directory
            tool_func = discover_builtin_tool(tool_name)

        # Execute the tool
        result = tool_func(**tool_args)

        # Handle non-JSON-serializable results
        try:
            # Test if result is JSON serializable
            json.dumps(result)
        except (TypeError, ValueError) as e:
            logger.warning(
                f"Tool result is not JSON serializable, converting to string: {e}"
            )
            result = str(result)

        return {
            "success": True,
            "result": result,
            "error": None,
        }

    except KeyError as e:
        error_msg = str(e)
        logger.error(f"Tool not found: {error_msg}")
        return {
            "success": False,
            "result": None,
            "error": error_msg,
        }
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        full_traceback = traceback.format_exc()
        logger.error(f"Tool execution failed: {full_traceback}")
        return {
            "success": False,
            "result": None,
            "error": error_msg,
        }


def main() -> int:
    """
    Main entry point for the sidecar container.

    Parses arguments, executes the tool, and outputs the result as JSON
    to stdout. This output is consumed by the PodmanSidecarExecutor.

    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    args = parse_args()

    # Parse tool arguments from JSON
    try:
        tool_args = json.loads(args.tool_args)
        if not isinstance(tool_args, dict):
            tool_args = {}
    except json.JSONDecodeError as e:
        error_output = json.dumps(
            {
                "success": False,
                "result": None,
                "error": f"Failed to parse tool_args JSON: {e}",
            }
        )
        print(error_output, flush=True)
        return 1

    # Execute the tool
    result = execute_tool(args.tool_name, tool_args, tool_source=args.tool_source)

    # Output result as JSON to stdout (must be the only stdout output)
    print(json.dumps(result, ensure_ascii=False), flush=True)

    # Return exit code based on success
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
