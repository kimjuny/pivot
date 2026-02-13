"""
Build service module.

Provides business logic for agent building/modification operations,
including streaming LLM responses for build mode.
"""

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from app.crud.llm import llm as llm_crud
from app.llm.llm_factory import create_llm_from_config
from app.orchestration.base.system_prompt import get_build_prompt
from app.schemas.schemas import AgentDetailResponse, StreamEvent, StreamEventType
from sqlmodel import Session

logger = logging.getLogger(__name__)


class BuildServiceError(Exception):
    """Base exception for build service errors."""

    pass


class BuildService:
    """
    Service class for agent building operations.

    Handles streaming build responses from LLM for creating/modifying agents.
    """

    @staticmethod
    def stream_build_chat(
        agent_detail: AgentDetailResponse | None,
        message: str,
        llm_id: int | None,
        db: Session,
    ) -> Iterator[StreamEvent]:
        """Stream build chat responses for modifying agent configuration.

        Takes user's build request and streams LLM's response including thinking,
        response text, reason, and updated agent JSON.

        Similar to preview chat stream, this follows the same event pattern
        for consistency.

        Args:
            agent_detail: Optional existing agent definition to modify.
            message: User's build request (e.g., "Add a sleep scene with 3 steps").
            llm_id: Optional LLM ID to use.
            db: Database session for loading LLM configuration.

        Yields:
            StreamEvent objects for SSE streaming:
            - REASONING: Chain-of-thought updates (for thinking models)
            - RESPONSE: LLM's friendly response text
            - REASON: Internal reasoning for changes
            - UPDATED_SCENES: Complete updated agent JSON in delta field
            - ERROR: Error messages
        """
        # Get LLM configuration and create instance
        if not llm_id:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error="LLM ID is required for build chat",
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            return

        llm_config = llm_crud.get(llm_id, db)
        if not llm_config:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=f"LLM with ID {llm_id} not found",
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            return

        try:
            llm_model = create_llm_from_config(llm_config)
        except (ValueError, NotImplementedError) as e:
            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=f"Failed to create LLM instance: {e!s}",
                create_time=datetime.now(timezone.utc).isoformat(),
            )
            return

        # Build system prompt with existing agent config (if any)
        existing_agent = None
        if agent_detail:
            # Convert agent detail to dict for prompt
            existing_agent = {
                "name": agent_detail.name,
                "description": agent_detail.description,
                "scenes": [
                    {
                        "name": scene.name,
                        "identification_condition": scene.description,
                        "state": scene.state,
                        "subscenes": [
                            {
                                "name": subscene.name,
                                "type": subscene.type,
                                "mandatory": subscene.mandatory,
                                "objective": subscene.objective,
                                "state": subscene.state,
                                "connections": [
                                    {
                                        "name": conn.name,
                                        "from_subscene": conn.from_subscene,
                                        "to_subscene": conn.to_subscene,
                                        "condition": conn.condition,
                                    }
                                    for conn in subscene.connections
                                ],
                            }
                            for subscene in scene.subscenes
                        ],
                    }
                    for scene in agent_detail.scenes
                ],
            }

        system_prompt = get_build_prompt(existing_agent)

        # Build messages for LLM
        messages = [
            system_prompt,
            {
                "role": "user",
                "content": message,
            },
        ]

        # Stream LLM response
        full_content = ""

        try:
            # Accumulate full response first (don't stream raw JSON)
            for chunk in llm_model.chat_stream(messages):
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.message.content
                reasoning = choice.message.reasoning_content

                # Yield reasoning delta if available (for thinking models)
                if reasoning:
                    yield StreamEvent(
                        type=StreamEventType.REASONING,
                        delta=reasoning,
                        create_time=datetime.now(timezone.utc).isoformat(),
                    )

                # Accumulate response (don't stream yet)
                if delta:
                    full_content += delta

            # Parse the complete JSON response
            try:
                # The LLM should return a JSON object like:
                # {
                #   "response": "I've created...",
                #   "reason": "The user requested...",
                #   "agent": { ... }
                # }

                # Try to extract JSON from markdown code blocks if present
                import re

                json_match = re.search(
                    r"```json\s*\n(.*?)\n```", full_content, re.DOTALL
                )
                json_str = json_match.group(1) if json_match else full_content.strip()

                result = json.loads(json_str)

                # Stream the friendly response text character by character
                if "response" in result:
                    response_text = result["response"]
                    # Stream character by character for smooth UX
                    for char in response_text:
                        yield StreamEvent(
                            type=StreamEventType.RESPONSE,
                            delta=char,
                            create_time=datetime.now(timezone.utc).isoformat(),
                        )

                # Yield reason if present
                if "reason" in result:
                    yield StreamEvent(
                        type=StreamEventType.REASON,
                        delta=result["reason"],
                        create_time=datetime.now(timezone.utc).isoformat(),
                    )

                # Yield the complete agent configuration
                if "agent" in result:
                    # Send the agent JSON as a delta in UPDATED_SCENES event
                    # Frontend will parse this to extract the scenes
                    yield StreamEvent(
                        type=StreamEventType.UPDATED_SCENES,
                        delta=json.dumps(result["agent"], ensure_ascii=False),
                        create_time=datetime.now(timezone.utc).isoformat(),
                    )

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM JSON response: {e}")
                logger.error(f"Raw content: {full_content}")
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"Failed to parse response as JSON: {e}",
                    create_time=datetime.now(timezone.utc).isoformat(),
                )
            except KeyError as e:
                logger.error(f"Missing required field in LLM response: {e}")
                yield StreamEvent(
                    type=StreamEventType.ERROR,
                    error=f"Invalid response format: missing {e}",
                    create_time=datetime.now(timezone.utc).isoformat(),
                )

        except Exception as e:
            logger.error(f"Error in build stream: {e}")
            import traceback

            logger.error(traceback.format_exc())

            yield StreamEvent(
                type=StreamEventType.ERROR,
                error=str(e),
                create_time=datetime.now(timezone.utc).isoformat(),
            )
