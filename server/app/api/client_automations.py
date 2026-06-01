"""Client-facing API endpoints for automation management."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Any

from app.api.permissions import permissions
from app.schemas.automation import (
    AutomationCreateRequest,
    AutomationResponse,
    AutomationRunResponse,
    AutomationUpdateRequest,
)
from app.security.permission_catalog import Permission
from app.services.automation_service import AutomationService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import col

from .dependencies import get_db

if TYPE_CHECKING:
    from app.models.automation import Automation, AutomationRun
    from app.models.user import User
    from sqlmodel import Session as DbSession

router = APIRouter()


def _serialize_automation(
    automation: Automation,
    *,
    channel_info: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Serialize an Automation row into the API response shape."""
    return {
        "id": automation.id,
        "automation_id": automation.automation_id,
        "name": automation.name,
        "agent_id": automation.agent_id,
        "release_id": automation.release_id,
        "trigger_type": automation.trigger_type,
        "trigger_config": automation.trigger_config,
        "prompt_template": automation.prompt_template,
        "session_strategy": automation.session_strategy,
        "status": automation.status,
        "max_iterations": automation.max_iterations,
        "timeout_seconds": automation.timeout_seconds,
        "notify_on_completion": automation.notify_on_completion,
        "notify_on_failure": automation.notify_on_failure,
        "channel_session_id": automation.channel_session_id,
        "channel_key": channel_info["channel_key"] if channel_info else None,
        "channel_name": channel_info["channel_name"] if channel_info else None,
        "channel_logo_url": (
            channel_info["channel_logo_url"] if channel_info else None
        ),
        "last_run_at": (
            automation.last_run_at.replace(tzinfo=UTC).isoformat()
            if automation.last_run_at
            else None
        ),
        "next_run_at": (
            automation.next_run_at.replace(tzinfo=UTC).isoformat()
            if automation.next_run_at
            else None
        ),
        "created_at": automation.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": automation.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def _serialize_run(
    run: AutomationRun, *, session_uuid_map: dict[int, str] | None = None
) -> dict[str, Any]:
    """Serialize an AutomationRun row into the API response shape."""
    return {
        "id": run.id,
        "run_id": run.run_id,
        "automation_id": run.automation_id,
        "scheduled_at": run.scheduled_at.replace(tzinfo=UTC).isoformat(),
        "session_id": run.session_id,
        "session_uuid": (
            session_uuid_map.get(run.session_id)
            if session_uuid_map and run.session_id is not None
            else None
        ),
        "task_id": run.task_id,
        "status": run.status,
        "started_at": (
            run.started_at.replace(tzinfo=UTC).isoformat() if run.started_at else None
        ),
        "finished_at": (
            run.finished_at.replace(tzinfo=UTC).isoformat() if run.finished_at else None
        ),
        "result_summary": run.result_summary,
        "error_message": run.error_message,
        "token_usage": run.token_usage,
        "delivery_status": run.delivery_status,
        "delivery_error": run.delivery_error,
    }


def _build_session_uuid_map(db: DbSession, session_ids: list[int]) -> dict[int, str]:
    """Look up string session_id values for a list of integer session PKs."""
    if not session_ids:
        return {}
    from app.models.session import Session as SessionModel
    from sqlmodel import select

    rows = db.exec(
        select(SessionModel).where(col(SessionModel.id).in_(session_ids))
    ).all()
    return {r.id: r.session_id for r in rows if r.id is not None}


class AutomationListResponse(BaseModel):
    """Paginated automation list."""

    automations: list[AutomationResponse]
    total: int


class AutomationRunListResponse(BaseModel):
    """Paginated automation run list."""

    runs: list[AutomationRunResponse]
    total: int


class AutomationStatsResponse(BaseModel):
    """Aggregated automation statistics for the current user."""

    total_automations: int
    active_count: int
    paused_count: int
    runs_last_7_days: int
    success_rate: float
    total_tokens_last_7_days: int


