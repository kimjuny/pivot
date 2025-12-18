
from typing import List, Dict, Any, Optional
from core.llm.abstract_llm import AbstractLLM, Response
from .plan.scene import Scene, SceneState
from .plan.subscene import Subscene, SubsceneState
from .plan.connection import Connection
from .input_message import InputMessage



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
        print("\n=== 当前场景图状态 ===")
        for i, scene in enumerate(self.scenes):
            status = "ACTIVE" if scene.state == SceneState.ACTIVE else "INACTIVE"
            current_marker = " <-- CURRENT" if scene == self.current_scene else ""
            print(f"场景 {i+1}: {scene.name} [{status}]{current_marker}")
            
            # Print subscenes
            for j, subscene in enumerate(scene.subscenes):
                status = "ACTIVE" if subscene.state == SubsceneState.ACTIVE else "INACTIVE"
                current_marker = " <-- CURRENT" if subscene == self.current_subscene else ""
                type_marker = f" ({subscene.type.value})"
                print(f"  子场景 {j+1}: {subscene.name}{type_marker} [{status}]{current_marker}")
                
                # Print connections
                if subscene.connections:
                    print(f"    连接:")
                    for k, connection in enumerate(subscene.connections):
                        to_scene_name = "未知"
                        to_subscene_name = "未知"
                        
                        # Find the target scene and subscene names
                        for s in self.scenes:
                            for ss in s.subscenes:
                                if ss == connection.to_subscene:
                                    to_scene_name = s.name
                                    to_subscene_name = ss.name
                                    break
                        
                        active_marker = " (ACTIVE)" if subscene == self.current_subscene else ""
                        print(f"      {k+1}. {connection.name} -> {to_scene_name}:{to_subscene_name}{active_marker}")
        print("========================\n")



    def _identify_scene(self, message: str) -> Optional[Scene]:
        """
        Identify which scene the user's message corresponds to.
        
        Args:
            message (str): The user's message
            
        Returns:
            Optional[Scene]: The identified scene or None if no scene matches
        """
        # For now, we'll just return the first scene as a placeholder
        # In a real implementation, this would use the LLM to analyze the message
        # against the scene identification conditions
        for scene in self.scenes:
            # This is a simplified implementation
            # A full implementation would analyze the message against the scene's
            # identification_condition using the LLM
            if scene.state == SceneState.INACTIVE:
                return scene
        return None

    def _transition_subscene(self, message: str) -> Optional[Subscene]:
        """
        Determine if a transition to a new subscene is needed based on the user's message.
        
        Args:
            message (str): The user's message
            
        Returns:
            Optional[Subscene]: The target subscene if a transition is needed, otherwise None
        """
        if not self.current_subscene:
            # If no current subscene, return the first subscene of the current scene
            if self.current_scene and self.current_scene.subscenes:
                return self.current_scene.subscenes[0]
            return None
            
        # Check connections from the current subscene
        for connection in self.current_subscene.connections:
            # This is a simplified implementation
            # A full implementation would analyze the message against the connection's
            # condition using the LLM
            return connection.to_subscene
            
        return None

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
            
        # Handle scene identification if we're not in a scene
        if not self.current_scene:
            identified_scene = self._identify_scene(message)
            if identified_scene:
                self.current_scene = identified_scene
                self.current_scene.activate()
                
        # Handle subscene transitions
        target_subscene = self._transition_subscene(message)
        if target_subscene:
            # Deactivate current subscene if exists
            if self.current_subscene:
                self.current_subscene.deactivate()
            # Activate new subscene
            self.current_subscene = target_subscene
            self.current_subscene.activate()
            
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
        
        # Get response from LLM
        response = self.model.chat(llm_messages)
        
        # Add user message and assistant response to history
        self.history.append({"role": "user", "content": message})
        if response.choices:
            first_choice = response.first()
            self.history.append({
                "role": first_choice.message.role,
                "content": first_choice.message.content
            })
        
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
