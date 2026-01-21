"""API endpoints for model management.

This module provides endpoints to query available LLM models.
"""

from typing import Any

from app.llm_globals import get_all_names
from fastapi import APIRouter

router = APIRouter()


@router.get("/models")
async def get_models() -> dict[str, Any]:
    """Get all available LLM models.

    Returns:
        A dictionary containing the list of available model names.
    """
    models = get_all_names()
    return {
        "models": models,
        "count": len(models),
    }
