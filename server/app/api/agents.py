"""API endpoints for agent management.

This module provides CRUD operations for agents.
"""
import logging
from datetime import timezone

from app.api.dependencies import get_db
from app.crud.agent import agent as agent_crud
from app.schemas.schemas import AgentCreate, AgentResponse
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
    return [
        {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "model_name": agent.model_name,
            "is_active": agent.is_active,
            "created_at": agent.created_at.replace(tzinfo=timezone.utc).isoformat(),
            "updated_at": agent.updated_at.replace(tzinfo=timezone.utc).isoformat()
        }
        for agent in agents
    ]


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def create_agent(
    agent_data: AgentCreate,
    db: Session = Depends(get_db)
):
    """Create a new agent.

    Args:
        agent_data: Agent creation data containing name, description, and model_name.
        db: Database session.

    Returns:
        The created agent with ID populated.

    Raises:
        HTTPException: If an agent with the same name already exists (400).
    """
    existing_agent = agent_crud.get_by_name(agent_data.name, db)
    if existing_agent:
        raise HTTPException(status_code=400, detail="Agent with this name already exists")

    agent = agent_crud.create(
        db,
        name=agent_data.name,
        description=agent_data.description,
        model_name=agent_data.model_name,
        is_active=agent_data.is_active
    )
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "model_name": agent.model_name,
        "is_active": agent.is_active,
        "created_at": agent.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": agent.updated_at.replace(tzinfo=timezone.utc).isoformat()
    }


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
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "model_name": agent.model_name,
        "is_active": agent.is_active,
        "created_at": agent.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": agent.updated_at.replace(tzinfo=timezone.utc).isoformat()
    }
