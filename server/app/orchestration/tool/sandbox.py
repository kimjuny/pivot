"""
Sandbox execution module for tool isolation.

This module provides Podman-based sidecar container execution for tool isolation,
enabling secure and isolated function execution in separate containers.
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SidecarConfig:
    """
    Configuration for Podman sidecar container execution.

    Attributes:
        podman_socket_path: Path to the Podman socket file.
        timeout_seconds: Maximum execution time for a tool call.
        network_mode: Network mode for the sidecar container (None for isolated, "host" for minimal overhead).
        base_image: Base image for sidecar containers (defaults to current image).
        memory_limit: Memory limit for container (e.g., "256m", "1g").
        cpu_quota: CPU quota in microseconds per period (e.g., 50000 = 50% CPU).
    """

    podman_socket_path: str
    timeout_seconds: int
    network_mode: str | None
    base_image: str | None
    memory_limit: str | None = None
    cpu_quota: int | None = None


@dataclass
class ExecutionResult:
    """
    Result of a tool execution in the sidecar container.

    Attributes:
        success: Whether the execution completed without errors.
        result: The return value from the tool function (if successful).
        error: Error message if execution failed.
    """

    success: bool
    result: Any
    error: str | None = None


def get_sidecar_config() -> SidecarConfig:
    """
    Create a SidecarConfig from the current application settings.

    Returns:
        A SidecarConfig instance populated from environment settings.
    """
    settings = get_settings()
    return SidecarConfig(
        podman_socket_path=settings.PODMAN_SOCKET_PATH,
        timeout_seconds=settings.SIDECAR_TIMEOUT_SECONDS,
        network_mode=settings.SIDECAR_NETWORK_MODE,
        base_image=settings.SIDECAR_BASE_IMAGE,
        memory_limit=settings.SIDECAR_MEMORY_LIMIT,
        cpu_quota=settings.SIDECAR_CPU_QUOTA,
    )


class PodmanSidecarExecutor:
    """
    Executes tool functions in isolated Podman sidecar containers.

    This class manages the creation, execution, and cleanup of ephemeral
    containers that run tool functions in isolation from the main process.

    The sidecar approach provides:
    - Process isolation for tool execution
    - Resource limits and timeouts
    - Network isolation options
    - Consistent execution environment

    Performance Characteristics:
    - Container creation: ~50-200ms (depends on image cache)
    - Container startup: ~10-50ms
    - Tool execution: varies by tool complexity
    - Container cleanup: ~5-20ms
    - Total overhead: ~100-300ms per tool call

    Optimization Opportunities (Future):
    1. Container pooling: Pre-warm containers to reduce creation overhead
    2. Resource limits: Add CPU/memory constraints to prevent runaway tools
    3. Host network mode: Reduce network overlay overhead for local tools
    4. Parallel execution: Execute multiple independent tools concurrently
    5. Result caching: Cache idempotent tool results
    """

    def __init__(self, config: SidecarConfig | None = None) -> None:
        """
        Initialize the PodmanSidecarExecutor.

        Args:
            config: Sidecar configuration. If None, uses default from settings.
        """
        self.config = config or get_sidecar_config()
        self._client: Any = None
        self._current_image: str | None = None

    def _get_client(self) -> Any:
        """
        Get or create the Podman client connection.

        Returns:
            A Podman client instance connected to the configured socket.

        Raises:
            RuntimeError: If the Podman client cannot be initialized.
        """
        if self._client is None:
            try:
                from podman import PodmanClient

                socket_path = self.config.podman_socket_path
                # Use unix socket URI format for local socket connection
                uri = f"unix://{socket_path}"
                self._client = PodmanClient(base_url=uri)
                logger.info(f"Connected to Podman at {uri}")
            except ImportError as e:
                raise RuntimeError(
                    "podman-py library not installed. "
                    "Please add 'podman' to your dependencies."
                ) from e
            except Exception as e:
                raise RuntimeError(
                    f"Failed to connect to Podman socket at "
                    f"{self.config.podman_socket_path}: {e}"
                ) from e
        return self._client

    def _detect_current_image(self) -> str:
        """
        Detect the container image to use for sidecar containers.

        When running inside a container, uses the current container's image.
        Otherwise, uses the configured base_image or falls back to a default.

        Returns:
            The image name/ID to use for sidecar containers.

        Raises:
            RuntimeError: If no suitable image can be determined.
        """
        if self._current_image is not None:
            return self._current_image

        # First, check if a base image is explicitly configured
        if self.config.base_image:
            self._current_image = self.config.base_image
            return self._current_image

        # Try to detect the current container's image when running in a container
        # This is done by reading the container's hostname and looking it up
        container_hostname = os.getenv("HOSTNAME")
        if container_hostname:
            try:
                client = self._get_client()
                containers = client.containers.list(
                    all=False, filters={"name": container_hostname}
                )
                if containers:
                    # Found the current container, get its image
                    container = containers[0]
                    image_id = container.image.id
                    self._current_image = image_id
                    logger.info(
                        f"Detected current container image: {image_id[:12]}"
                    )
                    return self._current_image
            except Exception as e:
                logger.warning(
                    f"Failed to detect current container image: {e}. "
                    "Falling back to configured image."
                )

        # Fall back to a well-known image name
        # In development, this should match the compose service name or
        # the SIDECAR_BASE_IMAGE environment variable if set
        fallback_image = self.config.base_image or "docker.io/library/pivot-backend:latest"
        self._current_image = fallback_image
        logger.warning(
            f"Could not detect current container image, using default: "
            f"{self._current_image}"
        )
        return self._current_image

    def _get_container_hostname(self) -> str | None:
        """
        Get the hostname of the current container (if running in one).

        Returns:
            The container hostname or None if not in a container.
        """
        return os.getenv("HOSTNAME")

    def execute(
        self,
        tool_name: str,
        tool_kwargs: dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute a tool function in an isolated sidecar container.

        Creates an ephemeral container, runs the tool function, captures
        the result, and cleans up the container.

        Args:
            tool_name: The name of the registered tool to execute.
            tool_kwargs: Keyword arguments to pass to the tool function.

        Returns:
            An ExecutionResult containing the success status, return value,
            and any error message.

        Note:
            The sidecar container uses --volumes-from to share the current
            container's volumes, ensuring access to the same codebase and
            data directories.
        """
        # Performance timing
        t_start = time.perf_counter()
        t_create_start = 0.0
        t_create_end = 0.0
        t_start_end = 0.0
        t_exec_end = 0.0
        t_cleanup_end = 0.0

        try:
            client = self._get_client()
            image = self._detect_current_image()
            current_hostname = self._get_container_hostname()

            # Prepare the command to run in the sidecar container
            # The entrypoint script handles tool execution
            tool_args_json = json.dumps(tool_kwargs, ensure_ascii=False)

            # Build the command that will be executed inside the sidecar
            # Use poetry run to ensure correct Python environment
            cmd = [
                "poetry",
                "run",
                "python",
                "-m",
                "app.orchestration.tool.sidecar_entrypoint",
                "--tool-name",
                tool_name,
                "--tool-args",
                tool_args_json,
            ]

            # Container configuration
            container_config: dict[str, Any] = {
                "image": image,
                "command": cmd,
                "detach": True,
                "stdin_open": True,
                "working_dir": "/app/server",  # Set correct working directory for app module
                "environment": {
                    "PYTHONUNBUFFERED": "1",
                },
            }

            # Note: volumes_from doesn't work reliably in podman machine environment
            # Instead, we rely on the fact that the sidecar uses the same image
            # which already has the codebase baked in (via Containerfile.dev)

            # Configure network mode if specified
            if self.config.network_mode:
                container_config["network_mode"] = self.config.network_mode

            # Configure resource limits if specified
            if self.config.memory_limit:
                container_config["mem_limit"] = self.config.memory_limit
            if self.config.cpu_quota:
                # CPU quota requires CPU period to be set (default period is 100000us = 100ms)
                container_config["cpu_quota"] = self.config.cpu_quota
                container_config["cpu_period"] = 100000

            # Log the container config for debugging
            logger.debug(f"Creating sidecar container with config: {container_config}")

            # Create the container
            t_create_start = time.perf_counter()
            try:
                container = client.containers.create(**container_config)
            except Exception as create_error:
                # Provide more detailed error information
                error_details = str(create_error)
                logger.error(
                    f"Failed to create sidecar container for tool '{tool_name}': "
                    f"{error_details}"
                )
                raise
            t_create_end = time.perf_counter()
            container_id = container.id[:12]

            try:
                # Start the container and wait for completion
                container.start()
                t_start_end = time.perf_counter()

                result = container.wait(timeout=self.config.timeout_seconds)
                t_exec_end = time.perf_counter()

                # Handle different return types from wait()
                # podman-py may return int directly or dict with StatusCode
                if isinstance(result, int):
                    exit_code = result
                elif isinstance(result, dict):
                    exit_code = result.get("StatusCode", -1)
                else:
                    exit_code = -1
                    logger.warning(f"Unexpected wait() result type: {type(result)}")

                stdout_logs = container.logs(stdout=True, stderr=False)
                stderr_logs = container.logs(stdout=False, stderr=True)

                # Handle different log return types (bytes, str, generator)
                def decode_logs(logs: Any) -> str:
                    """Decode container logs to string."""
                    if logs is None:
                        return ""
                    if isinstance(logs, bytes):
                        return logs.decode("utf-8")
                    if isinstance(logs, str):
                        return logs
                    # Handle generator or iterator
                    if hasattr(logs, "__iter__") and not isinstance(logs, (str, bytes)):
                        # It's a generator or iterator, consume it
                        chunks = []
                        for chunk in logs:
                            if isinstance(chunk, bytes):
                                chunks.append(chunk.decode("utf-8"))
                            else:
                                chunks.append(str(chunk))
                        return "".join(chunks)
                    return str(logs)

                stdout_str = decode_logs(stdout_logs)
                stderr_str = decode_logs(stderr_logs)

                if exit_code == 0:
                    # Parse the result from stdout
                    try:
                        result_data = json.loads(stdout_str.strip())
                        logger.info(
                            f"Tool '{tool_name}' executed successfully in "
                            f"sidecar {container_id}"
                        )
                        return ExecutionResult(
                            success=True,
                            result=result_data.get("result"),
                            error=result_data.get("error"),
                        )
                    except json.JSONDecodeError as e:
                        error_msg = f"Failed to parse sidecar output: {e}"
                        logger.error(
                            f"{error_msg}\nStdout: {stdout_str}\nStderr: {stderr_str}"
                        )
                        return ExecutionResult(
                            success=False,
                            result=None,
                            error=error_msg,
                        )
                else:
                    error_msg = stderr_str.strip() or f"Exit code: {exit_code}"
                    logger.error(
                        f"Tool '{tool_name}' failed in sidecar {container_id}: "
                        f"{error_msg}"
                    )
                    return ExecutionResult(
                        success=False,
                        result=None,
                        error=error_msg,
                    )

            finally:
                # Always clean up the container
                try:
                    container.remove(force=True)
                    t_cleanup_end = time.perf_counter()
                except Exception as e:
                    logger.warning(
                        f"Failed to remove sidecar container {container_id}: {e}"
                    )
                    t_cleanup_end = time.perf_counter()

                # Log performance statistics
                t_total = (t_cleanup_end - t_start) * 1000  # Convert to ms
                t_create = (t_create_end - t_create_start) * 1000
                t_startup = (t_start_end - t_create_end) * 1000 if t_start_end > 0 else 0
                t_exec = (t_exec_end - t_start_end) * 1000 if t_exec_end > 0 else 0
                t_cleanup = (t_cleanup_end - t_exec_end) * 1000 if t_cleanup_end > t_exec_end else 0

                logger.info(
                    f"[SIDECAR STATS] tool='{tool_name}' "
                    f"total={t_total:.1f}ms "
                    f"create={t_create:.1f}ms "
                    f"startup={t_startup:.1f}ms "
                    f"exec={t_exec:.1f}ms "
                    f"cleanup={t_cleanup:.1f}ms"
                )

        except Exception as e:
            import traceback

            t_total = (time.perf_counter() - t_start) * 1000
            error_msg = f"Sidecar execution failed: {type(e).__name__}: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            logger.info(
                f"[SIDECAR STATS] tool='{tool_name}' "
                f"total={t_total:.1f}ms "
                f"status=failed"
            )
            return ExecutionResult(
                success=False,
                result=None,
                error=error_msg,
            )

    def health_check(self) -> bool:
        """
        Check if the Podman connection is healthy.

        Returns:
            True if Podman is accessible and functional, False otherwise.
        """
        try:
            client = self._get_client()
            client.ping()
            return True
        except Exception as e:
            logger.error(f"Podman health check failed: {e}")
            return False


