"""Sandbox service client for delegating execution to sandbox-manager.

The backend does not talk to Podman directly. It calls sandbox-manager over
HTTP so backend can stay non-privileged while sandbox lifecycle remains
isolated in a dedicated service.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from app.config import get_settings


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

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST one JSON request to sandbox-manager and return JSON body."""
        try:
            response = requests.post(
                f"{self._base_url}{path}",
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Sandbox manager request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text.strip()
            raise RuntimeError(
                f"Sandbox manager error ({response.status_code}): {detail}"
            )

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Sandbox manager response is not a JSON object.")
        return data

    def exec(
        self,
        username: str,
        agent_id: int,
        cmd: list[str],
        skills: list[str] | None = None,
    ) -> SandboxExecResult:
        """Execute one non-interactive command inside an agent sandbox."""
        if skills is None:
            skills = []
        data = self._post(
            "/sandboxes/exec",
            {"username": username, "agent_id": agent_id, "cmd": cmd, "skills": skills},
        )
        return SandboxExecResult(
            exit_code=int(data.get("exit_code", -1)),
            stdout=str(data.get("stdout", "")),
            stderr=str(data.get("stderr", "")),
        )

    def create(self, username: str, agent_id: int, skills: list[str] | None = None) -> None:
        """Ensure sandbox exists and is configured with current skill mounts."""
        if skills is None:
            skills = []
        self._post(
            "/sandboxes/create",
            {"username": username, "agent_id": agent_id, "skills": skills},
        )


_sandbox_service: SandboxService | None = None


def get_sandbox_service() -> SandboxService:
    """Return process-wide sandbox service singleton."""
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = SandboxService()
    return _sandbox_service
