import json

from .plan.scene import Scene
from .plan.subscene import Subscene
from .system_prompt import get_chat_prompt


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
        
        # Build the messages list immediately upon initialization
        self.messages: list[dict[str, str]] = self._build_messages()
        
    def _build_system_message(self) -> dict[str, str]:
        """
        Construct the system message containing instructions, rules, and state.
        """
        return get_chat_prompt(
            scenes=self.scenes,
            current_scene=self.current_scene,
            current_subscene=self.current_subscene
        )

    def _build_messages(self) -> list[dict[str, str]]:
        """
        Build the full list of messages including system, history, and user message.
        """
        messages = []
        
        # 1. System Message (Instructions, Rules, State)
        messages.append(self._build_system_message())
        
        # 2. History Messages (User, Assistant, Tool)
        if self.history:
            messages.extend(self.history)
            
        # 3. Current User Message
        messages.append({
            "role": "user",
            "content": self.user_message
        })
        
        return messages

    def get_messages(self) -> list[dict[str, str]]:
        """
        Get the structured messages list for the LLM.
        
        Returns:
            list[dict[str, str]]: The list of messages.
        """
        return self.messages

    def to_llm_string(self) -> str:
        """
        Deprecated: Convert the input message to a string format suitable for the LLM.
        Kept for backward compatibility, but conceptually it just dumps the messages.
        """
        return json.dumps(self.messages, indent=2, ensure_ascii=False)