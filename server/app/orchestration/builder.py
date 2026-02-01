"""
Agent builder module.

Contains the AgentBuilder class for building or modifying agents
using LLM with multi-turn conversation support.
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.agent import Scene
from app.orchestration.base.system_prompt import get_build_prompt
from app.utils.logging_config import get_logger

if TYPE_CHECKING:
    from app.llm.abstract_llm import AbstractLLM

logger = get_logger("agent.builder")


@dataclass
class BuildResult:
    """Result of an agent build/modification operation.

    Attributes:
        agent_dict: Dictionary representation of the built agent.
        scenes: List of Scene objects for the agent.
        response: Human-readable response text.
        reason: Explanation of the changes made.
    """

    agent_dict: dict
    scenes: list[Scene]
    response: str
    reason: str


class AgentBuilder:
    """
    Helper class to build or modify agents using LLM with multi-turn conversation support.

    The builder maintains a conversation history to enable iterative refinement
    of agent configurations through natural language.
    """

    def __init__(self, model: "AbstractLLM"):
        """
        Initialize an AgentBuilder.

        Args:
            model: The LLM model to use for building.
        """
        self.model = model
        self.history: list[dict[str, str]] = []

    def build(
        self, requirement: str, agent_dict: dict[str, Any] | None = None
    ) -> BuildResult:
        """
        Build or modify an agent based on natural language requirements.

        Supports multi-turn conversation by maintaining history.

        Args:
            requirement: Description of the agent to build or modification instructions.
            agent_dict: Current agent configuration as dict. If provided, treated
                       as base for modification.

        Returns:
            BuildResult with the agent dictionary, scenes, response, and reasoning.
        """
        logger.info(f"Building/Modifying agent with requirement: {requirement}")

        messages = []

        # 1. Handle System Prompt (only if history is empty)
        if not self.history:
            system_msg = get_build_prompt(existing_agent=agent_dict)
            self.history.append(system_msg)

        # 2. Construct User Message
        user_content = requirement

        # If agent is provided and we already have history, remind LLM of current state
        if agent_dict and self.history:
            user_content += (
                f"\n\n(Context: Current Agent Configuration)\n"
                f"```json\n{json.dumps(agent_dict, indent=2, ensure_ascii=False)}\n```"
            )

        current_user_msg = {"role": "user", "content": user_content}

        # 3. Prepare full message list
        messages.extend(self.history)
        messages.append(current_user_msg)

        # 4. Call LLM
        response = self.model.chat(messages)
        content = response.first().message.content

        # 5. Update History
        self.history.append(current_user_msg)
        self.history.append({"role": "assistant", "content": content})

        # 6. Parse JSON and create BuildResult
        try:
            # Strip markdown code blocks if present
            if "```json" in content:
                clean_content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                clean_content = content.split("```")[1].split("```")[0].strip()
            else:
                clean_content = content.strip()

            data = json.loads(clean_content)

            # Extract fields from the schema
            agent_data = data.get("agent", {})
            response_text = data.get("response", "")
            reason_text = data.get("reason", "")

            # Build Scene objects from the agent data
            scenes: list[Scene] = []
            for scene_data in agent_data.get("scenes", []):
                scene = Scene.from_dict(scene_data)
                scenes.append(scene)

            return BuildResult(
                agent_dict=agent_data,
                scenes=scenes,
                response=response_text,
                reason=reason_text,
            )

        except Exception as e:
            logger.error(f"Failed to build agent: {e}")
            logger.error(f"LLM Output: {content}")
            raise

    def clear_history(self) -> None:
        """Clear the conversation history."""
        self.history = []
