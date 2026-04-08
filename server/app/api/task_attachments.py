"""API endpoints for assistant-generated task attachment previews."""

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.models.user import User
from app.services.task_attachment_service import TaskAttachmentService
from app.utils.http_headers import build_inline_content_disposition
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session as DBSession

router = APIRouter()


@router.get("/task-attachments/{attachment_id}/content")
async def get_task_attachment_content(
    attachment_id: str,
    db: DBSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream one live workspace file reference back to its owner."""
    attachment = TaskAttachmentService(db).get_attachment_for_user(
        attachment_id,
        current_user.username,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Task attachment not found")

    service = TaskAttachmentService(db)
    try:
        content = service.read_attachment_bytes(attachment)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Task attachment source file not found",
        ) from exc
    return Response(
        content=content,
        media_type=attachment.mime_type,
        headers={
            "Content-Disposition": build_inline_content_disposition(
                attachment.display_name
            )
        },
    )
