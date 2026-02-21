"""Podman-based sidecar execution for registered tools."""

import json
import logging
import os
import subprocess
import stat
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PodmanSidecarConfig:
    podman_host: str
    timeout_seconds: int
    network: str | None
    image: str | None


class PodmanSidecarExecutor:
    def __init__(self, config: PodmanSidecarConfig) -> None:
        self._config = config

    def execute(
        self,
        tool_name: str,
        tool_kwargs: dict[str, Any],
        pivot_context: dict[str, Any] | None,
    ) -> Any:
        start_ts = perf_counter()
        container_ref = _current_container_ref()
        _validate_podman_host(self._config.podman_host)
        podman_base = _podman_base_cmd(self._config.podman_host)
        resolve_start_ts = perf_counter()
        if self._config.image:
            image = self._config.image
        else:
            image = _resolve_current_image(
                podman_base=podman_base,
                container_ref=container_ref,
            )
        resolve_image_ms = (perf_counter() - resolve_start_ts) * 1000

        create_cmd = [
            *podman_base,
            "create",
            "--pull=never",
            "-i",
            "--userns",
            "keep-id",
            "--volumes-from",
            container_ref,
            "--workdir",
            "/app",
            "--label",
            "pivot.sidecar=true",
            "--label",
            f"pivot.tool_name={tool_name}",
            "--env",
            "PYTHONPATH=server",
            "--env",
            "TOOL_EXECUTION_MODE=local",
            "--env",
            "PIVOT_SIDECAR_DIAGNOSTICS=1",
        ]
        if self._config.network:
            create_cmd.extend(["--network", self._config.network])

        create_cmd.extend(
            [
                image,
                "poetry",
                "run",
                "python",
                "-m",
                "app.orchestration.tool.sidecar_entrypoint",
                "--tool-name",
                tool_name,
            ]
        )

        logger.info(
            "sidecar_start tool=%s backend_container=%s image=%s podman_host=%s resolve_image_ms=%.2f context=%s",
            tool_name,
            container_ref,
            image,
            self._config.podman_host,
            resolve_image_ms,
            pivot_context,
        )

        create_start_ts = perf_counter()
        create_completed = subprocess.run(
            create_cmd,
            capture_output=True,
            timeout=self._config.timeout_seconds,
            check=False,
        )
        create_ms = (perf_counter() - create_start_ts) * 1000

        container_id = create_completed.stdout.decode("utf-8", errors="replace").strip()
        create_stderr = create_completed.stderr.decode("utf-8", errors="replace").strip()
        if create_completed.returncode != 0 or not container_id:
            raise RuntimeError(
                _format_sidecar_error(
                    create_stderr,
                    "Failed to create sidecar container.",
                )
            )

        logger.info(
            "sidecar_container_created tool=%s container_id=%s create_ms=%.2f",
            tool_name,
            container_id,
            create_ms,
        )

        start_cmd = [*podman_base, "start", "-a", "-i", container_id]
        start_attach_ts = perf_counter()
        completed: subprocess.CompletedProcess[bytes]
        try:
            completed = subprocess.run(
                start_cmd,
                input=json.dumps(tool_kwargs, ensure_ascii=False).encode("utf-8"),
                capture_output=True,
                timeout=self._config.timeout_seconds,
                check=False,
            )
        finally:
            rm_start_ts = perf_counter()
            rm_cmd = [*podman_base, "rm", "-f", container_id]
            rm_completed = subprocess.run(
                rm_cmd,
                capture_output=True,
                timeout=self._config.timeout_seconds,
                check=False,
            )
            rm_ms = (perf_counter() - rm_start_ts) * 1000
            if rm_completed.returncode == 0:
                logger.info(
                    "sidecar_container_removed tool=%s container_id=%s rm_ms=%.2f",
                    tool_name,
                    container_id,
                    rm_ms,
                )

        run_ms = (perf_counter() - start_attach_ts) * 1000

        stdout_text = completed.stdout.decode("utf-8", errors="replace").strip()
        stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()

        if not stdout_text:
            if completed.returncode == 0:
                return None
            raise RuntimeError(_format_sidecar_error(stderr_text, None))

        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                _format_sidecar_error(stderr_text, f"Invalid JSON from sidecar: {exc}")
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(_format_sidecar_error(stderr_text, "Invalid payload"))

        diagnostics = payload.get("diagnostics")
        if isinstance(diagnostics, dict):
            logger.info(
                "sidecar_diagnostics tool=%s sidecar_hostname=%s sidecar_pid=%s sidecar_thread_id=%s timings=%s",
                tool_name,
                diagnostics.get("hostname"),
                diagnostics.get("pid"),
                diagnostics.get("thread_id"),
                diagnostics.get("timings_ms"),
            )

        if completed.returncode != 0 or payload.get("success") is not True:
            error_msg = payload.get("error")
            if not isinstance(error_msg, str) or not error_msg:
                error_msg = "Tool execution failed in sidecar."
            raise RuntimeError(_format_sidecar_error(stderr_text, error_msg))

        total_ms = (perf_counter() - start_ts) * 1000
        logger.info(
            "sidecar_end tool=%s container_id=%s returncode=%s run_ms=%.2f total_ms=%.2f",
            tool_name,
            container_id,
            completed.returncode,
            run_ms,
            total_ms,
        )

        return payload.get("result")


