
from typing import List, Dict, Any, Optional
from core.llm.abstract_llm import AbstractLLM, Response


class Agent:
    """
    Base class for all agents.
    """

    def __init__(self):
        self.model: Optional[AbstractLLM] = None
        self.is_started: bool = False
        self.history: List[Dict[str, str]] = []

    def add_action(self) -> 'Agent':
        """
        Add an action to the agent.
        
        Returns:
            Agent: Returns self for chaining
        """
        return self

    def set_memory_manager(self) -> 'Agent':
        """
        Set the memory manager for the agent. Only one memory manager is allowed.
        
        Returns:
            Agent: Returns self for chaining
        """
        return self

    def add_plan(self) -> 'Agent':
        """
        Add a plan to the agent.
        
        Returns:
            Agent: Returns self for chaining
        """
        return self

    def add_tool(self) -> 'Agent':
        """
        Add a tool to the agent.
        
        Returns:
            Agent: Returns self for chaining
        """
        return self

    def set_model(self, model: AbstractLLM) -> 'Agent':
        """
        Set the LLM model for the agent.
        
        Args:
            model (AbstractLLM): The LLM model to use
            
        Returns:
            Agent: Returns self for chaining
        """
        self.model = model
        return self

    def start(self) -> 'Agent':
        """
        Start the agent.
        
        Returns:
            Agent: Returns self for chaining
        """
        if self.model is None:
            raise ValueError("Model must be set before starting the agent")
        self.is_started = True
        return self

    def stop(self) -> None:
        """
        Stop the agent.
        """
        self.is_started = False

    def chat(self, message: str) -> Response:
        """
        Chat with the agent using the configured LLM model.
        
        Args:
            message (str): The user's message
            
        Returns:
            Response: The LLM response
            
        Raises:
            ValueError: If the agent hasn't been started or no model is set
        """
        if not self.is_started:
            raise ValueError("Agent must be started before chatting")
            
        if self.model is None:
            raise ValueError("Model must be set before chatting")
            
        # Add user message to history
        self.history.append({"role": "user", "content": message})
        
        # Get response from LLM
        response = self.model.chat(self.history)
        
        # Add assistant response to history
        if response.choices:
            first_choice = response.first()
            self.history.append({
                "role": first_choice.message.role,
                "content": first_choice.message.content
            })
        
        return response
