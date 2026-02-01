"""API endpoints for agent chat and chat history management.

This module provides endpoints for chatting with agents and managing
chat history, including conversation state persistence.
"""

import logging
import traceback
from datetime import datetime, timezone

from app.schemas.schemas import (
    PreviewChatRequest,
    StreamEvent,
    StreamEventType,
)
from app.services.chat_service import ChatService
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/preview/chat/stream")
async def preview_chat_stream(request: PreviewChatRequest):
    """Streaming stateless chat for preview mode using provided agent definition.

    Returns a Server-Sent Events (SSE) stream with events aligned with AgentResponseChunk:
    - reasoning: Chain-of-Thought updates
    - reason: Reason content updates
    - response: Response content updates
    - updated_scenes: Scene graph updates
    - match_connection: Connection match updates
    - error: Error details
    """

    async def event_generator():
        try:
            for event in ChatService.stream_preview_chat(
                agent_detail=request.agent_detail,
                message=request.message,
                current_scene_name=request.current_scene_name,
                current_subscene_name=request.current_subscene_name,
            ):
                yield f"data: {event.json()}\n\n"

        except Exception as e:
            logger.error(f"Error in preview chat stream: {e}")
            logger.error(traceback.format_exc())
            error_event = StreamEvent(
                type=StreamEventType.ERROR,
                error=str(e),
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            yield f"data: {error_event.json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
