import json
import re
from typing import Any

from app.models.agent import Connection, Scene


class OutputMessage:
    """
    Structured output message from the LLM.
    """

    def __init__(
        self,
        response: str,
        updated_scenes: list[Scene],
        match_connection: Connection | None = None,
        reason: str = "",
        reasoning: str = "",
        is_final: bool = True,
    ):
        """
        Initialize an OutputMessage.

        Args:
            response (str): The response from the LLM.
            updated_scenes (List[Scene]): The updated scenes.
            match_connection (Optional[Connection]): The matched connection.
            reason (str): The reason for the whole response.
            reasoning (str): The Chain-of-Thought reasoning content.
            is_final (bool): Whether this is the final parsed result or an intermediate streaming chunk.
        """
        self.response = response
        self.updated_scenes = updated_scenes
        self.match_connection = match_connection
        self.reason = reason
        self.reasoning = reasoning
        self.is_final = is_final

    @classmethod
    def from_content(cls, content: str):
        """
        Create an OutputMessage from a content string (Markdown format).

        Args:
            content (str): The content string to parse.

        Returns:
            OutputMessage: The parsed OutputMessage.
        """
        # Initialize defaults
        reason = ""
        response = ""
        updated_scenes = []
        match_connection = None

        try:
            # Extract Reason
            reason_match = re.search(
                r"## Reason\s*(.*?)\s*## Response", content, re.DOTALL | re.IGNORECASE
            )
            if reason_match:
                reason = reason_match.group(1).strip()

            # Extract Response
            # Look for Response followed by Update Scenes OR Match Connection OR end of string
            response_match = re.search(
                r"## Response\s*(.*?)\s*(?:## Update(?:d)? Scenes|## Match(?:ed)? Connection|$)",
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if response_match:
                response = response_match.group(1).strip()

            # Extract Update Scenes
            updated_scenes_match = re.search(
                r"## Update(?:d)? Scenes\s*.*?```json\s*(.*?)\s*```",
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if updated_scenes_match:
                json_str = updated_scenes_match.group(1).strip()
                if json_str and json_str.lower() != "null":
                    try:
                        scenes_data = json.loads(json_str)
                        if isinstance(scenes_data, list):
                            updated_scenes = [
                                Scene.from_dict(scene_data)
                                for scene_data in scenes_data
                            ]
                    except json.JSONDecodeError:
                        pass

            # Extract Match Connection
            match_connection_match = re.search(
                r"## Match(?:ed)? Connection\s*.*?```json\s*(.*?)\s*```",
                content,
                re.DOTALL | re.IGNORECASE,
            )
            if match_connection_match:
                json_str = match_connection_match.group(1).strip()
                if json_str and json_str.lower() != "null":
                    try:
                        conn_data = json.loads(json_str)
                        # Check if it's a valid object (not empty)
                        if isinstance(conn_data, dict) and conn_data:
                            match_connection = Connection.from_dict(conn_data)
                    except json.JSONDecodeError:
                        pass

        except Exception:
            # Fallback for parsing errors
            pass

        return cls(
            response=response,
            updated_scenes=updated_scenes,
            match_connection=match_connection,
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the OutputMessage to a dictionary.

        Returns:
            dict: The dictionary representation of the OutputMessage.
        """
        return {
            "response": self.response,
            "updated_scenes": [scene.to_dict() for scene in self.updated_scenes],
            "match_connection": self.match_connection.to_dict()
            if self.match_connection
            else None,
            "reason": self.reason,
            "reasoning": self.reasoning,
            "is_final": self.is_final,
        }
