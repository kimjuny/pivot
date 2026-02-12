"""
Tool metadata structure for storing tool information.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolMetadata:
    """
    Metadata for a registered tool function.

    Attributes:
        name: The unique identifier for the tool.
        description: A brief description of what the tool does.
        parameters: JSON Schema describing the expected parameters (OpenAI format).
        func: The actual callable function.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]

    def to_text(self) -> str:
        """
        Convert tool metadata to a human-readable text format for LLM consumption.

        Returns:
            A formatted string describing the tool's interface and purpose.
        """
        import json

        return f"""Tool: {self.name}
Description: {self.description}
Parameters: {json.dumps(self.parameters, ensure_ascii=False)}"""

    def to_dict(self) -> dict[str, Any]:
        """
        Convert tool metadata to a dictionary (excluding the function reference).

        Returns:
            Dictionary containing tool metadata fields.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_openai_format(self) -> dict[str, Any]:
        """
        Convert tool metadata to OpenAI function calling format.

        Returns:
            Dictionary in OpenAI tools format with type and function fields.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "strict": True,  # Enable structured outputs
            },
        }
