"""API endpoints for markdown skill management."""

import asyncio
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.config import get_settings
from app.db.session import managed_session
from app.models.access import AccessLevel, PrincipalType, ResourceAccess, ResourceType
from app.models.user import User
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.group_service import GroupService
from app.services.skill_import_progress_service import (
    get_skill_import_progress_service,
)
from app.services.skill_service import (
    BundleImportFile,
    create_skill_directory,
    create_skill_file,
    delete_skill_path,
    delete_skill_source,
    get_skill_by_name,
    install_archive_skill,
    install_bundle_skill,
    install_github_skill,
    list_visible_skill_directory,
    list_visible_skills,
    probe_github_skill_import,
    read_visible_skill_file,
    read_visible_skill_source,
    save_user_skill_source,
    set_skill_access,
    update_skill_file,
    update_skill_source,
)
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, select
from starlette.datastructures import UploadFile as StarletteUploadFile

router = APIRouter()
settings = get_settings()


class SkillWriteRequest(BaseModel):
    """Request payload for writing a markdown skill source file."""

    source: str


class SkillCreateRequest(SkillWriteRequest):
    """Request payload for creating one Skill."""

    skill_name: str


class GitHubSkillProbeRequest(BaseModel):
    """Request payload for probing a GitHub repository for skills."""

    github_url: str
    ref: str | None = None


class GitHubSkillImportRequest(BaseModel):
    """Request payload for installing one skill from GitHub."""

    github_url: str
    ref: str
    ref_type: Literal["branch", "tag"]
    remote_directory_name: str
    skill_name: str


class BundleSkillImportRequest(BaseModel):
    """Multipart fields required to install one uploaded skill bundle."""

    relative_paths: list[str]
    bundle_name: str
    skill_name: str


class SkillFileWriteRequest(BaseModel):
    """Payload for updating one file inside a skill directory."""

    path: str
    content: str


class SkillFileCreateRequest(BaseModel):
    """Payload for creating one file inside a skill directory."""

    path: str
    content: str = ""


class SkillDirectoryCreateRequest(BaseModel):
    """Payload for creating one directory inside a skill directory."""

    path: str


class SkillFileTreeEntryResponse(BaseModel):
    """One file or directory entry inside a skill bundle."""

    path: str
    name: str
    kind: Literal["directory", "file"]
    parent_path: str | None = None
    size_bytes: int | None = None


class SkillFileTreeResponse(BaseModel):
    """Direct directory listing for one skill bundle path."""

    root_path: str
    entries: list[SkillFileTreeEntryResponse]


class SkillFileContentResponse(BaseModel):
    """Text content for one skill file."""

    path: str
    content: str
    encoding: Literal["utf-8"] = "utf-8"


class SkillArchiveImportJobResponse(BaseModel):
    """Response returned after creating a skill archive import job."""

    job_id: str


class SkillAccessUpdate(BaseModel):
    """Payload for replacing one skill's selected access."""

    use_scope: Literal["all", "selected"] = "all"
    use_user_ids: list[int] = Field(default_factory=list)
    use_group_ids: list[int] = Field(default_factory=list)
    edit_user_ids: list[int] = Field(default_factory=list)
    edit_group_ids: list[int] = Field(default_factory=list)


class SkillAccessResponse(SkillAccessUpdate):
    """Direct use/edit grants for one skill."""

    skill_name: str


class SkillAccessUserOption(BaseModel):
    """Selectable user in a skill auth editor."""

    id: int
    username: str
    display_name: str | None
    email: str | None


class SkillAccessGroupOption(BaseModel):
    """Selectable group in a skill auth editor."""

    id: int
    name: str
    description: str
    member_count: int


class SkillAccessOptionsResponse(BaseModel):
    """Selectable users and groups for a skill auth editor."""

    users: list[SkillAccessUserOption]
    groups: list[SkillAccessGroupOption]


def _grant_principal_ids(
    grants: list[ResourceAccess],
    principal_type: PrincipalType,
) -> list[int]:
    """Return integer principal IDs for one principal type."""
    principal_ids: list[int] = []
    for grant in grants:
        if grant.principal_type == principal_type:
            principal_ids.append(int(grant.principal_id))
    return sorted(principal_ids)


