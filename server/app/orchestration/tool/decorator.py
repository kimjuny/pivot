"""Tool decorator for registering functions as callable tools.

Usage::

    from typing import Annotated

    from app.orchestration.tool import tool, Param

    @tool(description="Add two numbers together.")
    def add(
        a: Annotated[float, Param("First addend.")],
        b: Annotated[float, Param("Second addend.")],
    ) -> float:
        return a + b

The decorator reads:

- ``func.__name__``                       → tool name
- ``description`` keyword argument        → tool description shown to the LLM
- ``inspect.signature``                   → parameter names, defaults, required list
- ``Annotated[T, Param("...")]`` hints    → per-parameter descriptions

Python type annotations are mapped to JSON Schema types:

    int / float / complex  → "number"
    str                    → "string"
    bool                   → "boolean"
    list / tuple           → "array"
    dict                   → "object"
    anything else          → "string"   (safe fallback)
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Protocol,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True)
class Param:
    """LLM-facing description for one tool parameter.

    Used inside ``Annotated`` type hints to attach a human-readable
    description that the LLM will see in the tool's JSON Schema.

    Set ``hidden=True`` to exclude a parameter from the LLM-visible schema
    while keeping it in the Python function signature for runtime use.

    Example::

        def search(
            query: Annotated[str, Param("Search query string.")],
            limit: Annotated[int, Param("Max results.")] = 5,
        ): ...
    """

    description: str
    hidden: bool = False


class ToolFunction(Protocol):
    """Protocol for functions decorated with @tool."""

    __tool_metadata__: ToolMetadata

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...


# Import after protocol definition to avoid circular import
from .metadata import ToolMetadata, ToolType  # noqa: E402

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


def _unwrap_annotated(annotation: Any) -> tuple[Any, Param | None]:
    """Extract base type and Param metadata from ``Annotated[T, Param(...)]``."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        base_type = args[0]
        for extra in args[1:]:
            if isinstance(extra, Param):
                return base_type, extra
        return base_type, None
    return annotation, None


def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build an OpenAI-compatible JSON Schema from a function's signature.

    Extracts:
    - Parameter types from annotations (unwraps ``Annotated``)
    - Per-parameter descriptions from ``Param`` metadata
    - Required/optional from presence/absence of default values
    - Default values from the signature

    Args:
        func: A typed Python function.

    Returns:
        JSON Schema dict with ``type``, ``properties``, and ``required`` fields.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    sig = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = hints.get(param_name, Any)
        base_type, param_meta = _unwrap_annotated(annotation)

        if param_meta is not None and param_meta.hidden:
            continue

        prop: dict[str, Any] = {"type": _py_type_to_json_schema_type(base_type)}

        if param_meta is not None and param_meta.description:
            prop["description"] = param_meta.description

        if param.default is inspect.Parameter.empty:
            required.append(param_name)
        else:
            prop["default"] = param.default

        properties[param_name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------


def tool(
    func: Callable[..., Any] | None = None,
    *,
    description: str | None = None,
    tool_type: ToolType = "normal",
) -> ToolFunction | Callable[[Callable[..., Any]], ToolFunction]:
    """Register a typed function as a callable tool.

    Args:
        func: A typed Python function to register as a tool.
        description: LLM-facing tool description. Falls back to the first
            paragraph of the docstring when not provided.
        tool_type: Execution category for this tool.

    Returns:
        The same function, decorated with ``__tool_metadata__``.

    Example::

        @tool(description="Search the web.")
        def search(
            query: Annotated[str, Param("Search query.")],
            limit: Annotated[int, Param("Max results.")] = 5,
        ): ...
    """

    def _decorate(target: Callable[..., Any]) -> ToolFunction:
        tool_description = description
        if tool_description is None:
            doc = inspect.getdoc(target) or ""
            tool_description = doc.split("\n\n")[0].strip()

        metadata = ToolMetadata(
            name=target.__name__,
            description=tool_description,
            parameters=_build_parameters_schema(target),
            func=target,
            tool_type=tool_type,
        )
        object.__setattr__(target, "__tool_metadata__", metadata)
        return cast("ToolFunction", target)

    if func is None:
        return _decorate
    return _decorate(func)
