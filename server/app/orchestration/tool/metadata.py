"""Tool metadata structure for storing tool information."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

ToolType = Literal["normal", "sandbox"]


@dataclass
class ToolMetadata:
    """Metadata for a registered tool function.

    Attributes:
        name: The unique identifier for the tool.
        description: LLM-facing tool description.
        parameters: JSON Schema describing the expected parameters.
        func: The actual callable function.
        tool_type: Execution category (internal, not exposed to the LLM).
    """

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    tool_type: ToolType = "normal"

    def to_dict(self) -> dict[str, Any]:
        """Convert tool metadata to a dictionary (excluding the function reference).

        Returns:
            Dictionary compatible with OpenAI function calling format.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_openai_format(self) -> dict[str, Any]:
        """Convert tool metadata to OpenAI function calling format.

        Returns:
            Dictionary in OpenAI tools format with type and function fields.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
