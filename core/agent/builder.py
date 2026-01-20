import json
from dataclasses import dataclass

from core.llm.abstract_llm import AbstractLLM
from core.utils.logging_config import get_logger

from .agent import Agent
from .system_prompt import get_build_prompt

logger = get_logger('agent_builder')

@dataclass
class BuildResult:
    """Result of an agent build/modification operation."""
    agent: Agent
    response: str
    reason: str

class AgentBuilder:
    """
    Helper class to build or modify agents using LLM with multi-turn conversation support.
    """
    
    def __init__(self, model: AbstractLLM):
        self.model = model
        self.history: list[dict[str, str]] = []

    def build(self, requirement: str, agent: Agent | None = None) -> BuildResult:
        """
        Build or modify an agent based on natural language requirements.
        Supports multi-turn conversation by maintaining history.
        
        Args:
            requirement (str): The description of the agent to build or modification instructions.
            agent (Agent | None): The current agent instance. 
                                  If provided and history is empty, it's treated as the base for modification.
                                  If provided and history exists, it ensures the context is up-to-date.
            
        Returns:
            BuildResult: The structured result containing the agent, response text, and reasoning.
        """
        logger.info(f"Building/Modifying agent with requirement: {requirement}")
        
        messages = []
        
        # 1. Handle System Prompt (only if history is empty)
        if not self.history:
            # If agent is provided initially, inject it into system prompt context
            initial_agent_dict = agent.to_dict() if agent else None
            system_msg = get_build_prompt(existing_agent=initial_agent_dict)
            self.history.append(system_msg)
        
        # 2. Construct User Message
        user_content = requirement
        
        # If agent is provided and we already have history, we might want to remind the LLM of the current state
        if agent and self.history:
            user_content += f"\n\n(Context: Current Agent Configuration)\n```json\n{json.dumps(agent.to_dict(), indent=2, ensure_ascii=False)}\n```"

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
            
            # Extract fields from the new schema
            agent_data = data.get("agent", {})
            response_text = data.get("response", "")
            reason_text = data.get("reason", "")
            
            # Create Agent instance
            new_agent = Agent.from_dict(agent_data)
            new_agent.set_model(self.model) # Set model so it's ready to run
            
            return BuildResult(
                agent=new_agent,
                response=response_text,
                reason=reason_text
            )
            
        except Exception as e:
            logger.error(f"Failed to build agent: {e}")
            logger.error(f"LLM Output: {content}")
            raise

    def clear_history(self):
        """Clear the conversation history."""
        self.history = []
