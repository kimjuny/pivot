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
        input_schema: Description of the expected input format/parameters.
        output_schema: Description of the output format/return value.
        func: The actual callable function.
    """

    name: str
    description: str
    input_schema: str
    output_schema: str
    func: Callable[..., Any]

    def to_text(self) -> str:
        """
        Convert tool metadata to a human-readable text format for LLM consumption.

        Returns:
            A formatted string describing the tool's interface and purpose.
        """
        return f"""Tool: {self.name}
Description: {self.description}
Input: {self.input_schema}
Output: {self.output_schema}"""

    def to_dict(self) -> dict[str, str]:
        """
        Convert tool metadata to a dictionary (excluding the function reference).

        Returns:
            Dictionary containing tool metadata fields.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }
