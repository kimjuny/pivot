"""Built-in tool for creating one session-scoped web preview endpoint."""

from __future__ import annotations

from typing import Annotated

from app.db.session import managed_session
from app.orchestration.tool import Param, get_current_tool_execution_context, tool
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
    result = {
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

    # If running in background mode, include log file information
    if record.run_in_background and record.start_server:
        log_file = f"/workspace/.tmp/preview-{record.preview_id}.log"
        result.update(
            {
                "detached": True,
                "log_file": log_file,
            }
        )
    else:
        result["detached"] = False

    return result


@tool(
    description=(
        "Create or reconnect a web preview for this chat session. "
        "The preview server must bind 0.0.0.0 inside the sandbox; "
        "localhost and 127.0.0.1 are not reachable through the proxy."
    ),
)
def create_preview_endpoint(
    preview_name: Annotated[str, Param("Label shown in the preview picker.")],
    start_server: Annotated[
        str,
        Param(
            "Shell command to start the preview server. "
            "e.g. 'npm run dev -- --host 0.0.0.0' or 'python -m http.server 8000 --bind 0.0.0.0'."
        ),
    ],
    port: Annotated[int, Param("Sandbox-local HTTP port to expose.")],
    path: Annotated[str, Param("Initial HTTP path.")] = "/",
    cwd: Annotated[
        str,
        Param("Workspace-relative or absolute /workspace directory for start_server."),
    ] = ".",
    run_in_background: Annotated[
        bool,
        Param(
            "If true, automatically detach the server process so it runs "
            "in the background and the command returns immediately. "
            "Set to false only if start_server is a quick setup script that exits on its own."
        ),
    ] = True,
) -> dict[str, object]:
    """Create/reconnect a web preview for this chat session.

    Args:
        preview_name: Label for the preview.
        start_server: Shell command to start the server.
        port: HTTP port.
        path: Initial path.
        cwd: Working directory for start_server.
        run_in_background: Whether to detach the server process.

    Returns:
        Preview metadata, proxy URL, log file path, and UI intent.

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
            user_id=context.user_id,
            session_id=context.session_id,
            port=port,
            path=path,
            title=normalized_preview_name,
            cwd=cwd,
            start_server=normalized_start_server,
            skills=context.allowed_skills,
            run_in_background=run_in_background,
        )
        record = service.connect_preview_endpoint(
            preview_id=record.preview_id,
            user_id=context.user_id,
            timeout_seconds=context.sandbox_timeout_seconds,
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

    return {
        "preview_id": serialized_preview["preview_id"],
        "title": serialized_preview["title"],
        "port": serialized_preview["port"],
        "path": serialized_preview["path"],
        "proxy_url": serialized_preview["proxy_url"],
        "pivot_action": {
            "type": "open_workspace_web_preview",
            "category": "notify",
            "payload": {
                "surface_key": "workspace-editor",
                "view": "web",
                "preview": serialized_preview,
                "active_preview_id": record.preview_id,
            },
        },
    }
