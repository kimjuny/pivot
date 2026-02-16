"""API endpoints for model management.

This module provides endpoints to query available LLMs.
All endpoints require authentication.
"""

from typing import Any

from app.api.auth import get_current_user
from app.api.dependencies import get_db
from app.crud.llm import llm as llm_crud
from app.models.user import User
from fastapi import APIRouter, Depends
from sqlmodel import Session

router = APIRouter()


@router.get("/models")
async def get_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all available LLMs.

    Returns:
        A dictionary containing the list of available LLM names.

    Note:
        This endpoint is deprecated. Use /api/llms instead for full LLM details.
    """
    llms = llm_crud.get_all(db)
    model_names = [f"{llm.name} ({llm.model})" for llm in llms]
    return {
        "models": model_names,
        "count": len(model_names),
    }
