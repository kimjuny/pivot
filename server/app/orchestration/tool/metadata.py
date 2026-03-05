"""
Tool metadata structure for storing tool information.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

ToolType = Literal["normal", "sandbox"]


@dataclass
class ToolMetadata:
    """
    Metadata for a registered tool function.

    Attributes:
        name: The unique identifier for the tool.
        description: A brief description of what the tool does.
        parameters: JSON Schema describing the expected parameters (OpenAI format).
        parameter_descriptions: Human-readable descriptions for each parameter.
        return_description: Human-readable explanation of the tool return payload.
        tool_type: Execution category for this tool.
        func: The actual callable function.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    parameter_descriptions: dict[str, str]
    return_description: str
    func: Callable[..., Any]
    tool_type: ToolType = "normal"

    def to_text(self) -> str:
        """
        Convert tool metadata to a human-readable text format for LLM consumption.

        Returns:
            A formatted string describing the tool's interface and purpose.
        """
        import json

        return f"""Tool: {self.name}
Type: {self.tool_type}
Description: {self.description}
Parameters: {json.dumps(self.parameters, ensure_ascii=False)}
Parameter Descriptions: {json.dumps(self.parameter_descriptions, ensure_ascii=False)}
Return Description: {self.return_description}"""

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
            "parameter_descriptions": self.parameter_descriptions,
            "return_description": self.return_description,
            "tool_type": self.tool_type,
        }

    def to_openai_format(self) -> dict[str, Any]:
        """
        Convert tool metadata to OpenAI function calling format.

        Returns:
            Dictionary in OpenAI tools format with type and function fields.
        """
        function_description = self.description
        if self.return_description:
            function_description = f"{self.description}\n\nReturn value description: {self.return_description}"
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": function_description,
                "parameters": self.parameters,
                "strict": True,  # Enable structured outputs
            },
        }
