"""API endpoints for LLM management.

This module provides CRUD operations for LLMs (Large Language Models).
All endpoints require authentication.
"""

import logging
from datetime import timezone
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.llm import llm as llm_crud
from app.models.user import User
from app.schemas.schemas import LLMCreate, LLMResponse, LLMUpdate
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/llms", response_model=list[LLMResponse])
async def get_llms(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get all LLMs with pagination.

    Args:
        skip: Number of LLMs to skip.
        limit: Maximum number of LLMs to return.
        db: Database session.

    Returns:
        A list of LLMs.
    """
    llms = llm_crud.get_all(db, skip=skip, limit=limit)
    return [
        {
            "id": llm.id,
            "name": llm.name,
            "endpoint": llm.endpoint,
            "model": llm.model,
            "api_key": llm.api_key,
            "protocol": llm.protocol,
            "chat": llm.chat,
            "system_role": llm.system_role,
            "tool_calling": llm.tool_calling,
            "json_schema": llm.json_schema,
            "streaming": llm.streaming,
            "max_context": llm.max_context,
            "extra_config": llm.extra_config,
            "created_at": llm.created_at.replace(tzinfo=timezone.utc).isoformat(),
            "updated_at": llm.updated_at.replace(tzinfo=timezone.utc).isoformat(),
        }
        for llm in llms
    ]


@router.post("/llms", response_model=LLMResponse, status_code=201)
async def create_llm(
    llm_data: LLMCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new LLM.

    Args:
        llm_data: LLM creation data.
        db: Database session.

    Returns:
        The created LLM with ID populated.

    Raises:
        HTTPException: If an LLM with the same name already exists (400).
    """
    existing_llm = llm_crud.get_by_name(llm_data.name, db)
    if existing_llm:
        raise HTTPException(status_code=400, detail="LLM with this name already exists")

    llm = llm_crud.create(
        db,
        name=llm_data.name,
        endpoint=llm_data.endpoint,
        model=llm_data.model,
        api_key=llm_data.api_key,
        protocol=llm_data.protocol,
        chat=llm_data.chat,
        system_role=llm_data.system_role,
        tool_calling=llm_data.tool_calling,
        json_schema=llm_data.json_schema,
        streaming=llm_data.streaming,
        max_context=llm_data.max_context,
        extra_config=llm_data.extra_config,
    )
    return {
        "id": llm.id,
        "name": llm.name,
        "endpoint": llm.endpoint,
        "model": llm.model,
        "api_key": llm.api_key,
        "protocol": llm.protocol,
        "chat": llm.chat,
        "system_role": llm.system_role,
        "tool_calling": llm.tool_calling,
        "json_schema": llm.json_schema,
        "streaming": llm.streaming,
        "max_context": llm.max_context,
        "extra_config": llm.extra_config,
        "created_at": llm.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": llm.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@router.get("/llms/{llm_id}", response_model=LLMResponse)
async def get_llm(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single LLM by ID.

    Args:
        llm_id: The ID of the LLM to retrieve.
        db: Database session.

    Returns:
        The LLM details.

    Raises:
        HTTPException: If the LLM is not found (404).
    """
    llm = llm_crud.get(llm_id, db)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    return {
        "id": llm.id,
        "name": llm.name,
        "endpoint": llm.endpoint,
        "model": llm.model,
        "api_key": llm.api_key,
        "protocol": llm.protocol,
        "chat": llm.chat,
        "system_role": llm.system_role,
        "tool_calling": llm.tool_calling,
        "json_schema": llm.json_schema,
        "streaming": llm.streaming,
        "max_context": llm.max_context,
        "extra_config": llm.extra_config,
        "created_at": llm.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": llm.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@router.put("/llms/{llm_id}", response_model=LLMResponse)
async def update_llm(
    llm_id: int,
    llm_data: LLMUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update an existing LLM.

    Args:
        llm_id: The ID of the LLM to update.
        llm_data: LLM update data containing optional fields to update.
        db: Database session.

    Returns:
        The updated LLM.

    Raises:
        HTTPException: If the LLM is not found (404) or if the new name already exists (400).
    """
    llm = llm_crud.get(llm_id, db)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    # Check if name change conflicts with existing LLM
    if llm_data.name and llm_data.name != llm.name:
        existing_llm = llm_crud.get_by_name(llm_data.name, db)
        if existing_llm:
            raise HTTPException(
                status_code=400, detail="LLM with this name already exists"
            )

    # Update only provided fields
    update_data: dict[str, Any] = {}
    if llm_data.name is not None:
        update_data["name"] = llm_data.name
    if llm_data.endpoint is not None:
        update_data["endpoint"] = llm_data.endpoint
    if llm_data.model is not None:
        update_data["model"] = llm_data.model
    if llm_data.api_key is not None:
        update_data["api_key"] = llm_data.api_key
    if llm_data.protocol is not None:
        update_data["protocol"] = llm_data.protocol
    if llm_data.chat is not None:
        update_data["chat"] = llm_data.chat
    if llm_data.system_role is not None:
        update_data["system_role"] = llm_data.system_role
    if llm_data.tool_calling is not None:
        update_data["tool_calling"] = llm_data.tool_calling
    if llm_data.json_schema is not None:
        update_data["json_schema"] = llm_data.json_schema
    if llm_data.streaming is not None:
        update_data["streaming"] = llm_data.streaming
    if llm_data.max_context is not None:
        update_data["max_context"] = llm_data.max_context
    if llm_data.extra_config is not None:
        update_data["extra_config"] = llm_data.extra_config

    updated_llm = llm_crud.update(llm_id, db, **update_data)
    if not updated_llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    return {
        "id": updated_llm.id,
        "name": updated_llm.name,
        "endpoint": updated_llm.endpoint,
        "model": updated_llm.model,
        "api_key": updated_llm.api_key,
        "protocol": updated_llm.protocol,
        "chat": updated_llm.chat,
        "system_role": updated_llm.system_role,
        "tool_calling": updated_llm.tool_calling,
        "json_schema": updated_llm.json_schema,
        "streaming": updated_llm.streaming,
        "max_context": updated_llm.max_context,
        "extra_config": updated_llm.extra_config,
        "created_at": updated_llm.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": updated_llm.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


@router.delete("/llms/{llm_id}", status_code=204)
async def delete_llm(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an LLM.

    Args:
        llm_id: The ID of the LLM to delete.
        db: Database session.

    Raises:
        HTTPException: If the LLM is not found (404).
    """
    llm = llm_crud.get(llm_id, db)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    llm_crud.delete(llm_id, db)
    # Explicitly return None to ensure empty body for 204
    return None
