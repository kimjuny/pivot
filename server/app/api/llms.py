"""API endpoints for LLM management.

This module provides CRUD operations for LLMs (Large Language Models).
All endpoints require authentication.
"""

from datetime import UTC
from typing import Any, Literal, cast

from app.api.dependencies import get_db
from app.api.permissions import permissions
from app.models.access import AccessLevel, PrincipalType, ResourceAccess, ResourceType
from app.models.user import User
from app.schemas.schemas import (
    LLMAccessGroupOption,
    LLMAccessOptionsResponse,
    LLMAccessResponse,
    LLMAccessUpdate,
    LLMAccessUserOption,
    LLMCreate,
    LLMResponse,
    LLMUpdate,
    LLMUsableResponse,
)
from app.security.permission_catalog import Permission
from app.services.access_service import AccessService
from app.services.group_service import GroupService
from app.services.llm_service import LLMService
from app.services.user_service import UserService
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session

router = APIRouter()


def _serialize_llm(llm: Any) -> dict[str, Any]:
    """Convert one LLM row into the public API payload shape."""
    return {
        "id": llm.id,
        "name": llm.name,
        "created_by_user_id": llm.created_by_user_id,
        "use_scope": llm.use_scope,
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


def _serialize_usable_llm(llm: Any) -> dict[str, Any]:
    """Convert one LLM row into a safe Studio selector payload."""
    return {
        "id": llm.id,
        "name": llm.name,
        "model": llm.model,
        "protocol": llm.protocol,
        "streaming": llm.streaming,
        "image_input": llm.image_input,
        "image_output": llm.image_output,
        "max_context": llm.max_context,
    }


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


def _serialize_llm_access(
    llm_id: int,
    use_scope: str,
    grants: list[ResourceAccess],
) -> LLMAccessResponse:
    """Serialize direct grants for one LLM config."""
    use_grants = [grant for grant in grants if grant.access_level == AccessLevel.USE]
    edit_grants = [grant for grant in grants if grant.access_level == AccessLevel.EDIT]
    return LLMAccessResponse(
        llm_id=llm_id,
        use_scope=cast(Literal["all", "selected"], use_scope),
        use_user_ids=_grant_principal_ids(use_grants, PrincipalType.USER),
        use_group_ids=_grant_principal_ids(use_grants, PrincipalType.GROUP),
        edit_user_ids=_grant_principal_ids(edit_grants, PrincipalType.USER),
        edit_group_ids=_grant_principal_ids(edit_grants, PrincipalType.GROUP),
    )


def _serialize_llm_access_options(
    db: Session,
    users: list[User],
) -> LLMAccessOptionsResponse:
    """Serialize selectable users and groups for one LLM access editor."""
    group_service = GroupService(db)
    member_counts = group_service.get_member_count_by_group_id()
    return LLMAccessOptionsResponse(
        users=[
            LLMAccessUserOption(
                id=user.id or 0,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
            )
            for user in users
            if user.id is not None and user.status == "active"
        ],
        groups=[
            LLMAccessGroupOption(
                id=group.id or 0,
                name=group.name,
                description=group.description,
                member_count=member_counts.get(group.id or 0, 0),
            )
            for group in group_service.list_groups()
            if group.id is not None
        ],
    )


@router.get("/llms", response_model=list[LLMResponse])
async def get_llms(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
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
    llms = LLMService(db).list_llms(
        user=current_user,
        skip=skip,
        limit=limit,
    )
    return [_serialize_llm(llm) for llm in llms]


@router.get("/llms/access-options", response_model=LLMAccessOptionsResponse)
async def get_llm_create_access_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
) -> LLMAccessOptionsResponse:
    """Return selectable principals for a new LLM access editor."""
    return _serialize_llm_access_options(db, UserService(db).list_users())


@router.get("/llms/usable", response_model=list[LLMUsableResponse])
async def get_usable_llms(
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.AGENTS_MANAGE)),
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return safe LLM options the current Studio user can select for agents."""
    llms = LLMService(db).list_usable_llms(
        user=current_user,
        skip=skip,
        limit=limit,
    )
    return [_serialize_usable_llm(llm) for llm in llms]


@router.post("/llms", response_model=LLMResponse, status_code=201)
async def create_llm(
    llm_data: LLMCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
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
    try:
        llm = LLMService(db).create_llm(
            user=current_user,
            name=llm_data.name,
            endpoint=llm_data.endpoint,
            model=llm_data.model,
            api_key=llm_data.api_key,
            protocol=llm_data.protocol,
            cache_policy=llm_data.cache_policy,
            thinking_policy=llm_data.thinking_policy,
            thinking_effort=llm_data.thinking_effort,
            thinking_budget_tokens=llm_data.thinking_budget_tokens,
            streaming=llm_data.streaming,
            image_input=llm_data.image_input,
            image_output=llm_data.image_output,
            max_context=llm_data.max_context,
            extra_config=llm_data.extra_config,
            use_scope=llm_data.use_scope,
            use_user_ids=set(llm_data.use_user_ids),
            use_group_ids=set(llm_data.use_group_ids),
            edit_user_ids=set(llm_data.edit_user_ids),
            edit_group_ids=set(llm_data.edit_group_ids),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_llm(llm)


@router.get("/llms/{llm_id}", response_model=LLMResponse)
async def get_llm(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
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
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")
    service.require_llm_access(
        user=current_user,
        llm=llm,
        access_level=AccessLevel.EDIT,
    )

    return _serialize_llm(llm)


@router.get(
    "/llms/{llm_id}/access-options",
    response_model=LLMAccessOptionsResponse,
)
async def get_llm_access_options(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
) -> LLMAccessOptionsResponse:
    """Return selectable principals for one LLM access editor."""
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")
    service.require_llm_access(
        user=current_user,
        llm=llm,
        access_level=AccessLevel.EDIT,
    )
    return _serialize_llm_access_options(db, UserService(db).list_users())


@router.get("/llms/{llm_id}/access", response_model=LLMAccessResponse)
async def get_llm_access(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
) -> LLMAccessResponse:
    """Return direct use/edit grants for one LLM config."""
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")
    service.require_llm_access(
        user=current_user,
        llm=llm,
        access_level=AccessLevel.EDIT,
    )
    return _serialize_llm_access(
        llm_id=llm_id,
        use_scope=llm.use_scope,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.LLM,
            resource_id=llm_id,
        ),
    )


@router.put("/llms/{llm_id}/access", response_model=LLMAccessResponse)
async def update_llm_access(
    llm_id: int,
    payload: LLMAccessUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
) -> LLMAccessResponse:
    """Replace direct use/edit grants for one LLM config."""
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")
    service.require_llm_access(
        user=current_user,
        llm=llm,
        access_level=AccessLevel.EDIT,
    )
    service.set_llm_access(
        llm=llm,
        use_scope=payload.use_scope,
        use_user_ids=set(payload.use_user_ids),
        use_group_ids=set(payload.use_group_ids),
        edit_user_ids=set(payload.edit_user_ids),
        edit_group_ids=set(payload.edit_group_ids),
    )
    return _serialize_llm_access(
        llm_id=llm_id,
        use_scope=llm.use_scope,
        grants=AccessService(db).list_resource_grants(
            resource_type=ResourceType.LLM,
            resource_id=llm_id,
        ),
    )


@router.put("/llms/{llm_id}", response_model=LLMResponse)
async def update_llm(
    llm_id: int,
    llm_data: LLMUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
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
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

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
    if "thinking_effort" in llm_data.model_fields_set:
        update_data["thinking_effort"] = llm_data.thinking_effort
    if "thinking_budget_tokens" in llm_data.model_fields_set:
        update_data["thinking_budget_tokens"] = llm_data.thinking_budget_tokens

    if llm_data.streaming is not None:
        update_data["streaming"] = llm_data.streaming
    if llm_data.image_input is not None:
        update_data["image_input"] = llm_data.image_input
    if llm_data.image_output is not None:
        update_data["image_output"] = llm_data.image_output
    if llm_data.max_context is not None:
        update_data["max_context"] = llm_data.max_context
    if "extra_config" in llm_data.model_fields_set:
        # Allow explicit clearing: payload ``extra_config: ""`` is normalized to
        # None by schema validation and must still persist as NULL in DB.
        update_data["extra_config"] = llm_data.extra_config

    try:
        updated_llm = service.update_llm(
            llm_id,
            user=current_user,
            update_data=update_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated_llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    return _serialize_llm(updated_llm)


@router.delete("/llms/{llm_id}", status_code=204)
async def delete_llm(
    llm_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(permissions(Permission.LLMS_MANAGE)),
) -> Response:
    """Delete an LLM.

    Args:
        llm_id: The ID of the LLM to delete.
        db: Database session.

    Raises:
        HTTPException: If the LLM is not found (404).
    """
    service = LLMService(db)
    llm = service.get_llm(llm_id)
    if not llm:
        raise HTTPException(status_code=404, detail="LLM not found")

    service.delete_llm(llm_id, user=current_user)
    return Response(status_code=204)
