"""API endpoints for assistant-generated task attachment previews."""

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.services.task_attachment_service import TaskAttachmentService
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session as DBSession

router = APIRouter()


@router.get("/task-attachments/{attachment_id}/content")
async def get_task_attachment_content(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream one persisted task attachment snapshot back to its owner."""
    attachment = TaskAttachmentService(db).get_attachment_for_user(
        attachment_id,
        current_user.username,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Task attachment not found")

    return FileResponse(
        path=attachment.storage_path,
        media_type=attachment.mime_type,
        filename=attachment.display_name,
    )
