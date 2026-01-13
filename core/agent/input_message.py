import json

from .plan.scene import Scene
from .plan.subscene import Subscene


class InputMessage:
    """
    Structured input message for communicating with the LLM.
    Contains context information including history, scene graph, and current state.
    """

    def __init__(self, 
                 user_message: str,
                 history: list[dict[str, str]],
                 scenes: list[Scene],
                 current_scene: Scene | None = None,
                 current_subscene: Subscene | None = None):
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
        prompt_parts.append("\n- Scene property explanation:"
                            "name represents the name, globally unique, you can use name to refer to a scene."
                            "identification_condition represents the identification condition for entering this scene."
                            "state has two states: ACTIVE and INACTIVE. Only one scene can be in active state globally."
                            "subscenes are all the subscenes under this scene.")
        prompt_parts.append("\n- Subscene property explanation:"
                            "name represents the name, globally unique, you can use name to refer to a subscene."
                            "objective represents the goal of this subscene. When the agent enters this subscene, the conversation should be organized according to this objective."
                            "type has three types: START, END, and NORMAL, representing that this subscene is a start scene, end scene, or normal scene respectively."
                            "state has two states: ACTIVE and INACTIVE. Only one subscene can be in active state globally."
                            "mandatory indicates whether this subscene must be performed. Mandatory subscenes cannot be skipped."
                            "connections are all the connections under this subscene. Each connection has a target subscene and a transition condition.")
        prompt_parts.append("\n- Connection property explanation:"
                            "name represents the name, globally unique, you can use name to refer to a connection."
                            "from_subscene represents the source subscene of this connection"
                            "to_subscene represents the target subscene of this connection"
                            "condition represents the transition condition of this connection. When the conversation meets this condition description, the agent will jump from from_subscene to to_subscene.")
        prompt_parts.append("\n- OutputMessage property explanation:"
                            "response represents the agent's reply. After processing the user message, the agent will organize a reply based on the current state and user input."
                            "updated_scenes represents the updated list of scenes. After processing the user message, the agent may update the scene states."
                            "match_connection represents the connection matched by the agent. When the agent matches a connection, it will return this connection."
                            "reason represents the explanatory reason for returning this response, updated_scenes, and match_connection after processing according to requirements and rules.")
        prompt_parts.append("\n- Rules:")
        prompt_parts.append("\n- At most one scene and corresponding subscene can be selected globally at any moment")
        prompt_parts.append("\n- Requirements:")
        prompt_parts.append("\n- Input: user message, conversation history, scene_graph. Output: OutputMessage (json format)")
        prompt_parts.append("\n- After user input, the agent has two states: one is that no scene and subscene are currently selected, and the other is that a scene and subscene are currently selected."
                            "1. When the agent currently has no selected scene and subscene, you should first determine which scene in the scene_graph matches the user's conversation intent based on the user's input and each scene's identification_condition."
                            "If there is a matching scene, you should set this scene to active state, set the first subscene with type=start under this scene to active state, then organize your reply according to the objective description of this selected subscene, output the updated scene to OutputMessage's updated_scenes, output the reply to OutputMessage's response, and put your analysis reason into OutputMessage's reason."
                            "If there is no matching scene, you should organize your speech according to the information of all scenes (name and identification_condition description) to guide the user into one of your defined scenes, play a guiding role for the function, output the reply to OutputMessage's response, put your analysis reason into OutputMessage's reason, and do not fill in other content that is not updated."
                            "2. When the agent currently has selected scene and subscene, you should first iterate through all connections in the current subscene based on the user message to see if any connection's condition description is met."
                            "If a connection's condition description is met, the agent should jump from this connection's from_subscene to the specified to_subscene. The from_subscene's state should be set to INACTIVE, and the to_subscene's state should be set to ACTIVE. Based on this principle, the updated_scenes in OutputMessage should be updated by you. You should organize your reply according to the to_subscene's objective and put it into OutputMessage's response. OutputMessage's match_connection should be filled with the connection you just matched, and your analysis reason should be put into OutputMessage's reason. In particular, if the to_subscene you arrive at is a node with type=end, then all scene and subscene states in OutputMessage's updated_scenes should be reset to inactive, and your analysis reason should be put into OutputMessage's reason."
                            "If no connection is met, you should continue to organize your guiding speech according to the current subscene's objective and put it into OutputMessage's response, put your analysis reason into OutputMessage's reason, and do not fill in other content that is not updated in OutputMessage")
        prompt_parts.append("\n- Specifically, when you discover that the user is deliberately avoiding the choices you provide, you need to re-formulate your strategy based on understanding the original graph, especially what your ultimate goal is, and plan and create a new path that can eventually lead to the End node (including subscene and connection), and update your new strategy to the updated_scenes of OutputMessage.")
        
        return "\n".join(prompt_parts)