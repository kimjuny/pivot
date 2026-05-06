"""API endpoints for channel catalog, bindings, linking, and webhook ingress."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel
from app.models.channel import AgentChannelBinding
from app.schemas.channel import (
    ChannelBindingCreate,
    ChannelBindingResponse,
    ChannelBindingTestRequest,
    ChannelBindingUpdate,
    ChannelCatalogItemResponse,
    ChannelLinkCompletionResponse,
    ChannelLinkTokenStatusResponse,
    ChannelTestResponse,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.agent_service import AgentService
from app.services.agent_snapshot_service import AgentSnapshotService
from app.services.channel_service import ChannelService
from app.services.provider_registry_service import ProviderRegistryService
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from sqlmodel import Session


def _require_agent_edit(db: Session, agent_id: int, current_user: User) -> Agent:
    """Return one agent after checking channel-management edit access."""
    try:
        agent = AgentService(db).get_required_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found") from exc
    AccessService(db).require_agent_access(
        user=current_user,
        agent=agent,
        access_level=AccessLevel.EDIT,
    )
    return agent


def _require_channel_binding_edit(
    db: Session,
    binding_id: int,
    current_user: User,
) -> AgentChannelBinding:
    """Return one channel binding after checking its parent agent edit access."""
    binding = db.get(AgentChannelBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Channel binding not found")
    _require_agent_edit(db, binding.agent_id, current_user)
    return binding


@router.get("/channels", response_model=list[ChannelCatalogItemResponse])
async def list_channels(
    agent_id: int | None = None,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> list[dict[str, object]]:
    """List all channel manifests available to the current Studio user."""
    if agent_id is not None:
        _require_agent_edit(db, agent_id, current_user)
    return ChannelService(db).list_catalog(agent_id, user=current_user)


@router.get("/channels/{channel_key}", response_model=ChannelCatalogItemResponse)
async def get_channel(
    channel_key: str,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> dict[str, object]:
    """Return one channel manifest by provider key."""
    service = ChannelService(db)
    try:
        provider = ProviderRegistryService(db).get_channel_provider(channel_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Channel not found") from exc
    if not service.is_provider_usable_by_user(user=current_user, provider=provider):
        raise HTTPException(status_code=404, detail="Channel not found")
    return {"manifest": provider.manifest.model_dump()}


@router.get(
    "/agents/{agent_id}/channels",
    response_model=list[ChannelBindingResponse],
)
async def list_agent_channels(
    agent_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> list[ChannelBindingResponse]:
    """List the channel bindings configured for one agent."""
    _require_agent_edit(db, agent_id, current_user)
    return ChannelService(db).list_agent_bindings(agent_id)


@router.post(
    "/agents/{agent_id}/channels",
    response_model=ChannelBindingResponse,
    status_code=201,
)
async def create_agent_channel(
    agent_id: int,
    payload: ChannelBindingCreate,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> ChannelBindingResponse:
    """Create one channel binding for an agent."""
    _require_agent_edit(db, agent_id, current_user)
    try:
        binding = ChannelService(db).create_binding(
            agent_id=agent_id,
            channel_key=payload.channel_key,
            name=payload.name,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
            user=current_user,
        )
        AgentSnapshotService(db).save_draft(
            agent_id,
            saved_by=current_user.username,
        )
        return binding
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Channel provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/agent-channels/{binding_id}", response_model=ChannelBindingResponse)
async def update_agent_channel(
    binding_id: int,
    payload: ChannelBindingUpdate,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> ChannelBindingResponse:
    """Update one configured agent channel binding."""
    binding_row = _require_channel_binding_edit(db, binding_id, current_user)
    try:
        binding = ChannelService(db).update_binding(
            binding_id,
            name=payload.name,
            enabled=payload.enabled,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
        )
        AgentSnapshotService(db).save_draft(
            binding_row.agent_id,
            saved_by=current_user.username,
        )
        return binding
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/agent-channels/{binding_id}", status_code=204)
async def delete_agent_channel(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> Response:
    """Delete one configured channel binding."""
    binding = _require_channel_binding_edit(db, binding_id, current_user)
    try:
        ChannelService(db).delete_binding(binding_id)
        AgentSnapshotService(db).save_draft(
            binding.agent_id,
            saved_by=current_user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/agent-channels/{binding_id}/test", response_model=ChannelTestResponse)
async def test_agent_channel(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test."""
    binding = _require_channel_binding_edit(db, binding_id, current_user)

    provider = ProviderRegistryService(db).get_channel_provider(binding.channel_key)
    result = await run_in_threadpool(
        provider.test_connection,
        json.loads(binding.auth_config or "{}"),
        json.loads(binding.runtime_config or "{}"),
        binding_id,
    )
    binding.last_health_status = result.status
    binding.last_health_message = result.message
    binding.last_health_check_at = datetime.now(UTC)
    binding.updated_at = binding.last_health_check_at
    db.add(binding)
    db.commit()
    return {"result": result.model_dump()}


