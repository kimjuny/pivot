"""API endpoints for agent delegation configuration."""

import logging

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.agent import Agent
from app.models.user import User
from app.schemas.delegation import (
    DelegationCreate,
    DelegationReplaceRequest,
    DelegationResponse,
    DelegationUpdate,
)
from app.security.permission_catalog import Permission
from app.services.agent_delegation_service import AgentDelegationService
from app.services.agent_service import AgentService
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

logger = logging.getLogger(__name__)

router = APIRouter()


def _enrich_response(delegation: object, db: Session) -> DelegationResponse:
    """Build a DelegationResponse with joined callee agent data."""
    resp = DelegationResponse.model_validate(delegation)
    callee = db.get(Agent, resp.callee_agent_id)
    if callee is not None:
        resp.callee_name = callee.name
        resp.callee_description = callee.description
        resp.callee_llm_id = callee.llm_id
    return resp


@router.get("/agents/{agent_id}/delegations", response_model=list[DelegationResponse])
async def list_delegations(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[DelegationResponse]:
    """List all delegations configured for an agent."""
    _ = current_user
    service = AgentDelegationService(db)
    delegations = service.list_by_caller(agent_id)
    return [_enrich_response(d, db) for d in delegations]


@router.post(
    "/agents/{agent_id}/delegations",
    response_model=DelegationResponse,
    status_code=201,
)
async def create_delegation(
    agent_id: int,
    data: DelegationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> DelegationResponse:
    """Create a new delegation for an agent."""
    _ = current_user

    agent_service = AgentService(db)
    agent = agent_service.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    callee = agent_service.get_agent(data.callee_agent_id)
    if callee is None:
        raise HTTPException(status_code=404, detail="Callee agent not found")

    service = AgentDelegationService(db)
    try:
        delegation = service.create(
            caller_agent_id=agent_id,
            callee_agent_id=data.callee_agent_id,
            callee_alias=data.callee_alias,
            pass_mode=data.pass_mode,
            max_timeout_seconds=data.max_timeout_seconds,
            max_iterations_override=data.max_iterations_override,
            enabled=data.enabled,
            priority=data.priority,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return _enrich_response(delegation, db)


@router.put(
    "/agents/{agent_id}/delegations/{delegation_id}",
    response_model=DelegationResponse,
)
async def update_delegation(
    agent_id: int,
    delegation_id: int,
    data: DelegationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> DelegationResponse:
    """Update a delegation configuration."""
    _ = current_user

    service = AgentDelegationService(db)
    delegation = service.get_by_id(delegation_id)
    if delegation is None or delegation.caller_agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Delegation not found")

    update_fields = data.model_dump(exclude_none=True)
    if not update_fields:
        return _enrich_response(delegation, db)

    try:
        delegation = service.update(delegation_id, **update_fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return _enrich_response(delegation, db)


@router.delete(
    "/agents/{agent_id}/delegations/{delegation_id}",
    status_code=204,
)
async def delete_delegation(
    agent_id: int,
    delegation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> None:
    """Delete a delegation configuration."""
    _ = current_user

    service = AgentDelegationService(db)
    delegation = service.get_by_id(delegation_id)
    if delegation is None or delegation.caller_agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Delegation not found")

    service.delete(delegation_id)


@router.put(
    "/agents/{agent_id}/delegations",
    response_model=list[DelegationResponse],
)
async def replace_delegations(
    agent_id: int,
    data: DelegationReplaceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
) -> list[DelegationResponse]:
    """Atomically replace all delegations for an agent."""
    _ = current_user

    agent_service = AgentService(db)
    agent = agent_service.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    items = [d.model_dump() for d in data.delegations]
    service = AgentDelegationService(db)
    try:
        delegations = service.replace_delegations(agent_id, items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return [_enrich_response(d, db) for d in delegations]
