"""API endpoints for agent management.

This module provides read-only operations for agents.
All CRUD operations (create, update, delete) are not used by the frontend.
"""
import logging

from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.schemas.schemas import AgentResponse
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/agents", response_model=list[AgentResponse])
async def get_agents(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all agents with pagination.

    Args:
        skip: Number of agents to skip.
        limit: Maximum number of agents to return.
        db: Database session.

    Returns:
        A list of agents.
    """
    agents = agent_crud.get_all(db, skip=skip, limit=limit)
    return [AgentResponse.from_orm(agent) for agent in agents]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: int,
    db: Session = Depends(get_db)
):
    """Get a single agent by ID.

    Args:
        agent_id: The ID of the agent to retrieve.
        db: Database session.

    Returns:
        The agent if found.

    Raises:
        HTTPException: If the agent is not found (404).
    """
    agent = agent_crud.get(agent_id, db)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.from_orm(agent)
