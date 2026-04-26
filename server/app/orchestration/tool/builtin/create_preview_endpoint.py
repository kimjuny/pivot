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
    """Create/reconnect a web preview for this chat session.

    ``start_server`` is replayed now and on reconnect, so it must be idempotent,
    start the server in the background, and return quickly. Prefer a small
    script or detached command such as
    ``nohup npm run dev -- --host 0.0.0.0 > /tmp/preview.log 2>&1 &``.

    The preview server must bind ``0.0.0.0`` inside the sandbox; ``localhost``
    and ``127.0.0.1`` are not reachable through the proxy.

    Args:
        preview_name (required, str): Label shown in the preview picker.
        start_server (required, str): Idempotent detached shell command that
            ensures the server is running and exits promptly.
        port (required, int): Sandbox-local HTTP port to expose.
        path (optional, str): Initial HTTP path. Defaults to ``/``.
        cwd (optional, str): Workspace-relative or absolute ``/workspace`` directory for
            ``start_server``. Defaults to ``.``.

    Returns:
        Preview metadata, proxy URL, and UI intent.

    Raises:
        RuntimeError: If tool execution context is missing or not session-backed.
        ValueError: If preview validation fails.
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
