"""Built-in tool for creating one session-scoped web preview endpoint."""

from __future__ import annotations

from app.db.session import managed_session
from app.orchestration.tool import get_current_tool_execution_context, tool
from app.services.preview_endpoint_service import (
    PreviewEndpointRecord,
    PreviewEndpointService,
)
from app.services.workspace_service import WorkspaceService


def _serialize_preview_record(
    *,
    record: PreviewEndpointRecord,
    workspace_logical_root: str,
    service: PreviewEndpointService,
) -> dict[str, object]:
    """Return one tool-facing preview payload."""
    return {
        "preview_id": record.preview_id,
        "session_id": record.session_id,
        "workspace_id": record.workspace_id,
        "workspace_logical_root": workspace_logical_root,
        "title": record.title,
        "port": record.port,
        "path": record.path,
        "has_launch_recipe": bool(record.start_server and record.cwd),
        "proxy_url": service.build_proxy_url(record=record),
        "created_at": record.created_at.isoformat(),
    }


@tool
def create_preview_endpoint(
    preview_name: str,
    start_server: str,
    port: int,
    path: str = "/",
    cwd: str = ".",
) -> dict[str, object]:
    """Create or reconnect one web preview endpoint for the current chat session.

    This tool is intentionally stronger than a plain port registry. It records
    a reusable launch recipe, runs that recipe now, waits for the preview to
    become reachable, and then returns the Pivot-owned preview URL.

    ``start_server`` must be safe to run more than once. The easiest pattern is
    to write an idempotent shell script under ``/workspace`` and call it here.

    The launched preview server must listen on ``0.0.0.0`` inside the sandbox.
    Binding only to ``localhost`` or ``127.0.0.1`` is not reachable through
    Pivot's preview proxy.

    The tool does not expose raw ports to the UI. Instead it creates a
    session-scoped preview endpoint and returns a host-facing proxy URL that
    Pivot can open inside ``workspace-editor`` web view.

    Args:
        preview_name (required, str): Operator-facing preview label shown in the
            surface preview picker.
        start_server (required, str): Idempotent shell command that ensures the
            preview server is running for this workspace.
        port (required, int): Sandbox-local HTTP port to expose.
        path (optional, str): Initial HTTP path under that port. Defaults to
            ``/``.
        cwd (optional, str): Workspace-relative or absolute ``/workspace`` path
            used before running ``start_server``. Defaults to ``.``.

    Returns:
        Structured preview metadata plus a UI intent that can open
        ``workspace-editor`` in web view.

    Raises:
        RuntimeError: If tool execution context is missing or not session-backed.
        ValueError: If preview validation fails.

    Example:
        Use an idempotent script that can be replayed later:

        ``create_preview_endpoint(
            preview_name="Landing Page",
            start_server="bash /workspace/.pivot/previews/landing-page.sh",
            port=3000,
            cwd="apps/landing-page",
        )``
    """
    context = get_current_tool_execution_context()
    if context is None:
        raise RuntimeError("Tool execution context is missing.")
    if not context.session_id:
        raise RuntimeError(
            "create_preview_endpoint requires a session-backed chat task."
        )

    normalized_preview_name = preview_name.strip()
    if normalized_preview_name == "":
        raise ValueError("preview_name must be a non-empty string.")

    normalized_start_server = start_server.strip()
    if normalized_start_server == "":
        raise ValueError("start_server must be a non-empty shell command string.")

    with managed_session() as db:
        service = PreviewEndpointService(db)
        record = service.create_preview_endpoint(
            username=context.username,
            session_id=context.session_id,
            port=port,
            path=path,
            title=normalized_preview_name,
            cwd=cwd,
            start_server=normalized_start_server,
            skills=context.allowed_skills,
        )
        record = service.connect_preview_endpoint(
            preview_id=record.preview_id,
            username=context.username,
            timeout_seconds=context.sandbox_timeout_seconds,
        )
        preview_records = service.list_preview_endpoints(
            username=context.username,
            session_id=context.session_id,
        )
        workspace = WorkspaceService(db).get_workspace(record.workspace_id)
        workspace_logical_root = (
            WorkspaceService(db).get_workspace_logical_root(workspace)
            if workspace is not None
            else "/workspace"
        )
        serialized_preview = _serialize_preview_record(
            record=record,
            workspace_logical_root=workspace_logical_root,
            service=service,
        )
        serialized_previews = [
            _serialize_preview_record(
                record=preview_record,
                workspace_logical_root=workspace_logical_root,
                service=service,
            )
            for preview_record in preview_records
        ]

    return {
        **serialized_preview,
        "available_previews": serialized_previews,
        "active_preview_id": record.preview_id,
        "ui_intent": {
            "type": "open_workspace_web_preview",
            "surface_key": "workspace-editor",
            "view": "web",
            "preview": serialized_preview,
            "available_previews": serialized_previews,
            "active_preview_id": record.preview_id,
        },
    }
