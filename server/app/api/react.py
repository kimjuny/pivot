"""API endpoints for ReAct agent chat stream.

This module provides streaming chat endpoints for the ReAct agent system.
"""

import logging
import traceback
import uuid
from datetime import datetime, timezone

from app.api.dependencies import get_db
from app.llm_globals import get_llm
from app.models.agent import Agent
from app.models.react import ReactTask
from app.orchestration.react import ReactEngine
from app.orchestration.tool import get_tool_manager
from app.schemas.react import ReactChatRequest, ReactStreamEvent, ReactStreamEventType
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

# Get logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/react/chat/stream")
async def react_chat_stream(
    request: ReactChatRequest, raw_request: Request, db: Session = Depends(get_db)
):
    """
    ReAct streaming chat endpoint.

    This endpoint creates a new ReAct task and executes it with streaming updates.
    The stream returns Server-Sent Events (SSE) with the following event types:
    - recursion_start: New recursion cycle started
    - observe: LLM observation
    - thought: LLM reasoning
    - abstract: Brief summary of the recursion cycle
    - action: Action decision
    - tool_call: Tool execution
    - tool_result: Tool execution result
    - plan_update: Plan update from RE_PLAN action
    - answer: Final answer from ANSWER action
    - error: Error occurred
    - task_complete: Task completed successfully

    Args:
        request: ReactChatRequest containing agent_id, message, and user
        db: Database session dependency

    Returns:
        StreamingResponse with text/event-stream content
    """

    async def event_generator():
        client_disconnected = False
        task = None

        try:
            # Get agent
            agent = db.get(Agent, request.agent_id)
            if not agent:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={"error": f"Agent {request.agent_id} not found"},
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Get LLM for this agent
            llm = get_llm(agent.model_name or "")
            if not llm:
                error_event = ReactStreamEvent(
                    type=ReactStreamEventType.ERROR,
                    task_id="",
                    trace_id=None,
                    iteration=0,
                    delta=None,
                    data={
                        "error": f"LLM model '{agent.model_name}' not found or not registered"
                    },
                    timestamp=datetime.now(timezone.utc),
                )
                yield f"data: {error_event.json()}\n\n"
                return

            # Create ReactTask
            task_id = str(uuid.uuid4())
            task = ReactTask(
                task_id=task_id,
                agent_id=agent.id or 0,
                user=request.user,
                user_message=request.message,
                objective=request.message,  # Use message as objective
                status="pending",
                iteration=0,
                max_iteration=agent.max_iteration,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            # Initialize ReAct engine
            tool_manager = get_tool_manager()
            engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=db)

            # Execute task and stream events
            async for event_data in engine.run_task(task):
                # Check if client disconnected via Request object
                if await raw_request.is_disconnected():
                    logger.info(f"Client disconnected, stopping task {task_id}")
                    client_disconnected = True
                    engine.cancelled = True  # Signal engine to stop
                    break

                # Check if client disconnected via flag
                if client_disconnected:
                    logger.info(f"Client disconnected, stopping task {task_id}")
                    engine.cancelled = True  # Signal engine to stop
                    break

                # Convert event data to ReactStreamEvent
                event_type_str = event_data.get("type", "")
                try:
                    event_type = ReactStreamEventType(event_type_str)
                except ValueError:
                    # Unknown event type, skip
                    logger.warning(f"Unknown event type: {event_type_str}")
                    continue

                event = ReactStreamEvent(
                    type=event_type,
                    task_id=event_data.get("task_id", task_id),
                    trace_id=event_data.get("trace_id"),
                    iteration=event_data.get("iteration", 0),
                    delta=event_data.get("delta"),
                    data=event_data.get("data"),
                    timestamp=datetime.fromisoformat(
                        event_data.get("timestamp", datetime.now(timezone.utc).isoformat())
                    ),
                )

                try:
                    yield f"data: {event.json()}\n\n"
                except (
                    GeneratorExit,
                    ConnectionResetError,
                    BrokenPipeError,
                ) as e:
                    # Client disconnected
                    logger.info(f"Client disconnected during yield: {e}")
                    client_disconnected = True
                    break

        except (GeneratorExit, ConnectionResetError, BrokenPipeError) as e:
            # Client disconnected
            logger.info(f"Client disconnected: {e}")
            client_disconnected = True
        except Exception as e:
            logger.error(f"Error in ReAct chat stream: {e}")
            logger.error(traceback.format_exc())
            if not client_disconnected:
                try:
                    error_event = ReactStreamEvent(
                        type=ReactStreamEventType.ERROR,
                        task_id="",
                        trace_id=None,
                        iteration=0,
                        delta=None,
                        data={"error": str(e)},
                        timestamp=datetime.now(timezone.utc),
                    )
                    yield f"data: {error_event.json()}\n\n"
                except (GeneratorExit, ConnectionResetError, BrokenPipeError):
                    pass
        finally:
            # Mark task as cancelled if client disconnected
            if client_disconnected and task:
                task.status = "cancelled"
                task.updated_at = datetime.now(timezone.utc)
                try:
                    db.commit()
                    logger.info(f"Task {task.task_id} marked as cancelled")
                except Exception as e:
                    logger.error(f"Failed to mark task as cancelled: {e}")

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/react/tasks/{task_id}")
async def get_react_task(task_id: str, db: Session = Depends(get_db)):
    """
    Get ReAct task information by task_id.

    Args:
        task_id: Task UUID
        db: Database session dependency

    Returns:
        ReactTask information
    """
    from app.models.react import ReactTask
    from sqlmodel import select

    stmt = select(ReactTask).where(ReactTask.task_id == task_id)
    task = db.exec(stmt).first()

    if not task:
        return {"error": "Task not found"}, 404

    return task


@router.get("/react/tasks/{task_id}/recursions")
async def get_task_recursions(task_id: str, db: Session = Depends(get_db)):
    """
    Get all recursions for a task.

    Args:
        task_id: Task UUID
        db: Database session dependency

    Returns:
        List of recursions
    """
    from app.models.react import ReactRecursion
    from sqlmodel import select

    stmt = (
        select(ReactRecursion)
        .where(ReactRecursion.task_id == task_id)
        .order_by(ReactRecursion.iteration_index)
    )
    recursions = db.exec(stmt).all()

    return list(recursions)
