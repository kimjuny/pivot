"""API endpoints for development chat surfaces and workspace file access."""

from __future__ import annotations

import json
import re
from asyncio import FIRST_COMPLETED, create_task, wait
from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from app.api.auth import get_current_user, resolve_user_from_access_token
from app.api.dependencies import get_db
from app.schemas.chat_surface import (
    CreateDevSurfaceSessionRequest,
    CreateInstalledSurfaceSessionRequest,
    CreatePreviewEndpointRequest,
    DevSurfaceBootstrapResponse,
    DevSurfaceSessionResponse,
    InstalledSurfaceBootstrapResponse,
    InstalledSurfaceSessionResponse,
    PreviewEndpointResponse,
    ReconnectPreviewEndpointResponse,
    SurfaceFilesApiResponse,
    SurfaceThemeResponse,
    WorkspaceBinaryFileResponse,
    WorkspaceDirectoryEntryResponse,
    WorkspaceDirectoryResponse,
    WorkspaceFileContentResponse,
    WorkspaceFileTreeEntryResponse,
    WorkspaceFileTreeResponse,
    WorkspaceTextFileResponse,
    WriteWorkspaceFileRequest,
)
from app.services.preview_endpoint_service import (
    PreviewEndpointNotFoundError,
    PreviewEndpointPermissionError,
    PreviewEndpointRecord,
    PreviewEndpointService,
    PreviewEndpointValidationError,
)
from app.services.sandbox_service import get_sandbox_service
from app.services.surface_runtime_service import (
    SurfaceRuntimeNotFoundError,
    SurfaceRuntimeService,
)
from app.services.surface_session_service import (
    SurfaceSessionNotFoundError,
    SurfaceSessionPermissionError,
    SurfaceSessionRecord,
    SurfaceSessionService,
    SurfaceSessionValidationError,
)
from app.services.surface_token_service import (
    SurfaceTokenService,
    SurfaceTokenValidationError,
)
from app.services.workspace_file_service import (
    WorkspaceFileNotFoundError,
    WorkspaceFilePermissionError,
    WorkspaceFileService,
    WorkspaceFileTreeEntry,
    WorkspaceFileValidationError,
)
from app.services.workspace_service import WorkspaceService
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request as FastAPIRequest,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from websockets import connect as websocket_connect
from websockets.exceptions import ConnectionClosed

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlmodel import Session as DBSession
    from websockets.typing import Subprotocol

router = APIRouter()

_DEV_SURFACE_HOST_ALIASES = (
    "host.containers.internal",
    "host.docker.internal",
)


@dataclass(frozen=True)
class _UpstreamTarget:
    """One concrete upstream URL candidate plus the host header to preserve."""

    url: str
    host_header: str | None