def _serialize_skill_access(
    skill_name: str,
    use_scope: str,
    grants: list[ResourceAccess],
) -> SkillAccessResponse:
    """Serialize direct grants for one skill."""
    use_grants = [grant for grant in grants if grant.access_level == AccessLevel.USE]
    edit_grants = [grant for grant in grants if grant.access_level == AccessLevel.EDIT]
    return SkillAccessResponse(
        skill_name=skill_name,
        use_scope="selected" if use_scope == "selected" else "all",
        use_user_ids=_grant_principal_ids(use_grants, PrincipalType.USER),
        use_group_ids=_grant_principal_ids(use_grants, PrincipalType.GROUP),
        edit_user_ids=_grant_principal_ids(edit_grants, PrincipalType.USER),
        edit_group_ids=_grant_principal_ids(edit_grants, PrincipalType.GROUP),
    )


def _serialize_skill_access_options(db: Session) -> SkillAccessOptionsResponse:
    """Serialize selectable users and groups for one skill access editor."""
    group_service = GroupService(db)
    member_counts = group_service.get_member_count_by_group_id()
    return SkillAccessOptionsResponse(
        users=[
            SkillAccessUserOption(
                id=user.id or 0,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
            )
            for user in UserService(db).list_users()
            if user.id is not None and user.status == "active"
        ],
        groups=[
            SkillAccessGroupOption(
                id=group.id or 0,
                name=group.name,
                description=group.description,
                member_count=member_counts.get(group.id or 0, 0),
            )
            for group in group_service.list_groups()
            if group.id is not None
        ],
    )


@router.get("/skills/access-options", response_model=SkillAccessOptionsResponse)
async def get_skill_create_access_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillAccessOptionsResponse:
    """Return selectable principals for a new skill access editor."""
    return _serialize_skill_access_options(db)


@router.get("/skills/usable")
async def get_usable_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[dict[str, Any]]:
    """List skills the current Studio user can select for agents."""
    return list_visible_skills(db, current_user.username)


@router.get("/skills/manage")
async def get_manageable_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> list[dict[str, Any]]:
    """List skills visible in the Studio management page."""
    return list_visible_skills(db, current_user.username)