def _podman_base_cmd(podman_host: str) -> list[str]:
    if podman_host:
        return ["podman", "--url", podman_host]
    return ["podman"]


def _validate_podman_host(podman_host: str) -> None:
    if not podman_host:
        return
    if not podman_host.startswith("unix://"):
        return
    sock_path = podman_host.removeprefix("unix://")
    if not sock_path:
        return
    sock = Path(sock_path)
    if not sock.exists():
        raise RuntimeError(
            "Podman sidecar execution is enabled but the Podman socket is not "
            f"available at {podman_host}. Ensure the socket is mounted into the "
            "backend container, or configure PODMAN_HOST to a reachable endpoint."
        )
    try:
        mode = sock.stat().st_mode
    except OSError:
        return
    if not stat.S_ISSOCK(mode):
        raise RuntimeError(
            "Podman sidecar execution is enabled but the Podman socket path is not "
            f"a unix socket: {podman_host}. Check your bind-mount source path."
        )


def _current_container_ref() -> str:
    env_hostname = os.getenv("HOSTNAME")
    if env_hostname:
        return env_hostname
    try:
        return Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError as err:
        raise RuntimeError(
            "Cannot determine current container reference for sidecar execution."
        ) from err


def _resolve_current_image(podman_base: list[str], container_ref: str) -> str:
    inspect_cmd = [*podman_base, "inspect", container_ref]
    completed = subprocess.run(
        inspect_cmd,
        capture_output=True,
        timeout=10,
        check=False,
    )
    stdout_text = completed.stdout.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0 or not stdout_text:
        stderr_text = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            _format_sidecar_error(
                stderr_text,
                "Failed to resolve current container image for sidecar execution.",
            )
        )

    parsed = json.loads(stdout_text)
    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError("Unexpected podman inspect output.")

    inspect0 = parsed[0]
    if not isinstance(inspect0, dict):
        raise RuntimeError("Unexpected podman inspect output.")

    image = inspect0.get("ImageName") or inspect0.get("Image")
    if not isinstance(image, str) or not image:
        raise RuntimeError("Current container image is missing in podman inspect.")

    return image


def _format_sidecar_error(stderr_text: str, message: str | None) -> str:
    parts: list[str] = []
    if message:
        parts.append(message)
    if stderr_text:
        parts.append(f"podman stderr: {stderr_text}")
    return " | ".join(parts) if parts else "Sidecar execution failed."