class LocalExecutor:
    """
    Executes tool functions directly in the current process.

    This is the fallback executor when sidecar mode is disabled or
    unavailable. It provides the same interface as PodmanSidecarExecutor
    but executes tools in-process without isolation.
    """

    def execute(
        self,
        tool_name: str,
        tool_kwargs: dict[str, Any],
        tool_func: Any,
    ) -> ExecutionResult:
        """
        Execute a tool function directly in the current process.

        Args:
            tool_name: The name of the tool (for logging).
            tool_kwargs: Keyword arguments to pass to the tool function.
            tool_func: The callable tool function to execute.

        Returns:
            An ExecutionResult containing the success status and return value.
        """
        try:
            result = tool_func(**tool_kwargs)
            logger.debug(f"Tool '{tool_name}' executed locally")
            return ExecutionResult(success=True, result=result)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Tool '{tool_name}' execution failed locally: {error_msg}")
            return ExecutionResult(success=False, result=None, error=error_msg)


def run_in_sidecar() -> bool:
    """
    Check if the current process is running inside a sidecar container.

    This is determined by checking for the PIVOT_SIDECAR environment variable,
    which is set by the sidecar entrypoint when running tool executions.

    Returns:
        True if running in a sidecar container, False otherwise.
    """
    return os.getenv("PIVOT_SIDECAR") == "1"


def main() -> int:
    """
    Main entry point for testing the sidecar executor.

    This function is intended for development and testing purposes only.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    executor = PodmanSidecarExecutor()

    if executor.health_check():
        print("Podman connection: OK")
        print(f"Config: {executor.config}")
    else:
        print("Podman connection: FAILED")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
