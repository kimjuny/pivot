"""
Agent runtime module.

Contains the AgentRuntime class for managing agent chat sessions
using the unified SQLModel entities.
"""

import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

from app.models.agent import Scene, SceneState, Subscene
from app.orchestration.base.input_message import InputMessage
from app.orchestration.base.output_message import OutputMessage
from app.orchestration.base.stream import AgentResponseChunk, AgentResponseChunkType
from app.utils.logging_config import get_logger

if TYPE_CHECKING:
    from app.llm.abstract_llm import AbstractLLM

# Get logger for this module
logger = get_logger("agent.runtime")


class AgentRuntime:
    """
    Runtime orchestration for Agent chat functionality.

    This class manages the agent's conversation state, scene graph,
    and interaction with the LLM. It works with the unified SQLModel
    entities that support both database persistence and runtime operations.
    """

    def __init__(
        self,
        name: str = "Agent",
        description: str = "",
        scenes: list[Scene] | None = None,
    ):
        """
        Initialize an AgentRuntime.

        Args:
            name: The name of the agent.
            description: Description of the agent.
            scenes: Initial list of scenes for the agent.
        """
        self.name = name
        self.description = description
        self.model: AbstractLLM | None = None
        self.is_started: bool = False
        self.history: list[dict[str, str]] = []
        self.scenes: list[Scene] = scenes or []
        self.current_scene: Scene | None = None
        self.current_subscene: Subscene | None = None

    def set_model(self, model: "AbstractLLM") -> "AgentRuntime":
        """
        Set the LLM model for the agent.

        Args:
            model: The LLM model to use.

        Returns:
            Self for method chaining.
        """
        self.model = model
        return self

    def add_plan(self, scene: Scene) -> "AgentRuntime":
        """
        Add a scene to the agent's scene graph.

        Args:
            scene: The scene to add.

        Returns:
            Self for method chaining.
        """
        self.scenes.append(scene)
        return self

    def start(self) -> "AgentRuntime":
        """
        Start the agent runtime.

        Validates that a model is configured before starting.

        Returns:
            Self for method chaining.

        Raises:
            ValueError: If no model is set.
        """
        if self.model is None:
            raise ValueError("Model must be set before starting the agent")
        self.is_started = True
        return self

    def stop(self) -> None:
        """Stop the agent runtime."""
        self.is_started = False

    def chat(self, message: str) -> OutputMessage:
        """
        Chat with the agent using the configured LLM with scene graph awareness.

        Args:
            message: The user's message.

        Returns:
            The structured output message with response and scene updates.

        Raises:
            ValueError: If the agent hasn't been started or no model is set.
        """
        if not self.is_started:
            raise ValueError("Agent must be started before chatting")

        if self.model is None:
            raise ValueError("Model must be set before chatting")

        logger.info(f"Starting chat with message: {message}")

        # Create structured input message with context
        input_message = InputMessage(
            user_message=message,
            history=self.history,
            scenes=self.scenes,
            current_scene=self.current_scene,
            current_subscene=self.current_subscene,
        )

        llm_messages = input_message.get_messages()
        response = self.model.chat(llm_messages)

        if response.choices:
            first_choice = response.first()

            try:
                output_message = OutputMessage.from_content(
                    first_choice.message.content
                )

                # Update scenes if provided
                if output_message.updated_scenes:
                    self._update_scenes_from_output(output_message)

                logger.info(f"Response: {output_message.response[:50]}...")
                logger.info(f"Reason: {output_message.reason[:100]}...")

                return output_message

            except Exception as e:
                logger.error(f"Error parsing LLM response: {e}")
                import traceback

                logger.error(traceback.format_exc())

                return OutputMessage(
                    response=first_choice.message.content,
                    updated_scenes=[],
                    reason="Failed to parse structured response",
                )

        return OutputMessage(
            response="No response from LLM",
            updated_scenes=[],
            reason="No choices in LLM response",
        )

    def chat_stream(self, message: str) -> Iterator[AgentResponseChunk]:
        """
        Chat with the agent in streaming mode.

        Args:
            message: The user's message.

        Yields:
            Streamed response chunks and final parsed result.

        Raises:
            ValueError: If the agent hasn't been started or no model is set.
        """
        if not self.is_started:
            raise ValueError("Agent must be started before chatting")

        if self.model is None:
            raise ValueError("Model must be set before chatting")

        logger.info(f"Starting chat stream with message: {message}")

        input_message = InputMessage(
            user_message=message,
            history=self.history,
            scenes=self.scenes,
            current_scene=self.current_scene,
            current_subscene=self.current_subscene,
        )

        full_content = ""
        current_section = AgentResponseChunkType.REASON
        buffer = ""

        for chunk in self.model.chat_stream(input_message.get_messages()):
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.message.content
            reasoning = choice.message.reasoning_content

            # Yield reasoning delta if available
            if reasoning:
                yield AgentResponseChunk(
                    type=AgentResponseChunkType.REASONING, delta=reasoning
                )

            if delta:
                full_content += delta
                buffer += delta

                while True:
                    # Check for section transitions
                    split_match = re.search(
                        r"##\s*(Reason|Response|Update(?:d)? Scenes|Match(?:ed)? Connection)",
                        buffer,
                        re.IGNORECASE,
                    )

                    if split_match:
                        header_type = split_match.group(1).lower()
                        pre_header = buffer[: split_match.start()]

                        # Yield pre-header content
                        if pre_header and current_section != AgentResponseChunkType.PARSING:
                            yield AgentResponseChunk(
                                type=current_section,  # type: ignore
                                delta=pre_header,
                            )

                        # Switch section
                        if "reason" in header_type:
                            current_section = AgentResponseChunkType.REASON
                        elif "response" in header_type:
                            current_section = AgentResponseChunkType.RESPONSE
                        else:
                            current_section = AgentResponseChunkType.PARSING

                        buffer = buffer[split_match.end() :]
                    else:
                        break

                # Handle potential partial header at end of buffer
                safe_len = max(0, len(buffer) - 50)
                danger_zone = buffer[safe_len:]
                first_hash_in_danger = danger_zone.find("#")

                if first_hash_in_danger != -1:
                    split_idx = safe_len + first_hash_in_danger
                    to_yield = buffer[:split_idx]
                    buffer = buffer[split_idx:]

                    if to_yield and current_section != AgentResponseChunkType.PARSING:
                        yield AgentResponseChunk(
                            type=current_section,  # type: ignore
                            delta=to_yield,
                        )
                else:
                    if buffer and current_section != AgentResponseChunkType.PARSING:
                        yield AgentResponseChunk(
                            type=current_section,  # type: ignore
                            delta=buffer,
                        )
                    buffer = ""

        # Yield any remaining buffer
        if buffer and current_section != AgentResponseChunkType.PARSING:
            yield AgentResponseChunk(
                type=current_section,  # type: ignore
                delta=buffer,
            )

        # Parse final output and update state
        try:
            output_message = OutputMessage.from_content(full_content)

            if output_message.updated_scenes:
                # self._update_scenes_from_output(output_message)

                yield AgentResponseChunk(
                    type=AgentResponseChunkType.UPDATED_SCENES,
                    updated_scenes=output_message.updated_scenes,
                )

            if output_message.match_connection:
                yield AgentResponseChunk(
                    type=AgentResponseChunkType.MATCH_CONNECTION,
                    matched_connection=output_message.match_connection,
                )

        except Exception as e:
            logger.error(f"Error parsing stream output: {e}")
            import traceback

            logger.error(traceback.format_exc())

            yield AgentResponseChunk(type=AgentResponseChunkType.ERROR, delta=str(e))

    def _update_scenes_from_output(self, output: OutputMessage) -> None:
        """
        Update the agent's scene state from output message.

        Args:
            output: The output message containing updated scenes.
        """
        self.scenes.clear()
        self.scenes.extend(output.updated_scenes)

        # Find and set current active scene/subscene
        for scene in output.updated_scenes:
            if scene.state == SceneState.ACTIVE:
                self.current_scene = scene
                for subscene in scene.subscenes:
                    if subscene.state == "active":
                        self.current_subscene = subscene
                        break
                break

        if self.current_scene:
            logger.info(
                f"Updated state: scene={self.current_scene.name}, "
                f"subscene={self.current_subscene.name if self.current_subscene else None}"
            )
