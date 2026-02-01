"""API endpoints for agent building/modification.

This module provides endpoints for building and modifying agents
using LLM-powered natural language interactions.
"""

import logging
import traceback
from typing import Any

from app.api.dependencies import get_db
from app.schemas.build import BuildChatRequest, BuildChatResponse
from app.services.build_service import BuildService, BuildServiceError
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/build/chat", response_model=BuildChatResponse)
async def chat_build(
    request: BuildChatRequest, db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Chat endpoint for building/modifying agents.

    Args:
        request: Build chat request with content and optional session/agent IDs.
        db: Database session.

    Returns:
        Build response with session ID, response text, reason, and updated agent.

    Raises:
        HTTPException: If building fails.
    """
    logger.info(f"Received build chat request. Session: {request.session_id}")

    try:
        session_id, result = BuildService.build_agent(
            db=db,
            content=request.content,
            session_id=request.session_id,
            agent_id=request.agent_id,
        )

        return {
            "session_id": session_id,
            "response": result.response,
            "reason": result.reason,
            "updated_agent": result.agent_dict,
        }

    except BuildServiceError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Build failed: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Build failed: {e!s}") from e
