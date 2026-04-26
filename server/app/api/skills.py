"""API endpoints for markdown skill management."""

import asyncio
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.config import get_settings
from app.db.session import managed_session
from app.models.user import User
from app.services.skill_import_progress_service import (
    get_skill_import_progress_service,
)
from app.services.skill_service import (
    BundleImportFile,
    delete_user_skill,
    install_archive_skill,
    install_bundle_skill,
    install_github_skill,
    list_private_skills,
    list_shared_skills,
    probe_github_skill_import,
    read_shared_skill,
    read_user_skill,
    upsert_user_skill,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, select
from starlette.datastructures import UploadFile as StarletteUploadFile

router = APIRouter()
settings = get_settings()


class SkillWriteRequest(BaseModel):
    """Request payload for writing a markdown skill source file."""

    source: str


class GitHubSkillProbeRequest(BaseModel):
    """Request payload for probing a GitHub repository for skills."""

    github_url: str
    ref: str | None = None


class GitHubSkillImportRequest(BaseModel):
    """Request payload for installing one skill from GitHub."""

    github_url: str
    ref: str
    ref_type: Literal["branch", "tag"]
    kind: Literal["private", "shared"]
    remote_directory_name: str
    skill_name: str


class BundleSkillImportRequest(BaseModel):
    """Multipart fields required to install one uploaded skill bundle."""

    relative_paths: list[str]
    bundle_name: str
    kind: Literal["private", "shared"]
    skill_name: str


class SkillArchiveImportJobResponse(BaseModel):
    """Response returned after creating a skill archive import job."""

    job_id: str


@router.get("/skills/shared")
async def get_shared_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List shared skills visible to the current user."""
    return list_shared_skills(db, current_user.username)


@router.get("/skills/private")
async def get_private_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List private skills for current user."""
    return list_private_skills(db, current_user.username)


@router.get("/skills/shared/{skill_name}")
async def get_shared_skill_source(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read one shared skill source visible to the current user."""
    try:
        return read_shared_skill(db, current_user.username, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/import/bundle")
async def import_bundle_skill_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Install one skill bundle uploaded from the local machine."""
    form_data = await request.form(
        max_files=int(settings.SKILL_IMPORT_MULTIPART_MAX_FILES),
        max_fields=int(settings.SKILL_IMPORT_MULTIPART_MAX_FIELDS),
    )

    try:
        parsed_form = BundleSkillImportRequest.model_validate(
            {
                "relative_paths": form_data.getlist("relative_paths"),
                "bundle_name": form_data.get("bundle_name"),
                "kind": form_data.get("kind"),
                "skill_name": form_data.get("skill_name"),
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    uploads = form_data.getlist("files")
    if len(uploads) != len(parsed_form.relative_paths):
        raise HTTPException(
            status_code=400,
            detail="Uploaded files and relative paths must have the same length.",
        )

    bundle_files: list[BundleImportFile] = []
    for index, upload in enumerate(uploads):
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(
                status_code=422,
                detail="Uploaded files payload is invalid.",
            )

        try:
            content = await upload.read()
        finally:
            await upload.close()

        bundle_files.append(
            BundleImportFile(
                relative_path=parsed_form.relative_paths[index],
                content=content,
            )
        )

    try:
        metadata = install_bundle_skill(
            db,
            current_user,
            bundle_name=parsed_form.bundle_name,
            kind=parsed_form.kind,
            skill_name=parsed_form.skill_name,
            files=bundle_files,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "imported", "metadata": metadata}


@router.post(
    "/skills/import/archive/jobs",
    response_model=SkillArchiveImportJobResponse,
)
async def create_archive_import_job(
    current_user: User = Depends(get_current_user),
) -> SkillArchiveImportJobResponse:
    """Create one SSE-observable archive import job."""
    job = get_skill_import_progress_service().create_job(
        username=current_user.username,
    )
    return SkillArchiveImportJobResponse(job_id=job.job_id)


@router.get("/skills/import/archive/jobs/{job_id}/events/stream")
async def stream_archive_import_job_events(
    job_id: str,
    raw_request: Request,
    after_id: int = 0,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream progress events for one local skill archive import job."""
    progress_service = get_skill_import_progress_service()
    job = progress_service.get_job(job_id=job_id, username=current_user.username)
    if job is None:
        raise HTTPException(status_code=404, detail="Skill import job not found.")

    async def event_generator():
        cursor = after_id
        subscriber = await progress_service.subscribe(
            job_id=job_id,
            username=current_user.username,
        )
        try:
            for payload in progress_service.list_events(
                job_id=job_id,
                username=current_user.username,
                after_id=cursor,
            ):
                event_id = payload.get("event_id")
                if isinstance(event_id, int):
                    cursor = max(cursor, event_id)
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in {"complete", "failed"}:
                    return

            while True:
                if await raw_request.is_disconnected():
                    break

                try:
                    payload = await asyncio.wait_for(
                        subscriber.queue.get(),
                        timeout=15.0,
                    )
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue

                event_id = payload.get("event_id")
                if isinstance(event_id, int) and event_id <= cursor:
                    continue
                if isinstance(event_id, int):
                    cursor = event_id
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in {"complete", "failed"}:
                    break
        finally:
            await progress_service.unsubscribe(
                job_id=job_id,
                subscriber=subscriber,
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/skills/import/archive/jobs/{job_id}")
async def import_archive_skill_endpoint(
    job_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Install one skill archive uploaded from the local machine."""
    progress_service = get_skill_import_progress_service()
    job = progress_service.get_job(job_id=job_id, username=current_user.username)
    if job is None:
        raise HTTPException(status_code=404, detail="Skill import job not found.")
    if job.completed:
        raise HTTPException(status_code=409, detail="Skill import job is already done.")

    form_data = await request.form(max_files=1, max_fields=4)
    upload = form_data.get("archive")
    if not isinstance(upload, StarletteUploadFile):
        raise HTTPException(status_code=422, detail="Archive file is required.")

    kind = form_data.get("kind")
    skill_name = form_data.get("skill_name")
    if not isinstance(kind, str) or kind not in {"private", "shared"}:
        raise HTTPException(status_code=422, detail="Invalid archive import fields.")
    if not isinstance(skill_name, str):
        raise HTTPException(status_code=422, detail="Invalid archive import fields.")

    archive_filename = upload.filename or "skill-archive"
    progress_service.publish(
        job_id,
        stage="upload_received",
        label="Upload received",
        percent=8,
    )

    with NamedTemporaryFile(
        suffix=Path(archive_filename).suffix, delete=False
    ) as handle:
        archive_path = Path(handle.name)
        while chunk := await upload.read(1024 * 1024):
            handle.write(chunk)
    await upload.close()

    def publish_progress(
        stage: str,
        label: str,
        percent: int,
        detail: str | None,
    ) -> None:
        progress_service.publish(
            job_id,
            stage=stage,
            label=label,
            percent=percent,
            detail=detail,
        )

    def run_import() -> dict[str, Any]:
        with managed_session() as worker_db:
            worker_user = worker_db.exec(
                select(User).where(User.username == current_user.username)
            ).first()
            if worker_user is None:
                raise ValueError(f"User '{current_user.username}' not found.")
            return install_archive_skill(
                worker_db,
                worker_user,
                archive_path=archive_path,
                archive_filename=archive_filename,
                kind=kind,
                skill_name=skill_name,
                progress=publish_progress,
            )

    try:
        metadata = await run_in_threadpool(run_import)
    except PermissionError as exc:
        progress_service.publish(
            job_id,
            stage="failed",
            label="Import failed",
            percent=100,
            status="failed",
            detail=str(exc),
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        progress_service.publish(
            job_id,
            stage="failed",
            label="Import failed",
            percent=100,
            status="failed",
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        archive_path.unlink(missing_ok=True)

    progress_service.publish(
        job_id,
        stage="complete",
        label="Skill imported",
        percent=100,
        status="complete",
        metadata=metadata,
    )
    return {"status": "imported", "metadata": metadata}


@router.get("/skills/{kind}/{skill_name}")
async def get_user_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Read a user-owned skill source from private/shared namespace."""
    try:
        return read_user_skill(db, current_user.username, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/skills/{kind}/{skill_name}")
async def upsert_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    body: SkillWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create or update a user-owned markdown skill."""
    try:
        metadata = upsert_user_skill(db, current_user, kind, skill_name, body.source)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "name": skill_name,
        "kind": kind,
        "status": "ok",
        "metadata": metadata,
    }


@router.post("/skills/import/github/probe")
async def probe_github_skill(
    body: GitHubSkillProbeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Probe a public GitHub repository for importable skills."""
    try:
        return probe_github_skill_import(
            db,
            current_user,
            body.github_url,
            ref=body.ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/import/github")
async def import_github_skill(
    body: GitHubSkillImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Install one skill folder from a public GitHub repository."""
    try:
        metadata = install_github_skill(
            db,
            current_user,
            github_url=body.github_url,
            ref=body.ref,
            ref_type=body.ref_type,
            kind=body.kind,
            remote_directory_name=body.remote_directory_name,
            skill_name=body.skill_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "imported", "metadata": metadata}


@router.delete("/skills/{kind}/{skill_name}")
async def delete_skill_source(
    kind: Literal["private", "shared"],
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Delete a user-owned markdown skill."""
    try:
        delete_user_skill(db, current_user, kind, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"name": skill_name, "kind": kind, "status": "deleted"}
