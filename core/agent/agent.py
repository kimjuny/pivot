from typing import Any

from core.agent.output_message import OutputMessage
from core.llm.abstract_llm import AbstractLLM
from core.utils.logging_config import get_logger

from .input_message import InputMessage
from .plan.scene import Scene, SceneState
from .plan.subscene import Subscene, SubsceneState

# Get logger for this module
logger = get_logger('agent')

class Agent:
    """
    Base class for all agents with scene graph functionality.
    """

    def __init__(self, name: str = "Agent", description: str = ""):
        self.name = name
        self.description = description
        self.model: AbstractLLM | None = None
        self.is_started: bool = False
        self.history: list[dict[str, str]] = []
        self.scenes: list[Scene] = []
        self.current_scene: Scene | None = None
        self.current_subscene: Subscene | None = None

    def set_name(self, name: str) -> 'Agent':
        """
        Set the name of the agent.
        
        Args:
            name (str): The name of the agent
            
        Returns:
            Agent: Returns self for chaining
        """
        self.name = name
        return self

    def set_description(self, description: str) -> 'Agent':
        """
        Set the description of the agent.
        
        Args:
            description (str): The description of the agent
            
        Returns:
            Agent: Returns self for chaining
        """
        self.description = description
        return self

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

    def add_plan(self, scene: Scene) -> 'Agent':
        """
        Add a plan (scene) to the agent.
        
        Args:
            scene (Scene): The scene to add
            
        Returns:
            Agent: Returns self for chaining
        """
        self.scenes.append(scene)
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

    def print_scene_graph(self) -> None:
        """Print the current scene graph in text format."""
        logger.info("\n=== Current Scene Graph State ===")
        for i, scene in enumerate(self.scenes):
            status = "ACTIVE" if scene.state == SceneState.ACTIVE else "INACTIVE"
            current_marker = " <-- CURRENT" if scene == self.current_scene else ""
            logger.info(f"Scene {i+1}: {scene.name} [{status}]{current_marker}")
            
            # Print subscenes
            for j, subscene in enumerate(scene.subscenes):
                status = "ACTIVE" if subscene.state == SubsceneState.ACTIVE else "INACTIVE"
                current_marker = " <-- CURRENT" if subscene == self.current_subscene else ""
                type_marker = f" ({subscene.type.value})"
                logger.info(f"  Subscene {j+1}: {subscene.name}{type_marker} [{status}]{current_marker}")
                
                # Print connections
                if subscene.connections:
                    logger.info("    Connections:")
                    for k, connection in enumerate(subscene.connections):
                        to_subscene_name = connection.to_subscene  # Using explicit attribute name
                        to_scene_name = "Unknown"
                        
                        # Find the target scene name
                        for s in self.scenes:
                            for ss in s.subscenes:
                                if ss.name == to_subscene_name:
                                    to_scene_name = s.name
                                    break
                        
                        active_marker = " (ACTIVE)" if subscene == self.current_subscene else ""
                        logger.info(f"      {k+1}. {connection.name} -> {to_scene_name}:{to_subscene_name}{active_marker}")
        logger.info("========================\n")

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the agent configuration to a dictionary.
        
        Returns:
            dict: The agent configuration.
        """
        return {
            "name": self.name,
            "description": self.description,
            "scenes": [scene.to_dict() for scene in self.scenes]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Agent':
        """
        Create an agent from a dictionary configuration.
        
        Args:
            data (dict): The agent configuration.
            
        Returns:
            Agent: The created agent.
        """
        agent = cls(
            name=data.get("name", "Agent"),
            description=data.get("description", "")
        )
        
        if "scenes" in data:
            for scene_data in data["scenes"]:
                scene = Scene.from_dict(scene_data)
                agent.add_plan(scene)
                
        return agent



    def chat(self, message: str) -> 'OutputMessage':
        """
        Chat with the agent using the configured LLM model with scene graph awareness.
        
        Args:
            message (str): The user's message
            
        Returns:
            OutputMessage: The structured output message
            
        Raises:
            ValueError: If the agent hasn't been started or no model is set
        """
        if not self.is_started:
            raise ValueError("Agent must be started before chatting")
            
        if self.model is None:
            raise ValueError("Model must be set before chatting")
            
        # Log chat start
        logger.info(f"Starting chat with message: {message}")
        
        # Create structured input message with context
        input_message = InputMessage(
            user_message=message,
            history=self.history,
            scenes=self.scenes,
            current_scene=self.current_scene,
            current_subscene=self.current_subscene
        )
        
        # Get structured messages for LLM
        llm_messages = input_message.get_messages()
        
        response = self.model.chat(llm_messages)
        

        if response.choices:
            first_choice = response.first()
            
            # Parse the LLM response content into OutputMessage
            try:
                # Create OutputMessage from LLM response content
                output_message = OutputMessage.from_content(first_choice.message.content)
                
                # If updated_scenes is provided, update the agent's scenes
                if output_message.updated_scenes and len(output_message.updated_scenes) > 0:
                    # Clear existing scenes and add updated ones
                    self.scenes.clear()
                    self.scenes.extend(output_message.updated_scenes)
                    
                    # Update current_scene and current_subscene based on updated_scenes
                    for scene in output_message.updated_scenes:
                        if scene.state.value == 'active':
                            self.current_scene = scene
                            for subscene in scene.subscenes:
                                if subscene.state.value == 'active':
                                    self.current_subscene = subscene
                                    break
                            break
                    
                    logger.info(f"Updated agent state: scene={self.current_scene.name if self.current_scene else None}, subscene={self.current_subscene.name if self.current_subscene else None}")
                    
                logger.info(f"Response: {output_message.response[:50]}...")
                logger.info(f"Reason: {output_message.reason[:100]}...")
                
                return output_message
                
            except Exception as e:
                logger.error(f"Error parsing LLM response into OutputMessage: {e}")
                import traceback
                logger.error(traceback.format_exc())
                
                # Return a fallback OutputMessage
                return OutputMessage(
                    response=first_choice.message.content,
                    updated_scenes=[],
                    reason="Failed to parse structured response"
                )
        
        # Fallback if no choices
        return OutputMessage(
            response="No response from LLM",
            updated_scenes=[],
            reason="No choices in LLM response"
        )

    def chat_with_print(self, message: str) -> 'OutputMessage':
        """
        Chat with the agent and print the scene graph after the response.
        
        Args:
            message (str): The user's message
            
        Returns:
            OutputMessage: The structured output message
        """
        # Get the response
        output_message = self.chat(message)
        
        # Print the scene graph in text format
        self.print_scene_graph()
        
        return output_message