@router.post("/skills")
async def create_skill(
    body: SkillCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Create one user-authored Skill with unified Auth defaults."""
    try:
        metadata = save_user_skill_source(
            db,
            current_user,
            body.skill_name,
            body.source,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": body.skill_name, "status": "ok", "metadata": metadata}


@router.get(
    "/skills/{skill_name}/access-options",
    response_model=SkillAccessOptionsResponse,
)
async def get_skill_access_options(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillAccessOptionsResponse:
    """Return selectable principals for one skill access editor."""
    skill = get_skill_by_name(db, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    AccessService(db).require_resource_access(
        user=current_user,
        resource_type=ResourceType.SKILL,
        resource_id=skill.id,
        access_level=AccessLevel.EDIT,
        creator_user_id=skill.creator_id,
        use_scope=skill.use_scope,
    )
    return _serialize_skill_access_options(db)


@router.get("/skills/{skill_name}/access", response_model=SkillAccessResponse)
async def get_skill_access(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillAccessResponse:
    """Return direct use/edit grants for one skill."""
    skill = get_skill_by_name(db, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    AccessService(db).require_resource_access(
        user=current_user,
        resource_type=ResourceType.SKILL,
        resource_id=skill.id,
        access_level=AccessLevel.EDIT,
        creator_user_id=skill.creator_id,
        use_scope=skill.use_scope,
    )
    return _serialize_skill_access(
        skill_name=skill.name,
        use_scope=skill.use_scope,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.SKILL,
            resource_id=skill.id or 0,
        ),
    )


@router.put("/skills/{skill_name}/access", response_model=SkillAccessResponse)
async def update_skill_access(
    skill_name: str,
    payload: SkillAccessUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillAccessResponse:
    """Replace direct use/edit grants for one skill."""
    skill = get_skill_by_name(db, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    AccessService(db).require_resource_access(
        user=current_user,
        resource_type=ResourceType.SKILL,
        resource_id=skill.id,
        access_level=AccessLevel.EDIT,
        creator_user_id=skill.creator_id,
        use_scope=skill.use_scope,
    )
    try:
        set_skill_access(
            db,
            skill=skill,
            use_scope=payload.use_scope,
            use_user_ids=set(payload.use_user_ids),
            use_group_ids=set(payload.use_group_ids),
            edit_user_ids=set(payload.edit_user_ids),
            edit_group_ids=set(payload.edit_group_ids),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_skill_access(
        skill_name=skill.name,
        use_scope=skill.use_scope,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.SKILL,
            resource_id=skill.id or 0,
        ),
    )


@router.get("/skills/{skill_name}/files/tree", response_model=SkillFileTreeResponse)
async def get_skill_file_tree(
    skill_name: str,
    path: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillFileTreeResponse:
    """Return direct children for one visible skill directory."""
    try:
        entries = list_visible_skill_directory(
            db,
            current_user.username,
            skill_name,
            path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillFileTreeResponse(
        root_path=path or ".",
        entries=[
            SkillFileTreeEntryResponse(
                path=entry.path,
                name=entry.name,
                kind="directory" if entry.kind == "directory" else "file",
                parent_path=entry.parent_path,
                size_bytes=entry.size_bytes,
            )
            for entry in entries
        ],
    )


@router.get(
    "/skills/{skill_name}/files/content", response_model=SkillFileContentResponse
)
async def get_skill_file_content(
    skill_name: str,
    path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> SkillFileContentResponse:
    """Read one UTF-8 file from a visible skill directory."""
    try:
        content = read_visible_skill_file(db, current_user.username, skill_name, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Skill file is not valid UTF-8 text.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillFileContentResponse(path=path, content=content)


@router.put("/skills/{skill_name}/files/content")
async def update_skill_file_content(
    skill_name: str,
    payload: SkillFileWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Update one UTF-8 file inside an editable skill directory."""
    try:
        metadata = update_skill_file(
            db,
            current_user,
            skill_name,
            payload.path,
            payload.content,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UnicodeEncodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Skill file content must be valid UTF-8 text.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "metadata": metadata}


@router.post("/skills/{skill_name}/files/content")
async def create_skill_file_content(
    skill_name: str,
    payload: SkillFileCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Create one UTF-8 file inside an editable skill directory."""
    try:
        metadata = create_skill_file(
            db,
            current_user,
            skill_name,
            payload.path,
            payload.content,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except UnicodeEncodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Skill file content must be valid UTF-8 text.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "metadata": metadata}


@router.post("/skills/{skill_name}/files/directory")
async def create_skill_directory_path(
    skill_name: str,
    payload: SkillDirectoryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Create one directory inside an editable skill directory."""
    try:
        metadata = create_skill_directory(
            db,
            current_user,
            skill_name,
            payload.path,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "metadata": metadata}


@router.delete("/skills/{skill_name}/files/path")
async def delete_skill_file_path(
    skill_name: str,
    path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Delete one file or directory inside an editable skill directory."""
    try:
        metadata = delete_skill_path(db, current_user, skill_name, path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "metadata": metadata}


@router.get("/skills/{skill_name}/source")
async def get_skill_source(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Read one skill source when the current user has use access."""
    try:
        return read_visible_skill_source(db, current_user.username, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/skills/{skill_name}/source")
async def update_existing_skill_source(
    skill_name: str,
    body: SkillWriteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Update one existing skill source when the current user has edit access."""
    try:
        metadata = update_skill_source(db, current_user, skill_name, body.source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": skill_name, "status": "ok", "metadata": metadata}


@router.delete("/skills/{skill_name}")
async def delete_skill(
    skill_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, str]:
    """Delete one editable Skill."""
    skill = get_skill_by_name(db, skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    try:
        delete_skill_source(db, current_user, skill_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"name": skill_name, "status": "deleted"}


@router.post("/skills/import/bundle")
async def import_bundle_skill_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Install one skill archive uploaded from the local machine."""
    progress_service = get_skill_import_progress_service()
    job = progress_service.get_job(job_id=job_id, username=current_user.username)
    if job is None:
        raise HTTPException(status_code=404, detail="Skill import job not found.")
    if job.completed:
        raise HTTPException(status_code=409, detail="Skill import job is already done.")

    form_data = await request.form(max_files=1, max_fields=3)
    upload = form_data.get("archive")
    if not isinstance(upload, StarletteUploadFile):
        raise HTTPException(status_code=422, detail="Archive file is required.")

    skill_name = form_data.get("skill_name")
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


@router.post("/skills/import/github/probe")
async def probe_github_skill(
    body: GitHubSkillProbeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
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
    current_user: User = Depends(permissions(Permission.SKILLS_MANAGE)),
) -> dict[str, Any]:
    """Install one skill folder from a public GitHub repository."""
    try:
        metadata = install_github_skill(
            db,
            current_user,
            github_url=body.github_url,
            ref=body.ref,
            ref_type=body.ref_type,
            remote_directory_name=body.remote_directory_name,
            skill_name=body.skill_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "imported", "metadata": metadata}
