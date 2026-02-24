"""Tool decorator for registering functions as callable tools.

Usage — just decorate any typed function:

    from app.orchestration.tool import tool

    @tool
    def add(a: float, b: float) -> float:
        \"\"\"Add two numbers together.\"\"\"
        return a + b

The decorator reads:
- ``func.__name__``          → tool name
- ``inspect.getdoc(func)``   → description (full docstring, verbatim)
- ``inspect.signature`` + ``typing.get_type_hints``
                             → parameter names, JSON Schema types, required list

Python type annotations are mapped to JSON Schema types:

    int / float / complex  → "number"
    str                    → "string"
    bool                   → "boolean"
    list / tuple           → "array"
    dict                   → "object"
    anything else          → "string"   (safe fallback)

No per-parameter descriptions are extracted from the docstring — the full
docstring is already the description and the LLM is expected to read it.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Protocol, cast, get_type_hints


class ToolFunction(Protocol):
    """Protocol for functions decorated with @tool."""

    __tool_metadata__: "ToolMetadata"

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


# Import after protocol definition to avoid circular import
from .metadata import ToolMetadata  # noqa: E402

# ---------------------------------------------------------------------------
# Type → JSON Schema mapping
# ---------------------------------------------------------------------------

_PYTHON_TYPE_TO_JSON: dict[type, str] = {
    int: "number",
    float: "number",
    complex: "number",
    str: "string",
    bool: "boolean",
    list: "array",
    tuple: "array",
    dict: "object",
    bytes: "string",
}


def _py_type_to_json_schema_type(annotation: Any) -> str:
    """Map a Python type annotation to a JSON Schema type string.

    Handles plain types and simple generics (e.g. ``list[str]``).
    Falls back to ``"string"`` for unknown annotations.

    Args:
        annotation: A Python type annotation object.

    Returns:
        JSON Schema type string.
    """
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        return _PYTHON_TYPE_TO_JSON.get(origin, "string")
    return _PYTHON_TYPE_TO_JSON.get(annotation, "string")


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------

def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build an OpenAI-compatible JSON Schema from a function's signature.

    Only derives type and required-ness from the signature.
    All human-readable descriptions live in the tool's top-level ``description``
    field (the full docstring) — no per-parameter description is added here.

    Args:
        func: A typed Python function.

    Returns:
        JSON Schema dict with ``type``, ``properties``, ``required``, and
        ``additionalProperties`` fields.
    """
    try:
        hints = get_type_hints(func)
    except Exception:  # noqa: BLE001
        hints = {}

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}

    for param_name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = hints.get(param_name, Any)
        properties[param_name] = {"type": _py_type_to_json_schema_type(annotation)}

    return {"properties": properties}


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------

def tool(func: Callable[..., Any]) -> ToolFunction:
    """Register a typed function as a callable tool.

    Args:
        func: A typed Python function to register as a tool.

    Returns:
        The same function, decorated with ``__tool_metadata__``.

    Example:
        @tool
        def calculate_sum(a: float, b: float) -> float:
            \"\"\"Add two numbers together.

            Args:
                a: First addend.
                b: Second addend.
            \"\"\"
            return a + b
    """
    metadata = ToolMetadata(
        name=func.__name__,
        description=inspect.getdoc(func) or "",
        parameters=_build_parameters_schema(func),
        func=func,
    )
    object.__setattr__(func, "__tool_metadata__", metadata)
    return cast(ToolFunction, func)
