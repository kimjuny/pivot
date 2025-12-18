import json
from typing import List, Dict, Any, Optional
from .plan.scene import Scene
from .plan.subscene import Subscene


class InputMessage:
    """
    Structured input message for communicating with the LLM.
    Contains context information including history, scene graph, and current state.
    """

    def __init__(self, 
                 user_message: str,
                 history: List[Dict[str, str]],
                 scenes: List[Scene],
                 current_scene: Optional[Scene] = None,
                 current_subscene: Optional[Subscene] = None):
        """
        Initialize an InputMessage.
        
        Args:
            user_message (str): The current user message
            history (List[Dict[str, str]]): Conversation history
            scenes (List[Scene]): All available scenes for the agent
            current_scene (Optional[Scene]): Current active scene
            current_subscene (Optional[Subscene]): Current active subscene
        """
        self.user_message = user_message
        self.history = history
        self.scenes = scenes
        self.current_scene = current_scene
        self.current_subscene = current_subscene
        
    def to_llm_string(self) -> str:
        """
        Convert the input message to a string format suitable for the LLM.
        
        Returns:
            str: Formatted string containing all context information
        """
        # Build the scene graph JSON representation
        scene_graph = {
            "scenes": [scene.to_dict() for scene in self.scenes]
        }
        
        # Build current state information
        current_state = {}
        if self.current_scene:
            current_state["scene"] = self.current_scene.name
        if self.current_subscene:
            current_state["subscene"] = self.current_subscene.name
            
        # Construct the full prompt
        prompt_parts = []
        
        prompt_parts.append("You are an intelligent agent with the following scene graph:")
        prompt_parts.append(json.dumps(scene_graph, indent=2, ensure_ascii=False))
        
        if current_state:
            prompt_parts.append("\nCurrent state:")
            prompt_parts.append(json.dumps(current_state, indent=2, ensure_ascii=False))
            
        prompt_parts.append("\nConversation history:")
        prompt_parts.append(json.dumps(self.history, indent=2, ensure_ascii=False))
        
        prompt_parts.append("\nUser message:")
        prompt_parts.append(self.user_message)
        
        prompt_parts.append("\nInstructions:")
        prompt_parts.append("- Understand the scene graph and current state")
        prompt_parts.append("- Respond appropriately based on the current subscene's objective")
        prompt_parts.append("- If transitioning to a new subscene is appropriate, indicate this in your response")
        prompt_parts.append("- Your response should help achieve the current subscene's objective")
        
        return "\n".join(prompt_parts)