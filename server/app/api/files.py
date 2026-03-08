"""API endpoints for uploaded image lifecycle management."""

from datetime import timezone

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.schemas.file import FileAssetResponse
from app.services.file_service import FileService
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session as DBSession

router = APIRouter()


def _to_response(file_asset: object) -> FileAssetResponse:
    """Serialize a file asset row into the public API schema."""
    from app.models.file import FileAsset

    if not isinstance(file_asset, FileAsset):
        raise TypeError("Expected FileAsset instance")

    return FileAssetResponse(
        file_id=file_asset.file_id,
        source=file_asset.source,
        original_name=file_asset.original_name,
        mime_type=file_asset.mime_type,
        format=file_asset.format,
        extension=file_asset.extension,
        size_bytes=file_asset.size_bytes,
        width=file_asset.width,
        height=file_asset.height,
        session_id=file_asset.session_id,
        task_id=file_asset.task_id,
        created_at=file_asset.created_at.replace(tzinfo=timezone.utc).isoformat(),
        expires_at=file_asset.expires_at.replace(tzinfo=timezone.utc).isoformat(),
    )


@router.post("/files/images", response_model=FileAssetResponse, status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    source: str = Form(default="local"),
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileAssetResponse:
    """Upload, verify, and persist an image in the current user's workspace."""
    file_bytes = await file.read()
    service = FileService(db)
    try:
        stored_file = service.store_uploaded_image(
            username=current_user.username,
            filename=file.filename or "",
            source=source,
            file_bytes=file_bytes,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return _to_response(stored_file)


@router.delete("/files/{file_id}", status_code=204)
async def delete_image(
    file_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Delete an uploaded image that has not been used in a conversation."""
    service = FileService(db)
    try:
        deleted = service.delete_file_for_user(file_id, current_user.username)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err

    if not deleted:
        raise HTTPException(status_code=404, detail="Image file not found")

    return Response(status_code=204)


@router.get("/files/{file_id}/content")
async def get_image_content(
    file_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream an uploaded image back to the authenticated owner."""
    service = FileService(db)
    file_asset = service.get_file_for_user(file_id, current_user.username)
    if file_asset is None:
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(
        path=file_asset.storage_path,
        media_type=file_asset.mime_type,
        filename=file_asset.original_name,
    )
