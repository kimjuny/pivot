"""API endpoints for LLM management.

This module provides CRUD operations for LLMs (Large Language Models).
All endpoints require authentication.
"""

from datetime import UTC
from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.llm import llm as llm_crud
from app.llm.cache_policy import validate_cache_policy
from app.llm.thinking_policy import validate_thinking_policy
from app.models.user import User
from app.schemas.schemas import LLMCreate, LLMResponse, LLMUpdate
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

router = APIRouter()


def _serialize_llm(llm: Any) -> dict[str, Any]:
    """Convert one LLM row into the public API payload shape."""
    return {
        "id": llm.id,
        "name": llm.name,
        "endpoint": llm.endpoint,
        "model": llm.model,
        "api_key": llm.api_key,
        "protocol": llm.protocol,
        "cache_policy": llm.cache_policy,
        "thinking_policy": llm.thinking_policy,
        "thinking_effort": llm.thinking_effort,
        "thinking_budget_tokens": llm.thinking_budget_tokens,
        "streaming": llm.streaming,
        "image_input": llm.image_input,
        "image_output": llm.image_output,
        "max_context": llm.max_context,
        "extra_config": llm.extra_config,
        "created_at": llm.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": llm.updated_at.replace(tzinfo=UTC).isoformat(),
    }


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
    return [_serialize_llm(llm) for llm in llms]


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

    try:
        normalized_cache_policy = validate_cache_policy(
            llm_data.protocol,
            llm_data.cache_policy,
        )
        (
            normalized_thinking_policy,
            normalized_thinking_effort,
            normalized_thinking_budget_tokens,
        ) = validate_thinking_policy(
            llm_data.protocol,
            llm_data.thinking_policy,
            llm_data.thinking_effort,
            llm_data.thinking_budget_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    llm = llm_crud.create(
        db,
        name=llm_data.name,
        endpoint=llm_data.endpoint,
        model=llm_data.model,
        api_key=llm_data.api_key,
        protocol=llm_data.protocol,
        cache_policy=normalized_cache_policy,
        thinking_policy=normalized_thinking_policy,
        thinking_effort=normalized_thinking_effort,
        thinking_budget_tokens=normalized_thinking_budget_tokens,
        streaming=llm_data.streaming,
        image_input=llm_data.image_input,
        image_output=llm_data.image_output,
        max_context=llm_data.max_context,
        extra_config=llm_data.extra_config,
    )
    return _serialize_llm(llm)


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

    return _serialize_llm(llm)


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
    if llm_data.cache_policy is not None:
        update_data["cache_policy"] = llm_data.cache_policy
    if llm_data.thinking_policy is not None:
        update_data["thinking_policy"] = llm_data.thinking_policy
    if "thinking_effort" in llm_data.__fields_set__:
        update_data["thinking_effort"] = llm_data.thinking_effort
    if "thinking_budget_tokens" in llm_data.__fields_set__:
        update_data["thinking_budget_tokens"] = llm_data.thinking_budget_tokens

    # Ensure protocol/thinking/cache combinations remain valid after partial update.
    target_protocol = update_data.get("protocol", llm.protocol)
    target_cache_policy = update_data.get("cache_policy", llm.cache_policy)
    target_thinking_policy = update_data.get("thinking_policy", llm.thinking_policy)
    target_thinking_effort = update_data.get("thinking_effort", llm.thinking_effort)
    target_thinking_budget_tokens = update_data.get(
        "thinking_budget_tokens",
        llm.thinking_budget_tokens,
    )
    try:
        update_data["cache_policy"] = validate_cache_policy(
            target_protocol,
            target_cache_policy,
        )
        (
            update_data["thinking_policy"],
            update_data["thinking_effort"],
            update_data["thinking_budget_tokens"],
        ) = validate_thinking_policy(
            target_protocol,
            target_thinking_policy,
            target_thinking_effort,
            target_thinking_budget_tokens,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if llm_data.streaming is not None:
        update_data["streaming"] = llm_data.streaming
    if llm_data.image_input is not None:
        update_data["image_input"] = llm_data.image_input
    if llm_data.image_output is not None:
        update_data["image_output"] = llm_data.image_output
    if llm_data.max_context is not None:
        update_data["max_context"] = llm_data.max_context
    if "extra_config" in llm_data.__fields_set__:
        # Allow explicit clearing: payload ``extra_config: ""`` is normalized to
        # None by schema validation and must still persist as NULL in DB.
        update_data["extra_config"] = llm_data.extra_config

    updated_llm = llm_crud.update(llm_id, db, **update_data)
    if not updated_llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    return _serialize_llm(updated_llm)


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