@router.get("/client/automations/stats", response_model=AutomationStatsResponse)
async def get_automation_stats(
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationStatsResponse:
    """Return aggregated automation statistics for the current user."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    stats = svc.get_user_stats(current_user.id)
    return AutomationStatsResponse(
        total_automations=int(stats["total_automations"]),
        active_count=int(stats["active_count"]),
        paused_count=int(stats["paused_count"]),
        runs_last_7_days=int(stats["runs_last_7_days"]),
        success_rate=float(stats["success_rate"]),
        total_tokens_last_7_days=int(stats["total_tokens_last_7_days"]),
    )


@router.get("/client/automations", response_model=AutomationListResponse)
async def list_automations(
    status: str | None = None,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationListResponse:
    """List the current user's automations."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automations = svc.list_automations(current_user.id, status=status)
    channel_info_map = svc.get_channel_info_by_session_ids(
        [
            automation.channel_session_id
            for automation in automations
            if automation.channel_session_id is not None
        ],
    )
    return AutomationListResponse(
        automations=[
            AutomationResponse(
                **_serialize_automation(
                    automation,
                    channel_info=channel_info_map.get(automation.channel_session_id)
                    if automation.channel_session_id is not None
                    else None,
                )
            )
            for automation in automations
        ],
        total=len(automations),
    )


@router.post("/client/automations", response_model=AutomationResponse)
async def create_automation(
    request: AutomationCreateRequest,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationResponse:
    """Create a new automation."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    try:
        automation = svc.create_automation(
            owner_id=current_user.id,
            agent_id=request.agent_id,
            name=request.name,
            prompt_template=request.prompt_template,
            trigger_config=request.trigger_config,
            session_strategy=request.session_strategy,
            max_iterations=request.max_iterations,
            timeout_seconds=request.timeout_seconds,
            notify_on_completion=request.notify_on_completion,
            notify_on_failure=request.notify_on_failure,
            channel_session_id=request.channel_session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    channel_info_map = svc.get_channel_info_by_session_ids(
        [automation.channel_session_id]
        if automation.channel_session_id is not None
        else [],
    )
    return AutomationResponse(
        **_serialize_automation(
            automation,
            channel_info=channel_info_map.get(automation.channel_session_id)
            if automation.channel_session_id is not None
            else None,
        )
    )


@router.get(
    "/client/automations/{automation_id}",
    response_model=AutomationResponse,
)
async def get_automation(
    automation_id: str,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationResponse:
    """Get a single automation by UUID."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    if automation.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    channel_info_map = svc.get_channel_info_by_session_ids(
        [automation.channel_session_id]
        if automation.channel_session_id is not None
        else [],
    )
    return AutomationResponse(
        **_serialize_automation(
            automation,
            channel_info=channel_info_map.get(automation.channel_session_id)
            if automation.channel_session_id is not None
            else None,
        )
    )


@router.put(
    "/client/automations/{automation_id}",
    response_model=AutomationResponse,
)
async def update_automation(
    automation_id: str,
    request: AutomationUpdateRequest,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationResponse:
    """Update an automation."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    assert automation.id is not None  # persisted via get_automation_by_uuid
    try:
        updated = svc.update_automation(
            automation.id,
            user_id=current_user.id,
            **request.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    channel_info_map = svc.get_channel_info_by_session_ids(
        [updated.channel_session_id] if updated.channel_session_id is not None else [],
    )
    return AutomationResponse(
        **_serialize_automation(
            updated,
            channel_info=channel_info_map.get(updated.channel_session_id)
            if updated.channel_session_id is not None
            else None,
        )
    )


@router.delete("/client/automations/{automation_id}")
async def delete_automation(
    automation_id: str,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> dict[str, str]:
    """Delete an automation."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    assert automation.id is not None  # persisted via get_automation_by_uuid
    try:
        svc.delete_automation(automation.id, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.get(
    "/client/automations/{automation_id}/runs",
    response_model=AutomationRunListResponse,
)
async def list_automation_runs(
    automation_id: str,
    limit: int = 50,
    offset: int = 0,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationRunListResponse:
    """List runs for an automation."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    assert automation.id is not None  # persisted via get_automation_by_uuid
    runs, total = svc.list_runs(
        automation.id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    session_ids = [r.session_id for r in runs if r.session_id]
    uuid_map = _build_session_uuid_map(db, session_ids)
    return AutomationRunListResponse(
        runs=[
            AutomationRunResponse(**_serialize_run(r, session_uuid_map=uuid_map))
            for r in runs
        ],
        total=total,
    )


@router.get(
    "/client/automations/{automation_id}/runs/{run_id}",
    response_model=AutomationRunResponse,
)
async def get_automation_run(
    automation_id: str,
    run_id: str,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationRunResponse:
    """Get a single automation run."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    assert automation.id is not None  # persisted via get_automation_by_uuid
    if automation.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    run = svc.get_run_by_uuid(run_id)
    if run is None or run.automation_id != automation.id:
        raise HTTPException(status_code=404, detail="Run not found")
    uuid_map = _build_session_uuid_map(db, [run.session_id] if run.session_id else [])
    return AutomationRunResponse(**_serialize_run(run, session_uuid_map=uuid_map))


@router.post(
    "/client/automations/{automation_id}/trigger",
    response_model=AutomationRunResponse,
)
async def trigger_automation(
    automation_id: str,
    db: DbSession = Depends(get_db),
    current_user: User = Depends(permissions(Permission.CLIENT_ACCESS)),
) -> AutomationRunResponse:
    """Manually trigger an automation run for testing."""
    if current_user.id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    svc = AutomationService(db)
    automation = svc.get_automation_by_uuid(automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    assert automation.id is not None  # persisted via get_automation_by_uuid
    if automation.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if automation.status != "active":
        raise HTTPException(status_code=400, detail="Automation is not active")

    from datetime import datetime

    run = svc.claim_run(
        automation_id=automation.id,
        scheduled_at=datetime.now(UTC),
    )
    if run is None:
        raise HTTPException(status_code=409, detail="A run is already in progress")

    import asyncio

    from app.services.automation_executor import execute_automation_run

    assert run.id is not None  # persisted via claim_run
    _bg_task = asyncio.create_task(execute_automation_run(run.id))  # noqa: RUF006

    return AutomationRunResponse(**_serialize_run(run))
