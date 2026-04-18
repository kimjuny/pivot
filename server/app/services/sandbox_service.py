"""Sandbox service client for delegating execution to sandbox-manager.

The backend does not talk to Podman directly. It calls sandbox-manager over
HTTP so backend can stay non-privileged while sandbox lifecycle remains
isolated in a dedicated service.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests
from app.config import get_settings


@dataclass(frozen=True)
class SandboxExecResult:
    """Execution result returned by sandbox-manager."""

    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SandboxHttpProxyResult:
    """HTTP proxy result returned by sandbox-manager."""

    status_code: int
    body: bytes
    headers: dict[str, str]
    content_type: str | None


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
        except requests.ReadTimeout as exc:
            raise RuntimeError(
                self._format_timeout_error(
                    path=path,
                    request_timeout=request_timeout,
                )
            ) from exc
        except requests.ConnectTimeout as exc:
            raise RuntimeError(
                self._format_connect_timeout_error(
                    path=path,
                    request_timeout=request_timeout,
                )
            ) from exc
        except requests.ConnectionError as exc:
            raise RuntimeError(self._format_connection_error(path=path)) from exc
        except requests.RequestException as exc:
            raise RuntimeError(
                self._format_generic_request_error(
                    path=path,
                    request_timeout=request_timeout,
                    exc=exc,
                )
            ) from exc

        if response.status_code >= 400:
            detail = response.text.strip()
            raise RuntimeError(
                f"Sandbox manager error ({response.status_code}): {detail}"
            )

        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Sandbox manager response is not a JSON object.")
        return data

    def _operation_label(self, path: str) -> str:
        """Return a human-readable sandbox operation label for one API path."""
        operation_labels = {
            "/sandboxes/exec": "finish a workspace command",
            "/sandboxes/create": "prepare a workspace sandbox",
            "/sandboxes/destroy": "tear down a workspace sandbox",
            "/sandboxes/ws-proxy": "open a workspace preview websocket",
        }
        return operation_labels.get(path, "complete a workspace sandbox request")

    def build_websocket_proxy_url(self) -> str:
        """Return the sandbox-manager websocket proxy URL."""
        parsed = urlparse(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunparse((scheme, parsed.netloc, "/sandboxes/ws-proxy", "", "", ""))

    def build_websocket_proxy_headers(self) -> dict[str, str]:
        """Return auth headers for one sandbox-manager websocket tunnel."""
        return {
            "X-Sandbox-Token": get_settings().SANDBOX_MANAGER_TOKEN,
        }

    def _format_timeout_error(self, *, path: str, request_timeout: int) -> str:
        """Return an actionable timeout message for agent-facing tool errors."""
        operation_label = self._operation_label(path)
        return (
            "Workspace sandbox timed out after "
            f"{request_timeout} seconds while the backend was waiting for "
            f"sandbox-manager to {operation_label}. This does not necessarily "
            "mean the command failed; the sandbox may still be starting, or "
            "the command may still be running. Retry once for read-only "
            "actions like listing, reading, or searching files. For write, "
            "install, or edit actions, do not blindly retry; inspect the "
            "workspace first, or increase this agent's "
            "`sandbox_timeout_seconds` setting if longer runs are expected."
        )

    def _format_connect_timeout_error(
        self,
        *,
        path: str,
        request_timeout: int,
    ) -> str:
        """Return an actionable connect-timeout message."""
        operation_label = self._operation_label(path)
        return (
            "Workspace sandbox service did not respond within "
            f"{request_timeout} seconds while the backend was trying to "
            f"ask sandbox-manager to {operation_label}. This usually means "
            "the sandbox service is unhealthy or still booting. Wait briefly "
            "and retry. If it keeps failing, ask the user to check backend "
            "and sandbox-manager health."
        )

    def _format_connection_error(self, *, path: str) -> str:
        """Return an actionable connection failure message."""
        operation_label = self._operation_label(path)
        return (
            "Workspace sandbox service is unreachable while trying to "
            f"{operation_label}. This is an infrastructure problem, not a "
            "command syntax problem. Ask the user to check backend and "
            "sandbox-manager health before retrying."
        )

    def _format_generic_request_error(
        self,
        *,
        path: str,
        request_timeout: int,
        exc: requests.RequestException,
    ) -> str:
        """Return a fallback agent-facing request failure message."""
        operation_label = self._operation_label(path)
        return (
            "Workspace sandbox request failed while trying to "
            f"{operation_label} (timeout={request_timeout}s): {exc}. "
            "Retry once if the action is read-only. Otherwise inspect the "
            "workspace or ask the user to check sandbox health before retrying."
        )

    def exec(
        self,
        username: str,
        workspace_id: str,
        workspace_backend_path: str,
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
                "workspace_id": workspace_id,
                "workspace_backend_path": workspace_backend_path,
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
        workspace_id: str,
        workspace_backend_path: str,
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
                "workspace_id": workspace_id,
                "workspace_backend_path": workspace_backend_path,
                "skills": skills,
            },
            timeout_seconds=timeout_seconds,
        )

    def destroy(
        self,
        *,
        username: str,
        workspace_id: str,
        workspace_backend_path: str,
        timeout_seconds: int | None = None,
    ) -> None:
        """Destroy one sandbox container bound to the given workspace."""
        self._post(
            "/sandboxes/destroy",
            {
                "username": username,
                "workspace_id": workspace_id,
                "workspace_backend_path": workspace_backend_path,
                "skills": [],
            },
            timeout_seconds=timeout_seconds,
        )

    def proxy_http(
        self,
        *,
        username: str,
        workspace_id: str,
        workspace_backend_path: str,
        skills: list[dict[str, str]] | None = None,
        port: int,
        path: str,
        method: str,
        query_string: str | None = None,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: int | None = None,
        require_existing: bool = False,
        allow_recreate: bool = True,
    ) -> SandboxHttpProxyResult:
        """Proxy one HTTP request through sandbox-manager into a sandbox."""
        request_timeout = timeout_seconds or self._timeout
        payload: dict[str, Any] = {
            "username": username,
            "workspace_id": workspace_id,
            "workspace_backend_path": workspace_backend_path,
            "skills": skills or [],
            "port": port,
            "path": path,
            "method": method,
            "query_string": query_string or "",
            "headers": headers or {},
            "body_base64": (
                base64.b64encode(body).decode("ascii") if body is not None else None
            ),
            "require_existing": require_existing,
            "allow_recreate": allow_recreate,
        }
        try:
            response = requests.post(
                f"{self._base_url}/sandboxes/http-proxy",
                json=payload,
                headers=self._headers,
                timeout=request_timeout,
            )
        except requests.ReadTimeout as exc:
            raise RuntimeError(
                self._format_timeout_error(
                    path="/sandboxes/http-proxy",
                    request_timeout=request_timeout,
                )
            ) from exc
        except requests.ConnectTimeout as exc:
            raise RuntimeError(
                self._format_connect_timeout_error(
                    path="/sandboxes/http-proxy",
                    request_timeout=request_timeout,
                )
            ) from exc
        except requests.ConnectionError as exc:
            raise RuntimeError(
                self._format_connection_error(path="/sandboxes/http-proxy")
            ) from exc
        except requests.RequestException as exc:
            raise RuntimeError(
                self._format_generic_request_error(
                    path="/sandboxes/http-proxy",
                    request_timeout=request_timeout,
                    exc=exc,
                )
            ) from exc

        if response.status_code >= 500:
            detail = response.text.strip()
            raise RuntimeError(
                f"Sandbox manager error ({response.status_code}): {detail}"
            )

        return SandboxHttpProxyResult(
            status_code=response.status_code,
            body=response.content,
            headers=dict(response.headers.items()),
            content_type=response.headers.get("content-type"),
        )


_sandbox_service: SandboxService | None = None


def get_sandbox_service() -> SandboxService:
    """Return process-wide sandbox service singleton."""
    global _sandbox_service
    if _sandbox_service is None:
        _sandbox_service = SandboxService()
    return _sandbox_service
