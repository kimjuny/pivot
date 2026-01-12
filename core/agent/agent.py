
from typing import List, Dict, Any, Optional
from core.llm.abstract_llm import AbstractLLM, Response
from .plan.scene import Scene, SceneState
from .plan.subscene import Subscene, SubsceneState
from .plan.connection import Connection
from .input_message import InputMessage
from core.utils.logging_config import get_logger

# Get logger for this module
logger = get_logger('agent')



class Agent:
    """
    Base class for all agents with scene graph functionality.
    """

    def __init__(self):
        self.model: Optional[AbstractLLM] = None
        self.is_started: bool = False
        self.history: List[Dict[str, str]] = []
        self.scenes: List[Scene] = []
        self.current_scene: Optional[Scene] = None
        self.current_subscene: Optional[Subscene] = None

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
        """
        Print the current scene graph in text format.
        """
        logger.info("\n=== 当前场景图状态 ===")
        for i, scene in enumerate(self.scenes):
            status = "ACTIVE" if scene.state == SceneState.ACTIVE else "INACTIVE"
            current_marker = " <-- CURRENT" if scene == self.current_scene else ""
            logger.info(f"场景 {i+1}: {scene.name} [{status}]{current_marker}")
            
            # Print subscenes
            for j, subscene in enumerate(scene.subscenes):
                status = "ACTIVE" if subscene.state == SubsceneState.ACTIVE else "INACTIVE"
                current_marker = " <-- CURRENT" if subscene == self.current_subscene else ""
                type_marker = f" ({subscene.type.value})"
                logger.info(f"  子场景 {j+1}: {subscene.name}{type_marker} [{status}]{current_marker}")
                
                # Print connections
                if subscene.connections:
                    logger.info(f"    连接:")
                    for k, connection in enumerate(subscene.connections):
                        to_subscene_name = connection.to_subscene  # Using explicit attribute name
                        to_scene_name = "未知"
                        
                        # Find the target scene name
                        for s in self.scenes:
                            for ss in s.subscenes:
                                if ss.name == to_subscene_name:
                                    to_scene_name = s.name
                                    break
                        
                        active_marker = " (ACTIVE)" if subscene == self.current_subscene else ""
                        logger.info(f"      {k+1}. {connection.name} -> {to_scene_name}:{to_subscene_name}{active_marker}")
        logger.info("========================\n")





    def chat(self, message: str) -> Response:
        """
        Chat with the agent using the configured LLM model with scene graph awareness.
        
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
        
        # Format message for LLM with scene context
        llm_message = input_message.to_llm_string()
        
        # Prepare messages for LLM
        llm_messages = [{"role": "user", "content": llm_message}]
        
        response = self.model.chat(llm_messages)

        if response.choices:
            first_choice = response.first()
            
            # Parse the LLM response content into OutputMessage
            try:
                from core.agent.output_message import OutputMessage
                
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
            except Exception as e:
                logger.error(f"Error parsing LLM response into OutputMessage: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Add user message and assistant response to history
        self.history.append({"role": "user", "content": message})
        
        # Prepare assistant response based on OutputMessage
        assistant_response = None
        if response.choices:
            first_choice = response.first()
            
            try:
                from core.agent.output_message import OutputMessage
                
                # Parse response content into OutputMessage
                output_message = OutputMessage.from_content(first_choice.message.content)
                
                # Add structured assistant response to history
                self.history.append({
                    "role": "assistant",
                    "content": output_message.response
                })
                
                # Use OutputMessage response as the assistant response
                assistant_response = output_message.response
                
            except Exception as e:
                # Fallback to raw response if parsing fails
                self.history.append({
                    "role": first_choice.message.role,
                    "content": first_choice.message.content
                })
                assistant_response = first_choice.message.content
        
        # Log chat completion
        logger.info("Chat completed successfully")
        
        # Return the original response for compatibility
        return response

    def chat_with_print(self, message: str) -> Response:
        """
        Chat with the agent and print the scene graph after the response.
        
        Args:
            message (str): The user's message
            
        Returns:
            Response: The LLM response
        """
        # Get the response
        response = self.chat(message)
        
        # Print the scene graph in text format
        self.print_scene_graph()
        
        return response
