"""Sandbox service client for delegating execution to sandbox-manager.

The backend does not talk to Podman directly. It calls sandbox-manager over
HTTP so backend can stay non-privileged while sandbox lifecycle remains
isolated in a dedicated service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests
from app.config import get_settings

if TYPE_CHECKING:
    from app.services.workspace_storage_service import WorkspaceMountSpec


@dataclass(frozen=True)
class SandboxExecResult:
    """Execution result returned by sandbox-manager."""

    exit_code: int
    stdout: str
    stderr: str


class SandboxService:
    """HTTP client wrapper for sandbox-manager APIs."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.SANDBOX_MANAGER_URL.rstrip("/")
        self._timeout = settings.SANDBOX_MANAGER_TIMEOUT_SECONDS
        self._headers = {
            "X-Sandbox-Token": settings.SANDBOX_MANAGER_TOKEN,
            "Content-Type": "application/json",
        }

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """POST one JSON request to sandbox-manager and return JSON body."""
        request_timeout = timeout_seconds or self._timeout
        try:
            response = requests.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=self._headers,
                timeout=request_timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Sandbox manager request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = self._error_detail(response)
            raise RuntimeError(
                f"Sandbox manager error ({response.status_code}): {detail}"
            )

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Sandbox manager response is not a JSON object.")
        return data

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        """Return the most useful error detail from one manager HTTP response."""
        with_detail = response.text.strip()
        try:
            payload = response.json()
        except ValueError:
            return with_detail or "Unknown sandbox-manager error."

        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
        return with_detail or "Unknown sandbox-manager error."

    def exec(
        self,
        username: str,
        mount_spec: WorkspaceMountSpec,
        cmd: list[str],
        skills: list[dict[str, str]] | None = None,
        timeout_seconds: int | None = None,
    ) -> SandboxExecResult:
        """Execute one non-interactive command inside a workspace sandbox."""
        if skills is None:
            skills = []
        data = self._post(
            "/sandboxes/exec",
            {
                "username": username,
                "workspace_id": mount_spec.workspace_id,
                "storage_backend": mount_spec.storage_backend,
                "logical_path": mount_spec.logical_path,
                "mount_mode": mount_spec.mount_mode,
                "source_workspace_id": mount_spec.source_workspace_id,
                "cmd": cmd,
                "skills": skills,
            },
            timeout_seconds=timeout_seconds,
        )
        return SandboxExecResult(
            exit_code=int(data.get("exit_code", -1)),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
        )

    def create(
        self,
        username: str,
        mount_spec: WorkspaceMountSpec,
        skills: list[dict[str, str]] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """Ensure sandbox exists and is configured with current skill mounts."""
        if skills is None:
            skills = []
        self._post(
            "/sandboxes/create",
            {
                "username": username,
                "workspace_id": mount_spec.workspace_id,
                "storage_backend": mount_spec.storage_backend,
                "logical_path": mount_spec.logical_path,
                "mount_mode": mount_spec.mount_mode,
                "source_workspace_id": mount_spec.source_workspace_id,
                "skills": skills,
            },
            timeout_seconds=timeout_seconds,
        )

    def destroy(
        self,
        *,
        username: str,
        mount_spec: WorkspaceMountSpec,
        timeout_seconds: int | None = None,
    ) -> None:
        """Destroy one sandbox container bound to the given workspace."""
        self._post(
            "/sandboxes/destroy",
            {
                "username": username,
                "workspace_id": mount_spec.workspace_id,
                "storage_backend": mount_spec.storage_backend,
                "logical_path": mount_spec.logical_path,
                "mount_mode": mount_spec.mount_mode,
                "source_workspace_id": mount_spec.source_workspace_id,
                "skills": [],
            },
            timeout_seconds=timeout_seconds,
        )


_sandbox_service: SandboxService | None = None


def get_sandbox_service() -> SandboxService:
    """Return process-wide sandbox service singleton."""
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = SandboxService()
    return _sandbox_service
