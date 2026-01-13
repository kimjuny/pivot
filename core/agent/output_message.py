import json

from .plan.connection import Connection
from .plan.scene import Scene


class OutputMessage:
    """
    Structured output message from the LLM.
    """

    def __init__(self, 
                response: str,
                updated_scenes: list[Scene],
                match_connection: Connection | None = None, 
                reason: str = ""):
        """
        Initialize an OutputMessage.

        Args:
            response (str): The response from the LLM.
            updated_scenes (List[Scene]): The updated scenes.
            match_connection (Optional[Connection]): The matched connection.
            reason (str): The reason for the whole response.
        """
        self.response = response
        self.updated_scenes = updated_scenes
        self.match_connection = match_connection
        self.reason = reason

    @classmethod
    def from_content(cls, content: str):
        """
        Create an OutputMessage from a content string.

        Args:
            content (str): The content string to parse.

        Returns:
            OutputMessage: The parsed OutputMessage.
        """
        data = json.loads(content)
        
        response = data.get("response", "")
        reason = data.get("reason", "")
        
        updated_scenes = []
        
        # Process updated scenes if present - connections are handled automatically by Scene.from_dict()
        if data.get("updated_scenes"):
            updated_scenes = [Scene.from_dict(scene_data) for scene_data in data["updated_scenes"]]
        
        # Process match connection if present
        match_connection = None
        if data.get("match_connection"):
            match_connection = Connection.from_dict(data["match_connection"])
        
        return cls(
            response=response,
            updated_scenes=updated_scenes,
            match_connection=match_connection,
            reason=reason
        )
        