@router.post(
    "/chat-surfaces/dev-sessions",
    response_model=DevSurfaceSessionResponse,
    status_code=201,
)
def create_dev_surface_session(
    request: CreateDevSurfaceSessionRequest,
    db: DBSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> DevSurfaceSessionResponse:
    """Create one development-mode chat surface session for the current user."""
    service = SurfaceSessionService(db)
    try:
        record = service.create_dev_surface_session(
            username=current_user.username,
            session_id=request.session_id,
            surface_key=request.surface_key,
            dev_server_url=request.dev_server_url,
            display_name=request.display_name,
        )
    except SurfaceSessionNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except SurfaceSessionValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    surface_token = SurfaceTokenService.create_surface_token(
        surface_session_id=record.surface_session_id,
        username=record.username,
    )
    bootstrap = _serialize_bootstrap(
        service.build_bootstrap(record=record),
        surface_token=surface_token,
    )
    return DevSurfaceSessionResponse(
        surface_session_id=record.surface_session_id,
        surface_token=surface_token,
        surface_key=record.surface_key,
        display_name=record.display_name,
        agent_id=record.agent_id,
        session_id=record.session_id,
        workspace_id=record.workspace_id,
        workspace_logical_root=bootstrap.workspace_logical_root,
        dev_server_url=bootstrap.dev_server_url,
        created_at=record.created_at.replace(tzinfo=UTC).isoformat(),
        bootstrap=bootstrap,
    )


@router.post(
    "/chat-surfaces/installed-sessions",
    response_model=InstalledSurfaceSessionResponse,
    status_code=201,
)
def create_installed_surface_session(
    request: CreateInstalledSurfaceSessionRequest,
    db: DBSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> InstalledSurfaceSessionResponse:
    """Create one installed chat surface session for the current user."""
    service = SurfaceSessionService(db)
    try:
        record = service.create_installed_surface_session(
            username=current_user.username,
            session_id=request.session_id,
            extension_installation_id=request.extension_installation_id,
            surface_key=request.surface_key,
        )
    except SurfaceSessionNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except SurfaceSessionValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    surface_token = SurfaceTokenService.create_surface_token(
        surface_session_id=record.surface_session_id,
        username=record.username,
    )
    bootstrap = _serialize_installed_bootstrap(
        service.build_bootstrap(record=record),
        surface_token=surface_token,
    )
    return InstalledSurfaceSessionResponse(
        surface_session_id=record.surface_session_id,
        surface_token=surface_token,
        surface_key=record.surface_key,
        display_name=record.display_name,
        package_id=bootstrap.package_id,
        extension_installation_id=bootstrap.extension_installation_id,
        agent_id=record.agent_id,
        session_id=record.session_id,
        workspace_id=record.workspace_id,
        workspace_logical_root=bootstrap.workspace_logical_root,
        runtime_url=bootstrap.runtime_url,
        created_at=record.created_at.replace(tzinfo=UTC).isoformat(),
        bootstrap=bootstrap,
    )


@router.post(
    "/chat-previews",
    response_model=PreviewEndpointResponse,
    status_code=201,
)
def create_preview_endpoint(
    request: CreatePreviewEndpointRequest,
    db: DBSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> PreviewEndpointResponse:
    """Create one session-scoped preview endpoint for the current user."""
    service = PreviewEndpointService(db)
    try:
        record = service.create_preview_endpoint(
            username=current_user.username,
            session_id=request.session_id,
            port=request.port,
            path=request.path,
            title=request.preview_name,
            cwd=request.cwd,
            start_server=request.start_server,
        )
        record = service.connect_preview_endpoint(
            preview_id=record.preview_id,
            username=current_user.username,
        )
    except PreviewEndpointNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PreviewEndpointPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except PreviewEndpointValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    workspace = WorkspaceService(db).get_workspace(record.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    return _serialize_preview_record(
        record=record,
        workspace_logical_root=WorkspaceService(db).get_workspace_logical_root(workspace),
        service=service,
    )


@router.get(
    "/chat-previews",
    response_model=list[PreviewEndpointResponse],
)
def list_preview_endpoints(
    session_id: str,
    db: DBSession = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> list[PreviewEndpointResponse]:
    """List all session-scoped preview endpoints for one owned chat session."""
    service = PreviewEndpointService(db)
    try:
        records = service.list_preview_endpoints(
            username=current_user.username,
            session_id=session_id,
        )
    except PreviewEndpointNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PreviewEndpointPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    workspace_service = WorkspaceService(db)
    serialized_records: list[PreviewEndpointResponse] = []
    for record in records:
        workspace = workspace_service.get_workspace(record.workspace_id)
        workspace_logical_root = (
            workspace_service.get_workspace_logical_root(workspace)
            if workspace is not None
            else "/workspace"
        )
        serialized_records.append(
            _serialize_preview_record(
                record=record,
                workspace_logical_root=workspace_logical_root,
                service=service,
            )
        )

    return serialized_records


@router.post(
    "/chat-surfaces/sessions/{surface_session_id}/previews/{preview_id}/connect",
    response_model=ReconnectPreviewEndpointResponse,
)
def reconnect_surface_preview(
    surface_session_id: str,
    preview_id: str,
    request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> ReconnectPreviewEndpointResponse:
    """Reconnect one preview endpoint for an authenticated surface runtime."""
    surface_record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = PreviewEndpointService(db)
    try:
        preview_record = service.get_preview_endpoint(
            preview_id=preview_id,
            username=surface_record.username,
        )
        if preview_record.session_id != surface_record.session_id:
            if preview_record.agent_id != surface_record.agent_id:
                raise HTTPException(
                    status_code=403,
                    detail="Preview endpoint does not belong to the active surface agent.",
                )
            preview_record = service.create_preview_endpoint_from_existing(
                source_record=preview_record,
                username=surface_record.username,
                session_id=surface_record.session_id,
            )
        preview_record = service.connect_preview_endpoint(
            preview_id=preview_record.preview_id,
            username=surface_record.username,
        )
        preview_records = service.list_preview_endpoints(
            username=surface_record.username,
            session_id=surface_record.session_id,
        )
    except PreviewEndpointNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PreviewEndpointPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except PreviewEndpointValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    workspace = WorkspaceService(db).get_workspace(surface_record.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    workspace_logical_root = WorkspaceService(db).get_workspace_logical_root(workspace)
    return ReconnectPreviewEndpointResponse(
        preview=_serialize_preview_record(
            record=preview_record,
            workspace_logical_root=workspace_logical_root,
            service=service,
        ),
        available_previews=[
            _serialize_preview_record(
                record=item,
                workspace_logical_root=workspace_logical_root,
                service=service,
            )
            for item in preview_records
        ],
        active_preview_id=preview_record.preview_id,
    )


@router.get(
    "/chat-surfaces/dev-sessions/{surface_session_id}/bootstrap",
    response_model=DevSurfaceBootstrapResponse,
)
def get_dev_surface_bootstrap(
    surface_session_id: str,
    request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> DevSurfaceBootstrapResponse:
    """Return the latest bootstrap payload for one owned surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = SurfaceSessionService(db)
    surface_token = SurfaceTokenService.create_surface_token(
        surface_session_id=record.surface_session_id,
        username=record.username,
    )
    return _serialize_bootstrap(
        service.build_bootstrap(record=record),
        surface_token=surface_token,
        theme=_resolve_surface_theme(request=request),
    )


@router.get(
    "/chat-surfaces/installed-sessions/{surface_session_id}/bootstrap",
    response_model=InstalledSurfaceBootstrapResponse,
)
def get_installed_surface_bootstrap(
    surface_session_id: str,
    request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> InstalledSurfaceBootstrapResponse:
    """Return the latest bootstrap payload for one owned installed surface."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = SurfaceSessionService(db)
    surface_token = SurfaceTokenService.create_surface_token(
        surface_session_id=record.surface_session_id,
        username=record.username,
    )
    return _serialize_installed_bootstrap(
        service.build_bootstrap(record=record),
        surface_token=surface_token,
        theme=_resolve_surface_theme(request=request),
    )


@router.get(
    "/chat-surfaces/dev-sessions/{surface_session_id}/files/directory",
    response_model=WorkspaceDirectoryResponse,
)
def list_dev_surface_workspace_directory(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str | None = Query(default=None),
    db: DBSession = Depends(get_db),
) -> WorkspaceDirectoryResponse:
    """List direct children visible to one owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        entries = service.list_directory(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceDirectoryResponse(
        root_path=path or ".",
        entries=[_serialize_directory_entry(entry) for entry in entries],
    )


@router.get(
    "/chat-surfaces/dev-sessions/{surface_session_id}/files/text",
    response_model=WorkspaceTextFileResponse,
)
def read_dev_surface_workspace_text_file(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceTextFileResponse:
    """Read one UTF-8 workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        content = service.read_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except UnicodeDecodeError as err:
        raise HTTPException(
            status_code=400,
            detail="Workspace file is not valid UTF-8 text.",
        ) from err
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceTextFileResponse(path=path, content=content)


@router.put("/chat-surfaces/dev-sessions/{surface_session_id}/files/text", status_code=204)
def write_dev_surface_workspace_text_file(
    surface_session_id: str,
    request: WriteWorkspaceFileRequest,
    http_request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> Response:
    """Persist one UTF-8 workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        service.write_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=request.path,
            content=request.content,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(status_code=204)


@router.get("/chat-surfaces/dev-sessions/{surface_session_id}/files/blob")
def read_dev_surface_workspace_blob(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> Response:
    """Return one binary workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        blob = service.read_binary_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(
        content=blob.content,
        media_type=blob.mime_type,
        headers={"Content-Length": str(blob.size_bytes)},
    )


@router.post(
    "/chat-surfaces/dev-sessions/{surface_session_id}/files/blob",
    response_model=WorkspaceBinaryFileResponse,
    status_code=201,
)
async def write_dev_surface_workspace_blob(
    surface_session_id: str,
    http_request: FastAPIRequest,
    path: str = Form(...),
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceBinaryFileResponse:
    """Persist one binary workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        result = service.write_binary_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
            content=await file.read(),
            mime_type=file.content_type,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceBinaryFileResponse(
        path=result.path,
        mime_type=result.mime_type,
        size_bytes=result.size_bytes,
    )


@router.get(
    "/chat-surfaces/dev-sessions/{surface_session_id}/files/tree",
    response_model=WorkspaceFileTreeResponse,
)
def list_dev_surface_workspace_tree(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str | None = Query(default=None),
    db: DBSession = Depends(get_db),
) -> WorkspaceFileTreeResponse:
    """List workspace files visible to one owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        entries = service.list_tree(
            workspace_id=record.workspace_id,
            username=record.username,
            root_path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceFileTreeResponse(
        root_path=path or ".",
        entries=[_serialize_tree_entry(entry) for entry in entries],
    )


@router.get(
    "/chat-surfaces/dev-sessions/{surface_session_id}/files/content",
    response_model=WorkspaceFileContentResponse,
)
def read_dev_surface_workspace_file(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceFileContentResponse:
    """Read one previewable workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        file_payload = service.read_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return WorkspaceFileContentResponse(
        path=path,
        kind=file_payload.kind,
        content=file_payload.content,
        encoding=file_payload.encoding,
        mime_type=file_payload.mime_type,
        data_base64=file_payload.data_base64,
    )


@router.put("/chat-surfaces/dev-sessions/{surface_session_id}/files/content", status_code=204)
def write_dev_surface_workspace_file(
    surface_session_id: str,
    request: WriteWorkspaceFileRequest,
    http_request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> Response:
    """Persist one UTF-8 workspace file for an owned development surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        service.write_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=request.path,
            content=request.content,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(status_code=204)


@router.get(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/directory",
    response_model=WorkspaceDirectoryResponse,
)
def list_installed_surface_workspace_directory(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str | None = Query(default=None),
    db: DBSession = Depends(get_db),
) -> WorkspaceDirectoryResponse:
    """List direct children visible to one owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        entries = service.list_directory(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceDirectoryResponse(
        root_path=path or ".",
        entries=[_serialize_directory_entry(entry) for entry in entries],
    )


@router.get(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/text",
    response_model=WorkspaceTextFileResponse,
)
def read_installed_surface_workspace_text_file(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceTextFileResponse:
    """Read one UTF-8 workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        content = service.read_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except UnicodeDecodeError as err:
        raise HTTPException(
            status_code=400,
            detail="Workspace file is not valid UTF-8 text.",
        ) from err
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceTextFileResponse(path=path, content=content)


@router.put(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/text",
    status_code=204,
)
def write_installed_surface_workspace_text_file(
    surface_session_id: str,
    request: WriteWorkspaceFileRequest,
    http_request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> Response:
    """Persist one UTF-8 workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        service.write_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=request.path,
            content=request.content,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(status_code=204)


@router.get("/chat-surfaces/installed-sessions/{surface_session_id}/files/blob")
def read_installed_surface_workspace_blob(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> Response:
    """Return one binary workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        blob = service.read_binary_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(
        content=blob.content,
        media_type=blob.mime_type,
        headers={"Content-Length": str(blob.size_bytes)},
    )


@router.post(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/blob",
    response_model=WorkspaceBinaryFileResponse,
    status_code=201,
)
async def write_installed_surface_workspace_blob(
    surface_session_id: str,
    http_request: FastAPIRequest,
    path: str = Form(...),
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceBinaryFileResponse:
    """Persist one binary workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        result = service.write_binary_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
            content=await file.read(),
            mime_type=file.content_type,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceBinaryFileResponse(
        path=result.path,
        mime_type=result.mime_type,
        size_bytes=result.size_bytes,
    )


@router.get(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/tree",
    response_model=WorkspaceFileTreeResponse,
)
def list_installed_surface_workspace_tree(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str | None = Query(default=None),
    db: DBSession = Depends(get_db),
) -> WorkspaceFileTreeResponse:
    """List workspace files visible to one owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        entries = service.list_tree(
            workspace_id=record.workspace_id,
            username=record.username,
            root_path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return WorkspaceFileTreeResponse(
        root_path=path or ".",
        entries=[_serialize_tree_entry(entry) for entry in entries],
    )


@router.get(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/content",
    response_model=WorkspaceFileContentResponse,
)
def read_installed_surface_workspace_file(
    surface_session_id: str,
    request: FastAPIRequest,
    path: str = Query(...),
    db: DBSession = Depends(get_db),
) -> WorkspaceFileContentResponse:
    """Read one previewable workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        file_payload = service.read_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=path,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return WorkspaceFileContentResponse(
        path=path,
        kind=file_payload.kind,
        content=file_payload.content,
        encoding=file_payload.encoding,
        mime_type=file_payload.mime_type,
        data_base64=file_payload.data_base64,
    )


@router.put(
    "/chat-surfaces/installed-sessions/{surface_session_id}/files/content",
    status_code=204,
)
def write_installed_surface_workspace_file(
    surface_session_id: str,
    request: WriteWorkspaceFileRequest,
    http_request: FastAPIRequest,
    db: DBSession = Depends(get_db),
) -> Response:
    """Persist one UTF-8 workspace file for an owned installed surface session."""
    record = _authenticate_surface_request(
        db=db,
        request=http_request,
        surface_session_id=surface_session_id,
    )
    service = WorkspaceFileService(db)
    try:
        service.write_text_file(
            workspace_id=record.workspace_id,
            username=record.username,
            path=request.path,
            content=request.content,
        )
    except WorkspaceFileNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except WorkspaceFilePermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except WorkspaceFileValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return Response(status_code=204)


@router.api_route(
    "/chat-previews/{preview_id}/proxy",
    methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
)
@router.api_route(
    "/chat-previews/{preview_id}/proxy/",
    methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
)
@router.api_route(
    "/chat-previews/{preview_id}/proxy/{proxy_path:path}",
    methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
)
async def proxy_chat_preview(
    preview_id: str,
    request: FastAPIRequest,
    proxy_path: str = "",
    db: DBSession = Depends(get_db),
) -> Response:
    """Proxy one session-scoped preview request through the sandbox runtime."""
    record = _authenticate_preview_request(
        db=db,
        request=request,
        preview_id=preview_id,
    )
    workspace = WorkspaceService(db).get_workspace(record.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    upstream_path = f"/{proxy_path.lstrip('/')}" if proxy_path else record.path
    forwarded_query_items = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "surface_token"
    ]

    try:
        proxy_result = get_sandbox_service().proxy_http(
            username=record.username,
            workspace_id=record.workspace_id,
            workspace_backend_path=WorkspaceService(db).get_workspace_backend_path(
                workspace
            ),
            skills=list(record.allowed_skills),
            port=record.port,
            path=upstream_path,
            method=request.method,
            query_string=urlencode(forwarded_query_items),
            headers=_extract_preview_request_headers(request=request),
            body=await request.body(),
            require_existing=True,
            allow_recreate=False,
        )
    except RuntimeError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err

    response_headers = _extract_proxy_response_headers(proxy_result.headers)
    if _is_html_response(
        content_type=proxy_result.content_type or "",
        payload=proxy_result.body,
    ):
        rewritten_html = _inject_preview_runtime_script(
            html=proxy_result.body.decode("utf-8"),
            preview_id=record.preview_id,
        )
        response_headers["Content-Type"] = "text/html; charset=utf-8"
        response = Response(
            content=rewritten_html.encode("utf-8"),
            status_code=proxy_result.status_code,
            headers=response_headers,
        )
        request_surface_token = _extract_surface_token(request=request)
        if request_surface_token:
            response.set_cookie(
                key=_SURFACE_ACCESS_COOKIE_NAME,
                value=request_surface_token,
                httponly=True,
                samesite="lax",
                path=_build_preview_path_scope(preview_id=record.preview_id),
            )
        return response

    if _is_javascript_response(
        content_type=proxy_result.content_type or "",
        proxy_path=proxy_path,
    ):
        rewritten_module = _rewrite_root_relative_js_specifiers(
            source=proxy_result.body.decode("utf-8"),
            proxy_base_path=_build_preview_proxy_base_path(preview_id=record.preview_id),
        )
        response_headers["Content-Type"] = "application/javascript; charset=utf-8"
        return Response(
            content=rewritten_module.encode("utf-8"),
            status_code=proxy_result.status_code,
            headers=response_headers,
        )

    return Response(
        content=proxy_result.body,
        status_code=proxy_result.status_code,
        headers=response_headers,
        media_type=proxy_result.content_type or None,
    )


@router.websocket("/chat-previews/{preview_id}/ws")
@router.websocket("/chat-previews/{preview_id}/ws/")
@router.websocket("/chat-previews/{preview_id}/ws/{proxy_path:path}")
async def proxy_chat_preview_websocket(
    websocket: WebSocket,
    preview_id: str,
    proxy_path: str = "",
    db: DBSession = Depends(get_db),
) -> None:
    """Tunnel one session-scoped preview websocket through sandbox-manager."""
    record = _authenticate_preview_websocket(
        db=db,
        websocket=websocket,
        preview_id=preview_id,
    )
    workspace = WorkspaceService(db).get_workspace(record.workspace_id)
    if workspace is None:
        await websocket.close(code=1011, reason="Workspace not found.")
        return

    upstream_path = f"/{proxy_path.lstrip('/')}" if proxy_path else record.path
    forwarded_query_items = [
        (key, value)
        for key, value in websocket.query_params.multi_items()
        if key != "surface_token"
    ]
    requested_protocol = websocket.headers.get("sec-websocket-protocol")
    sandbox_service = get_sandbox_service()

    try:
        manager_connection = websocket_connect(
            sandbox_service.build_websocket_proxy_url(),
            additional_headers=sandbox_service.build_websocket_proxy_headers(),
        )
        async with manager_connection as manager_websocket:
            await manager_websocket.send(
                json.dumps(
                    {
                        "username": record.username,
                        "workspace_id": record.workspace_id,
                        "workspace_backend_path": WorkspaceService(
                            db
                        ).get_workspace_backend_path(workspace),
                        "skills": list(record.allowed_skills),
                        "port": record.port,
                        "path": upstream_path,
                        "query_string": urlencode(forwarded_query_items),
                        "headers": _extract_preview_websocket_headers(
                            websocket=websocket
                        ),
                        "subprotocol": requested_protocol,
                        "require_existing": True,
                        "allow_recreate": False,
                    }
                )
            )
            manager_ready = json.loads(await manager_websocket.recv())
            if manager_ready.get("type") != "ready":
                detail = str(
                    manager_ready.get(
                        "detail",
                        "Preview websocket tunnel could not be established.",
                    )
                )
                await websocket.close(code=1011, reason=detail[:120])
                return

            accepted_subprotocol = manager_ready.get("accepted_subprotocol")
            await websocket.accept(
                subprotocol=(
                    str(accepted_subprotocol)
                    if isinstance(accepted_subprotocol, str)
                    and accepted_subprotocol.strip()
                    else None
                )
            )

            client_to_upstream = create_task(
                _forward_client_messages(websocket=websocket, upstream=manager_websocket)
            )
            upstream_to_client = create_task(
                _forward_upstream_messages(websocket=websocket, upstream=manager_websocket)
            )
            done, pending = await wait(
                {client_to_upstream, upstream_to_client},
                return_when=FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
    except ConnectionClosed:
        await websocket.close()
    except OSError:
        await websocket.close(
            code=1011,
            reason="Preview websocket service is unreachable.",
        )


@router.get("/chat-surfaces/dev-sessions/{surface_session_id}/proxy")
@router.get("/chat-surfaces/dev-sessions/{surface_session_id}/proxy/")
@router.get("/chat-surfaces/dev-sessions/{surface_session_id}/proxy/{proxy_path:path}")
def proxy_dev_surface_runtime(
    surface_session_id: str,
    request: FastAPIRequest,
    proxy_path: str = "",
    db: DBSession = Depends(get_db),
) -> Response:
    """Proxy one local development surface resource through the Pivot backend."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    if record.dev_server_url is None:
        raise HTTPException(
            status_code=400,
            detail="Development proxy requires a dev-mode surface session.",
        )
    forwarded_query_items = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key != "surface_token"
    ]
    query_string = urlencode(forwarded_query_items)
    try:
        status_code, content_type, payload, response_headers = _fetch_upstream_resource(
            request_accept=request.headers.get("accept", "*/*"),
            upstream_targets=_build_upstream_target_candidates(
                base_url=record.dev_server_url,
                proxy_path=proxy_path,
                query_string=query_string,
            ),
        )
    except HTTPError as err:
        detail = f"Development surface returned HTTP {err.code}."
        raise HTTPException(status_code=502, detail=detail) from err
    except URLError as err:
        raise HTTPException(
            status_code=502,
            detail="Development surface server is unreachable.",
        ) from err

    if _is_html_response(content_type=content_type, payload=payload):
        surface_token = SurfaceTokenService.create_surface_token(
            surface_session_id=record.surface_session_id,
            username=record.username,
        )
        bootstrap = _serialize_bootstrap(
            SurfaceSessionService(db).build_bootstrap(record=record),
            surface_token=surface_token,
            theme=_resolve_surface_theme(request=request),
        )
        injected_html = _inject_bootstrap_script(
            html=payload.decode("utf-8"),
            bootstrap=bootstrap.model_dump(),
            proxy_base_path=_build_proxy_base_path(
                surface_session_id=record.surface_session_id
            ),
        )
        response_headers["Content-Type"] = "text/html; charset=utf-8"
        response = Response(
            content=injected_html.encode("utf-8"),
            status_code=status_code,
            headers=response_headers,
        )
        request_surface_token = _extract_surface_token(request=request)
        if request_surface_token:
            response.set_cookie(
                key=_SURFACE_ACCESS_COOKIE_NAME,
                value=request_surface_token,
                httponly=True,
                samesite="lax",
                path=_build_surface_session_path(
                    surface_session_id=record.surface_session_id,
                    mode=record.mode,
                ),
            )
        return response

    if _is_vite_client_request(proxy_path=proxy_path, content_type=content_type):
        proxy_base_path = _build_proxy_base_path(
            surface_session_id=record.surface_session_id
        )
        rewritten_client = _rewrite_vite_client_hmr_target(
            source=_rewrite_root_relative_js_specifiers(
                source=payload.decode("utf-8"),
                proxy_base_path=proxy_base_path,
            ),
            hmr_proxy_path=_build_hmr_proxy_path(
                surface_session_id=record.surface_session_id
            ),
        )
        response_headers["Content-Type"] = "application/javascript; charset=utf-8"
        return Response(
            content=rewritten_client.encode("utf-8"),
            status_code=status_code,
            headers=response_headers,
        )

    if _is_javascript_response(content_type=content_type, proxy_path=proxy_path):
        rewritten_module = _rewrite_root_relative_js_specifiers(
            source=payload.decode("utf-8"),
            proxy_base_path=_build_proxy_base_path(
                surface_session_id=record.surface_session_id
            ),
        )
        response_headers["Content-Type"] = "application/javascript; charset=utf-8"
        return Response(
            content=rewritten_module.encode("utf-8"),
            status_code=status_code,
            headers=response_headers,
        )

    return Response(
        content=payload,
        status_code=status_code,
        headers=response_headers,
        media_type=content_type or None,
    )


@router.get("/chat-surfaces/installed-sessions/{surface_session_id}/runtime")
@router.get("/chat-surfaces/installed-sessions/{surface_session_id}/runtime/")
@router.get("/chat-surfaces/installed-sessions/{surface_session_id}/runtime/{runtime_path:path}")
def serve_installed_surface_runtime(
    surface_session_id: str,
    request: FastAPIRequest,
    runtime_path: str = "",
    db: DBSession = Depends(get_db),
) -> Response:
    """Serve one packaged installed surface runtime through the Pivot backend."""
    record = _authenticate_surface_request(
        db=db,
        request=request,
        surface_session_id=surface_session_id,
    )
    runtime_service = SurfaceRuntimeService()
    try:
        asset = runtime_service.read_installed_asset(
            record=record,
            requested_path=runtime_path,
        )
    except SurfaceRuntimeNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    if _is_html_response(content_type=asset.content_type, payload=asset.content):
        surface_token = SurfaceTokenService.create_surface_token(
            surface_session_id=record.surface_session_id,
            username=record.username,
        )
        bootstrap = _serialize_installed_bootstrap(
            SurfaceSessionService(db).build_bootstrap(record=record),
            surface_token=surface_token,
            theme=_resolve_surface_theme(request=request),
        )
        proxy_base_path = _build_installed_runtime_base_path(record=record)
        injected_html = _inject_bootstrap_script(
            html=asset.content.decode("utf-8"),
            bootstrap=bootstrap.model_dump(),
            proxy_base_path=proxy_base_path,
        )
        response = Response(
            content=injected_html.encode("utf-8"),
            media_type="text/html",
        )
        request_surface_token = _extract_surface_token(request=request)
        if request_surface_token:
            response.set_cookie(
                key=_SURFACE_ACCESS_COOKIE_NAME,
                value=request_surface_token,
                httponly=True,
                samesite="lax",
                path=_build_surface_session_path(
                    surface_session_id=record.surface_session_id,
                    mode=record.mode,
                ),
            )
        return response

    if _is_javascript_response(content_type=asset.content_type, proxy_path=runtime_path):
        rewritten_module = _rewrite_root_relative_js_specifiers(
            source=asset.content.decode("utf-8"),
            proxy_base_path=_build_installed_runtime_base_path(record=record),
        )
        return Response(
            content=rewritten_module.encode("utf-8"),
            media_type="application/javascript",
        )

    return Response(
        content=asset.content,
        media_type=asset.content_type or None,
    )


@router.websocket("/chat-surfaces/dev-sessions/{surface_session_id}/hmr")
async def proxy_dev_surface_hmr(
    websocket: WebSocket,
    surface_session_id: str,
    db: DBSession = Depends(get_db),
) -> None:
    """Tunnel one development HMR websocket through the Pivot backend."""
    record = _authenticate_surface_websocket(
        db=db,
        websocket=websocket,
        surface_session_id=surface_session_id,
    )
    if record.dev_server_url is None:
        await websocket.close(code=1011, reason="Development HMR requires dev mode.")
        return

    requested_protocol = websocket.headers.get("sec-websocket-protocol")
    subprotocol = requested_protocol if requested_protocol else None
    await websocket.accept(subprotocol=subprotocol)

    upstream_targets = _build_upstream_hmr_target_candidates(
        dev_server_url=record.dev_server_url
    )

    for upstream_target in upstream_targets:
        try:
            if subprotocol and upstream_target.host_header:
                upstream_connection = websocket_connect(
                    upstream_target.url,
                    subprotocols=[cast("Subprotocol", subprotocol)],
                    additional_headers={"Host": upstream_target.host_header},
                )
            elif subprotocol:
                upstream_connection = websocket_connect(
                    upstream_target.url,
                    subprotocols=[cast("Subprotocol", subprotocol)],
                )
            elif upstream_target.host_header:
                upstream_connection = websocket_connect(
                    upstream_target.url,
                    additional_headers={"Host": upstream_target.host_header},
                )
            else:
                upstream_connection = websocket_connect(upstream_target.url)

            async with upstream_connection as upstream:
                client_to_upstream = create_task(
                    _forward_client_messages(websocket=websocket, upstream=upstream)
                )
                upstream_to_client = create_task(
                    _forward_upstream_messages(websocket=websocket, upstream=upstream)
                )
                done, pending = await wait(
                    {client_to_upstream, upstream_to_client},
                    return_when=FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
                return
        except ConnectionClosed:
            await websocket.close()
            return
        except OSError:
            continue

    await websocket.close(code=1011, reason="Development HMR server is unreachable.")


_SURFACE_ACCESS_COOKIE_NAME = "pivot_surface_access"


def _serialize_preview_record(
    *,
    record: PreviewEndpointRecord,
    workspace_logical_root: str,
    service: PreviewEndpointService,
) -> PreviewEndpointResponse:
    """Return one API-facing preview endpoint payload."""
    return PreviewEndpointResponse(
        preview_id=record.preview_id,
        session_id=record.session_id,
        workspace_id=record.workspace_id,
        workspace_logical_root=workspace_logical_root,
        title=record.title,
        port=record.port,
        path=record.path,
        has_launch_recipe=bool(record.start_server and record.cwd),
        proxy_url=service.build_proxy_url(record=record),
        created_at=record.created_at.replace(tzinfo=UTC).isoformat(),
    )


def _authenticate_surface_request(
    *,
    db: DBSession,
    request: FastAPIRequest | None,
    surface_session_id: str,
):
    """Resolve one surface session from either user auth or a surface token."""
    service = SurfaceSessionService(db)
    auth_header = request.headers.get("authorization") if request is not None else None
    bearer_token = _extract_bearer_token(auth_header)
    surface_token = _extract_surface_token(request=request)

    if surface_token is not None:
        try:
            claims = SurfaceTokenService.validate_surface_token(surface_token)
        except SurfaceTokenValidationError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(err),
            ) from err

        if claims.surface_session_id != surface_session_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Surface token does not match the requested surface session.",
            )

        try:
            return service.get_surface_session(
                surface_session_id=surface_session_id,
                username=claims.username,
            )
        except SurfaceSessionNotFoundError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except SurfaceSessionPermissionError as err:
            raise HTTPException(status_code=403, detail=str(err)) from err

    if bearer_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Surface access token or user bearer token is required.",
        )

    user = resolve_user_from_access_token(bearer_token, db)
    try:
        return service.get_surface_session(
            surface_session_id=surface_session_id,
            username=user.username,
        )
    except SurfaceSessionNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err


def _authenticate_preview_request(
    *,
    db: DBSession,
    request: FastAPIRequest | None,
    preview_id: str,
) -> PreviewEndpointRecord:
    """Resolve one preview endpoint from either user auth or a surface token."""
    preview_service = PreviewEndpointService(db)
    auth_header = request.headers.get("authorization") if request is not None else None
    bearer_token = _extract_bearer_token(auth_header)
    surface_token = _extract_surface_token(request=request)

    if surface_token is not None:
        try:
            claims = SurfaceTokenService.validate_surface_token(surface_token)
        except SurfaceTokenValidationError as err:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(err),
            ) from err

        try:
            surface_record = SurfaceSessionService(db).get_surface_session(
                surface_session_id=claims.surface_session_id,
                username=claims.username,
            )
            preview_record = preview_service.get_preview_endpoint(
                preview_id=preview_id,
                username=claims.username,
            )
        except SurfaceSessionNotFoundError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except SurfaceSessionPermissionError as err:
            raise HTTPException(status_code=403, detail=str(err)) from err
        except PreviewEndpointNotFoundError as err:
            raise HTTPException(status_code=404, detail=str(err)) from err
        except PreviewEndpointPermissionError as err:
            raise HTTPException(status_code=403, detail=str(err)) from err
        if preview_record.session_id != surface_record.session_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Preview endpoint does not belong to the active surface session.",
            )
        return preview_record

    if bearer_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Surface access token or user bearer token is required.",
        )

    user = resolve_user_from_access_token(bearer_token, db)
    try:
        return preview_service.get_preview_endpoint(
            preview_id=preview_id,
            username=user.username,
        )
    except PreviewEndpointNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PreviewEndpointPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err


def _authenticate_surface_websocket(
    *,
    db: DBSession,
    websocket: WebSocket,
    surface_session_id: str,
):
    """Resolve one surface session from websocket cookies or query parameters."""
    service = SurfaceSessionService(db)
    surface_token = _extract_surface_token_from_websocket(websocket=websocket)
    if surface_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Surface access token is required for HMR websocket access.",
        )

    try:
        claims = SurfaceTokenService.validate_surface_token(surface_token)
    except SurfaceTokenValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
        ) from err

    if claims.surface_session_id != surface_session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Surface token does not match the requested surface session.",
        )

    try:
        return service.get_surface_session(
            surface_session_id=surface_session_id,
            username=claims.username,
        )
    except SurfaceSessionNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err


def _authenticate_preview_websocket(
    *,
    db: DBSession,
    websocket: WebSocket,
    preview_id: str,
) -> PreviewEndpointRecord:
    """Resolve one preview endpoint from a surface websocket token."""
    surface_token = _extract_surface_token_from_websocket(websocket=websocket)
    if surface_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Surface access token is required for preview websocket access.",
        )

    try:
        claims = SurfaceTokenService.validate_surface_token(surface_token)
    except SurfaceTokenValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
        ) from err

    preview_service = PreviewEndpointService(db)
    try:
        surface_record = SurfaceSessionService(db).get_surface_session(
            surface_session_id=claims.surface_session_id,
            username=claims.username,
        )
        preview_record = preview_service.get_preview_endpoint(
            preview_id=preview_id,
            username=claims.username,
        )
    except SurfaceSessionNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except SurfaceSessionPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except PreviewEndpointNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PreviewEndpointPermissionError as err:
        raise HTTPException(status_code=403, detail=str(err)) from err

    if preview_record.session_id != surface_record.session_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Preview endpoint does not belong to the active surface session.",
        )
    return preview_record


def _serialize_bootstrap(
    payload: dict[str, object],
    *,
    surface_token: str,
    theme: SurfaceThemeResponse | None = None,
) -> DevSurfaceBootstrapResponse:
    """Convert one bootstrap dict into its response schema."""
    files_api = payload.get("files_api", {})
    raw_agent_id = payload.get("agent_id")
    agent_id = raw_agent_id if isinstance(raw_agent_id, int) else int(str(raw_agent_id))

    raw_capabilities = payload.get("capabilities")
    capabilities = (
        [str(item) for item in raw_capabilities]
        if isinstance(raw_capabilities, list)
        else []
    )

    return DevSurfaceBootstrapResponse(
        surface_session_id=str(payload["surface_session_id"]),
        surface_token=surface_token,
        mode="dev",
        surface_key=str(payload["surface_key"]),
        display_name=str(payload["display_name"]),
        agent_id=agent_id,
        session_id=str(payload["session_id"]),
        workspace_id=str(payload["workspace_id"]),
        workspace_logical_root=str(payload["workspace_logical_root"]),
        dev_server_url=str(payload["dev_server_url"]),
        capabilities=capabilities,
        files_api=SurfaceFilesApiResponse(
            directory_url=(
                str(files_api["directory_url"]) if isinstance(files_api, dict) else ""
            ),
            text_url=str(files_api["text_url"]) if isinstance(files_api, dict) else "",
            blob_url=str(files_api["blob_url"]) if isinstance(files_api, dict) else "",
            tree_url=str(files_api["tree_url"]) if isinstance(files_api, dict) else "",
            content_url=(
                str(files_api["content_url"]) if isinstance(files_api, dict) else ""
            ),
        ),
        theme=theme,
    )


def _serialize_installed_bootstrap(
    payload: dict[str, object],
    *,
    surface_token: str,
    theme: SurfaceThemeResponse | None = None,
) -> InstalledSurfaceBootstrapResponse:
    """Convert one installed bootstrap dict into its response schema."""
    files_api = payload.get("files_api", {})
    raw_agent_id = payload.get("agent_id")
    agent_id = raw_agent_id if isinstance(raw_agent_id, int) else int(str(raw_agent_id))
    raw_installation_id = payload.get("extension_installation_id")
    extension_installation_id = (
        raw_installation_id
        if isinstance(raw_installation_id, int)
        else int(str(raw_installation_id))
    )

    raw_capabilities = payload.get("capabilities")
    capabilities = (
        [str(item) for item in raw_capabilities]
        if isinstance(raw_capabilities, list)
        else []
    )

    return InstalledSurfaceBootstrapResponse(
        surface_session_id=str(payload["surface_session_id"]),
        surface_token=surface_token,
        mode="installed",
        surface_key=str(payload["surface_key"]),
        display_name=str(payload["display_name"]),
        package_id=str(payload["package_id"]),
        extension_installation_id=extension_installation_id,
        agent_id=agent_id,
        session_id=str(payload["session_id"]),
        workspace_id=str(payload["workspace_id"]),
        workspace_logical_root=str(payload["workspace_logical_root"]),
        runtime_url=str(payload["runtime_url"]),
        capabilities=capabilities,
        files_api=SurfaceFilesApiResponse(
            directory_url=(
                str(files_api["directory_url"]) if isinstance(files_api, dict) else ""
            ),
            text_url=str(files_api["text_url"]) if isinstance(files_api, dict) else "",
            blob_url=str(files_api["blob_url"]) if isinstance(files_api, dict) else "",
            tree_url=str(files_api["tree_url"]) if isinstance(files_api, dict) else "",
            content_url=(
                str(files_api["content_url"]) if isinstance(files_api, dict) else ""
            ),
        ),
        theme=theme,
    )


def _serialize_tree_entry(
    entry: WorkspaceFileTreeEntry,
) -> WorkspaceFileTreeEntryResponse:
    """Convert one internal tree entry into its API schema."""
    return WorkspaceFileTreeEntryResponse(
        path=entry.path,
        name=entry.name,
        kind="directory" if entry.kind == "directory" else "file",
        parent_path=entry.parent_path,
        size_bytes=entry.size_bytes,
    )


def _serialize_directory_entry(
    entry: WorkspaceFileTreeEntry,
) -> WorkspaceDirectoryEntryResponse:
    """Convert one internal directory entry into its API schema."""
    return WorkspaceDirectoryEntryResponse(
        path=entry.path,
        name=entry.name,
        kind="directory" if entry.kind == "directory" else "file",
        parent_path=entry.parent_path,
        size_bytes=entry.size_bytes,
    )


def _build_proxy_target_url(
    *,
    base_url: str,
    proxy_path: str,
    query_string: str,
) -> str:
    """Compose one upstream development runtime URL from the proxied request.

    Why:
        Development runtimes may expose either a server root such as
        ``http://127.0.0.1:5173`` or a concrete entry HTML path such as
        ``http://127.0.0.1:4173/index.html``.
        Keeping the original base URL intact ensures sibling assets resolve
        correctly for entry-page URLs instead of being forced under an
        artificial trailing slash.
    """
    upstream_url = base_url if not proxy_path else urljoin(base_url, proxy_path)
    if query_string:
        return f"{upstream_url}?{query_string}"
    return upstream_url


def _fetch_upstream_resource(
    *,
    request_accept: str,
    upstream_targets: list[_UpstreamTarget],
) -> tuple[int, str, bytes, dict[str, str]]:
    """Try local upstream candidates until one development server responds."""
    last_error: URLError | None = None

    for upstream_target in upstream_targets:
        request_headers = {"Accept": request_accept}
        if upstream_target.host_header:
            request_headers["Host"] = upstream_target.host_header

        try:
            upstream_request = Request(
                upstream_target.url,
                headers=request_headers,
                method="GET",
            )
            with urlopen(upstream_request) as upstream_response:
                return (
                    upstream_response.getcode(),
                    upstream_response.headers.get("Content-Type", ""),
                    upstream_response.read(),
                    _extract_proxy_response_headers(upstream_response.headers),
                )
        except HTTPError:
            raise
        except URLError as err:
            last_error = err

    if last_error is None:
        last_error = URLError("No upstream development surface targets were built.")
    raise last_error


def _build_upstream_target_candidates(
    *,
    base_url: str,
    proxy_path: str,
    query_string: str,
) -> list[_UpstreamTarget]:
    """Build reachable upstream HTTP targets for one local dev runtime URL."""
    parsed = urlparse(base_url)
    original_host_header = parsed.netloc
    candidates = [
        _UpstreamTarget(
            url=_build_proxy_target_url(
                base_url=base_url,
                proxy_path=proxy_path,
                query_string=query_string,
            ),
            host_header=original_host_header,
        )
    ]

    if parsed.hostname is None or not _is_loopback_hostname(parsed.hostname):
        return candidates

    for host_alias in _DEV_SURFACE_HOST_ALIASES:
        candidate_base_url = _replace_url_hostname(parsed=parsed, hostname=host_alias)
        candidate_url = _build_proxy_target_url(
            base_url=candidate_base_url,
            proxy_path=proxy_path,
            query_string=query_string,
        )
        if any(existing.url == candidate_url for existing in candidates):
            continue
        candidates.append(
            _UpstreamTarget(
                url=candidate_url,
                host_header=original_host_header,
            )
        )

    return candidates


def _extract_proxy_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Forward only safe upstream headers to the proxied surface response."""
    allowed_headers = {
        "cache-control",
        "content-language",
        "content-type",
        "etag",
        "last-modified",
        "vary",
    }
    response_headers: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in allowed_headers:
            response_headers[key] = value
    return response_headers


def _build_proxy_base_path(*, surface_session_id: str) -> str:
    """Return the stable proxy prefix injected into dev surface HTML."""
    return f"/api/chat-surfaces/dev-sessions/{surface_session_id}/proxy/"


def _build_installed_runtime_base_path(*, record: SurfaceSessionRecord) -> str:
    """Return the stable proxy prefix for one installed surface runtime."""
    base_path = f"/api/chat-surfaces/installed-sessions/{record.surface_session_id}/runtime/"
    parent_path = (record.runtime_entrypoint_parent_path or "").strip("/")
    if not parent_path:
        return base_path
    return f"{base_path}{parent_path}/"


def _build_hmr_proxy_path(*, surface_session_id: str) -> str:
    """Return the stable websocket tunnel path for one dev surface session."""
    return f"/api/chat-surfaces/dev-sessions/{surface_session_id}/hmr"


def _build_preview_proxy_base_path(*, preview_id: str) -> str:
    """Return the stable proxy prefix for one chat preview endpoint."""
    return f"/api/chat-previews/{preview_id}/proxy/"


def _build_preview_ws_base_path(*, preview_id: str) -> str:
    """Return the stable websocket tunnel prefix for one preview endpoint."""
    return f"/api/chat-previews/{preview_id}/ws/"


def _build_surface_session_path(*, surface_session_id: str, mode: str) -> str:
    """Return the shared path prefix for one surface session cookie scope."""
    if mode == "installed":
        return f"/api/chat-surfaces/installed-sessions/{surface_session_id}"
    return f"/api/chat-surfaces/dev-sessions/{surface_session_id}"


def _build_preview_path_scope(*, preview_id: str) -> str:
    """Return the cookie path scope for one preview endpoint."""
    return f"/api/chat-previews/{preview_id}"


def _extract_bearer_token(auth_header: str | None) -> str | None:
    """Return one bearer token extracted from an Authorization header."""
    if auth_header is None:
        return None
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _extract_surface_token(*, request: FastAPIRequest | None) -> str | None:
    """Return one surface token from the query string or cookie jar."""
    if request is None:
        return None
    query_token = request.query_params.get("surface_token")
    if isinstance(query_token, str) and query_token:
        return query_token
    cookie_token = request.cookies.get(_SURFACE_ACCESS_COOKIE_NAME)
    if isinstance(cookie_token, str) and cookie_token:
        return cookie_token
    return None


def _extract_preview_request_headers(*, request: FastAPIRequest) -> dict[str, str]:
    """Return safe request headers to forward to one preview target."""
    allowed_headers = {
        "accept",
        "accept-language",
        "cache-control",
        "content-type",
        "origin",
        "pragma",
        "referer",
        "user-agent",
    }
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() in allowed_headers
    }


def _extract_preview_websocket_headers(*, websocket: WebSocket) -> dict[str, str]:
    """Return safe websocket request headers to forward to one preview target."""
    allowed_headers = {
        "accept-language",
        "origin",
        "pragma",
        "referer",
        "user-agent",
    }
    return {
        key: value
        for key, value in websocket.headers.items()
        if key.lower() in allowed_headers
    }


def _resolve_surface_theme(
    *,
    request: FastAPIRequest | None,
) -> SurfaceThemeResponse | None:
    """Return one host-provided light/dark theme payload from query params."""
    if request is None:
        return None

    resolved = str(request.query_params.get("resolved_theme", "")).strip().lower()
    if resolved not in {"dark", "light"}:
        return None

    preference = str(request.query_params.get("theme_preference", "")).strip().lower()
    normalized_preference: Literal["system", "dark", "light"]
    if preference in {"system", "dark", "light"}:
        normalized_preference = cast("Literal['system', 'dark', 'light']", preference)
    else:
        normalized_preference = "system"

    normalized_resolved = cast("Literal['dark', 'light']", resolved)
    return SurfaceThemeResponse(
        preference=normalized_preference,
        resolved=normalized_resolved,
    )


def _extract_surface_token_from_websocket(*, websocket: WebSocket) -> str | None:
    """Return one surface token from websocket query params or cookies."""
    query_token = websocket.query_params.get("surface_token")
    if isinstance(query_token, str) and query_token:
        return query_token
    cookie_token = websocket.cookies.get(_SURFACE_ACCESS_COOKIE_NAME)
    if isinstance(cookie_token, str) and cookie_token:
        return cookie_token
    return None


def _is_html_response(*, content_type: str, payload: bytes) -> bool:
    """Return whether one proxied response should receive bootstrap injection."""
    normalized_content_type = content_type.lower()
    if "text/html" in normalized_content_type:
        return True
    return payload.lstrip().startswith(b"<!doctype html") or payload.lstrip().startswith(
        b"<html"
    )


def _inject_bootstrap_script(
    *,
    html: str,
    bootstrap: dict[str, object],
    proxy_base_path: str,
) -> str:
    """Inject the server bootstrap payload into one proxied HTML document."""
    rewritten_html = _rewrite_root_relative_asset_urls(
        html=html,
        proxy_base_path=proxy_base_path,
    )
    hmr_ws_path: str | None = None
    if str(bootstrap.get("mode", "")) == "dev":
        hmr_ws_path = _build_hmr_proxy_path(
            surface_session_id=str(bootstrap["surface_session_id"])
        )
    bootstrap_script = (
        "<script>"
        f"window.__PIVOT_SURFACE_BOOTSTRAP__ = {json.dumps(bootstrap)};"
        f"window.__PIVOT_SURFACE_PROXY_BASE__ = {json.dumps(proxy_base_path)};"
        f"window.__PIVOT_SURFACE_HMR_WS_PATH__ = {json.dumps(hmr_ws_path)};"
        "</script>"
    )
    if "</head>" in rewritten_html:
        return rewritten_html.replace("</head>", f"{bootstrap_script}</head>", 1)
    if "</body>" in rewritten_html:
        return rewritten_html.replace("</body>", f"{bootstrap_script}</body>", 1)
    return f"{bootstrap_script}{rewritten_html}"


def _inject_preview_runtime_script(*, html: str, preview_id: str) -> str:
    """Inject preview runtime helpers into one proxied HTML document."""
    proxy_base_path = _build_preview_proxy_base_path(preview_id=preview_id)
    rewritten_html = _rewrite_root_relative_asset_urls(
        html=html,
        proxy_base_path=proxy_base_path,
    )
    websocket_base_path = _build_preview_ws_base_path(preview_id=preview_id)
    preview_script = (
        "<script>"
        f"window.__PIVOT_PREVIEW_PROXY_BASE__ = {json.dumps(proxy_base_path)};"
        f"window.__PIVOT_PREVIEW_WS_BASE__ = {json.dumps(websocket_base_path)};"
        "(function(){"
        "const OriginalWebSocket = window.WebSocket;"
        "if (typeof OriginalWebSocket !== 'function') return;"
        "const wsBasePath = window.__PIVOT_PREVIEW_WS_BASE__;"
        "const currentWsOrigin = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;"
        "function rewriteSocketUrl(rawUrl){"
        "try{"
        "const resolved = new URL(String(rawUrl), currentWsOrigin);"
        "if (!(resolved.protocol === 'ws:' || resolved.protocol === 'wss:')) return rawUrl;"
        "if (resolved.host !== window.location.host) return rawUrl;"
        "if (resolved.pathname.startsWith(wsBasePath)) return rawUrl;"
        "const nextPath = resolved.pathname.startsWith('/') ? resolved.pathname.slice(1) : resolved.pathname;"
        "return `${currentWsOrigin}${wsBasePath}${nextPath}${resolved.search}`;"
        "}catch(_error){"
        "return rawUrl;"
        "}"
        "}"
        "class PivotPreviewWebSocket extends OriginalWebSocket {"
        "constructor(url, protocols){"
        "super(rewriteSocketUrl(url), protocols);"
        "}"
        "}"
        "PivotPreviewWebSocket.CONNECTING = OriginalWebSocket.CONNECTING;"
        "PivotPreviewWebSocket.OPEN = OriginalWebSocket.OPEN;"
        "PivotPreviewWebSocket.CLOSING = OriginalWebSocket.CLOSING;"
        "PivotPreviewWebSocket.CLOSED = OriginalWebSocket.CLOSED;"
        "window.WebSocket = PivotPreviewWebSocket;"
        "})();"
        "</script>"
    )
    if "</head>" in rewritten_html:
        return rewritten_html.replace("</head>", f"{preview_script}</head>", 1)
    if "</body>" in rewritten_html:
        return rewritten_html.replace("</body>", f"{preview_script}</body>", 1)
    return f"{preview_script}{rewritten_html}"


def _rewrite_root_relative_asset_urls(*, html: str, proxy_base_path: str) -> str:
    """Rewrite root-relative HTML asset URLs so dev resources stay under proxy.

    Why:
        Vite's development index pages usually reference assets such as
        ``/@vite/client`` and ``/src/main.tsx`` from the server root. Once the
        page is served from Pivot's proxy route, those paths would otherwise
        escape the proxy and 404 against the Pivot frontend.
    """
    asset_pattern = re.compile(
        r"""(?P<attr>\b(?:src|href))=(?P<quote>["'])/(?P<path>(?!/)[^"']*)(?P=quote)"""
    )

    def replace(match: re.Match[str]) -> str:
        path = match.group("path")
        if path.startswith("api/chat-surfaces/"):
            return match.group(0)
        return (
            f"{match.group('attr')}={match.group('quote')}"
            f"{proxy_base_path}{path}{match.group('quote')}"
        )

    return asset_pattern.sub(replace, html)


def _is_vite_client_request(*, proxy_path: str, content_type: str) -> bool:
    """Return whether one proxied response is Vite's special client runtime."""
    if proxy_path != "@vite/client":
        return False
    normalized_content_type = content_type.lower()
    return (
        "javascript" in normalized_content_type
        or "ecmascript" in normalized_content_type
        or not normalized_content_type
    )


def _is_javascript_response(*, content_type: str, proxy_path: str) -> bool:
    """Return whether one proxied response should be treated as JavaScript."""
    normalized_content_type = content_type.lower()
    if "javascript" in normalized_content_type or "ecmascript" in normalized_content_type:
        return True
    return proxy_path.endswith(".js") or proxy_path.endswith(".mjs") or proxy_path.endswith(
        ".ts"
    )


def _rewrite_vite_client_hmr_target(*, source: str, hmr_proxy_path: str) -> str:
    """Rewrite Vite's websocket host resolution to use Pivot's HMR tunnel."""
    rewritten = re.sub(
        r"const socketHost = .*?;",
        (
            "const socketHost = "
            f"`${{importMetaUrl.host}}{hmr_proxy_path}`;"
        ),
        source,
        count=1,
    )
    return re.sub(
        r"const directSocketHost = .*?;",
        "const directSocketHost = socketHost;",
        rewritten,
        count=1,
    )


def _rewrite_root_relative_js_specifiers(*, source: str, proxy_base_path: str) -> str:
    """Rewrite root-relative JS module specifiers so browser fetches stay proxied."""
    specifier_pattern = re.compile(
        r'(?P<prefix>\bimport\s*(?:[^"\']*?\sfrom\s*)?|\bimport\()(?P<quote>["\'])/(?P<path>[^"\']*)(?P=quote)'
    )

    def replace(match: re.Match[str]) -> str:
        path = match.group("path")
        if path.startswith("api/chat-surfaces/"):
            return match.group(0)
        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{proxy_base_path}{path}{match.group('quote')}"
        )

    return specifier_pattern.sub(replace, source)


def _build_upstream_hmr_ws_url(*, dev_server_url: str) -> str:
    """Resolve the upstream websocket URL for a development runtime."""
    parsed = urlparse(dev_server_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}/"


def _build_upstream_hmr_target_candidates(
    *,
    dev_server_url: str,
) -> list[_UpstreamTarget]:
    """Build reachable upstream websocket targets for one local dev runtime."""
    parsed = urlparse(dev_server_url)
    original_host_header = parsed.netloc
    primary_url = _build_upstream_hmr_ws_url(dev_server_url=dev_server_url)
    candidates = [_UpstreamTarget(url=primary_url, host_header=original_host_header)]

    if parsed.hostname is None or not _is_loopback_hostname(parsed.hostname):
        return candidates

    for host_alias in _DEV_SURFACE_HOST_ALIASES:
        candidate_base_url = _replace_url_hostname(parsed=parsed, hostname=host_alias)
        candidate_url = _build_upstream_hmr_ws_url(dev_server_url=candidate_base_url)
        if any(existing.url == candidate_url for existing in candidates):
            continue
        candidates.append(
            _UpstreamTarget(
                url=candidate_url,
                host_header=original_host_header,
            )
        )

    return candidates


def _replace_url_hostname(*, parsed: Any, hostname: str) -> str:
    """Replace one parsed URL hostname while preserving user info and port."""
    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    return parsed._replace(netloc=f"{userinfo}{hostname}{port_suffix}").geturl()


def _is_loopback_hostname(hostname: str) -> bool:
    """Return whether one hostname represents a loopback-only author URL."""
    return hostname == "localhost" or hostname.startswith("127.") or hostname == "::1"


async def _forward_client_messages(*, websocket: WebSocket, upstream: Any) -> None:
    """Forward browser websocket frames into the upstream HMR server."""
    try:
        while True:
            message = await websocket.receive()
            message_type = message.get("type")
            if message_type == "websocket.disconnect":
                break
            text = message.get("text")
            if isinstance(text, str):
                await upstream.send(text)
                continue
            binary = message.get("bytes")
            if isinstance(binary, bytes):
                await upstream.send(binary)
    except WebSocketDisconnect:
        return


async def _forward_upstream_messages(*, websocket: WebSocket, upstream: Any) -> None:
    """Forward upstream HMR websocket frames back into the browser."""
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)