@router.post("/channels/{channel_key}/test", response_model=ChannelTestResponse)
async def test_channel_draft(
    channel_key: str,
    payload: ChannelBindingTestRequest,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> dict[str, object]:
    """Run one provider-specific connection test for unsaved form values."""
    try:
        return ChannelService(db).test_binding_draft(
            channel_key=channel_key,
            auth_config=payload.auth_config,
            runtime_config=payload.runtime_config,
            user=current_user,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Channel provider not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/agent-channels/{binding_id}/poll")
async def poll_agent_channel_once(
    binding_id: int,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CHANNELS_MANAGE)),
) -> dict[str, object]:
    """Manually poll a polling-based channel binding once."""
    _require_channel_binding_edit(db, binding_id, current_user)
    try:
        return await ChannelService(db).poll_binding_once(binding_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/channel-link/{token}",
    response_model=ChannelLinkTokenStatusResponse,
)
async def get_channel_link_status(
    token: str,
    db=Depends(get_db),
) -> ChannelLinkTokenStatusResponse:
    """Return public metadata for a channel link token."""
    try:
        return ChannelService(db).get_link_token_status(token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/channel-link/{token}/complete",
    response_model=ChannelLinkCompletionResponse,
)
async def complete_channel_link(
    token: str,
    db=Depends(get_db),
    current_user=Depends(permissions(Permission.CLIENT_ACCESS)),
) -> ChannelLinkCompletionResponse:
    """Bind an external identity to the current authenticated user."""
    try:
        return ChannelService(db).complete_link_token(token, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.api_route(
    "/channel-endpoints/{binding_id}/webhook",
    methods=["GET", "POST"],
    response_model=None,
)
async def channel_webhook(
    binding_id: int,
    request: Request,
    db=Depends(get_db),
) -> Response:
    """Receive one inbound webhook request and route text events to the agent."""
    binding = db.get(AgentChannelBinding, binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="Channel binding not found")
    if not binding.enabled:
        raise HTTPException(status_code=409, detail="Channel binding is disabled")

    provider = ProviderRegistryService(db).get_channel_provider(binding.channel_key)
    auth_config = json.loads(binding.auth_config or "{}")
    runtime_config = json.loads(binding.runtime_config or "{}")
    raw_body = await request.body()
    try:
        result = provider.handle_webhook(
            auth_config,
            runtime_config,
            method=request.method,
            query_params=dict(request.query_params),
            headers=dict(request.headers),
            body=raw_body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.inbound_event is not None:
        channel_service = ChannelService(db)
        existing_log = None
        if result.inbound_event.external_event_id:
            existing_log = channel_service.get_event_log(
                channel_binding_id=binding_id,
                external_event_id=result.inbound_event.external_event_id,
                direction="inbound",
            )
        if existing_log is not None:
            if result.body_json is not None:
                return JSONResponse(
                    status_code=result.status_code, content=result.body_json
                )
            return PlainTextResponse(
                status_code=result.status_code,
                content=result.body_text or "success",
                media_type=result.content_type,
            )

        event_log = channel_service.create_event_log(
            channel_binding_id=binding_id,
            external_event_id=result.inbound_event.external_event_id,
            direction="inbound",
            status="received",
            payload=result.inbound_event.model_dump(),
        )
        context = channel_service.build_message_context(event=result.inbound_event)
        try:
            async for action in channel_service.stream_inbound_actions(
                binding=binding,
                event=result.inbound_event,
            ):
                if context.conversation_id is None or not action.text.strip():
                    continue
                provider.send_action(
                    auth_config,
                    runtime_config,
                    context=context,
                    action=action,
                )
                channel_service.create_event_log(
                    channel_binding_id=binding_id,
                    external_event_id=result.inbound_event.external_event_id,
                    direction="outbound",
                    status="sent",
                    payload={
                        "conversation_id": context.conversation_id,
                        "external_user_id": context.user_id,
                        "action": action.model_dump(),
                    },
                )
        except Exception as exc:
            channel_service.update_event_log(
                event_log,
                status="failed",
                error_message=str(exc),
            )
            raise HTTPException(
                status_code=502,
                detail=f"Failed to deliver outbound channel reply: {exc!s}",
            ) from exc
        channel_service.update_event_log(event_log, status="processed")

    if result.body_json is not None:
        return JSONResponse(status_code=result.status_code, content=result.body_json)
    return PlainTextResponse(
        status_code=result.status_code,
        content=result.body_text or "success",
        media_type=result.content_type,
    )
