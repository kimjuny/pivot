"""
Tool decorator for registering functions as callable tools.
"""

from collections.abc import Callable
from typing import Any, Protocol, cast


class ToolFunction(Protocol):
    """Protocol for functions decorated with @tool."""

    __tool_metadata__: "ToolMetadata"

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


# Import after protocol definition to avoid circular import
from .metadata import ToolMetadata  # noqa: E402


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[Callable[..., Any]], ToolFunction]:
    """
    Decorator to register a function as a tool with metadata.

    This decorator attaches metadata to the function without modifying its behavior.
    The metadata is used by the ToolManager for discovery and registration.

    Args:
        name: Unique identifier for the tool.
        description: Brief description of the tool's purpose.
        parameters: JSON Schema describing expected parameters in OpenAI format.

    Returns:
        Decorated function with attached metadata.

    Example:
        @tool(
            name="calculate_sum",
            description="Calculates the sum of two numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"],
                "additionalProperties": False
            }
        )
        def calculate_sum(a: float, b: float) -> float:
            return a + b
    """

    def decorator(func: Callable[..., Any]) -> ToolFunction:
        # Attach metadata to the function as an attribute
        metadata = ToolMetadata(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )
        # Use object.__setattr__ to bypass type checking for dynamic attribute
        object.__setattr__(func, "__tool_metadata__", metadata)
        return cast(ToolFunction, func)

    return decorator
