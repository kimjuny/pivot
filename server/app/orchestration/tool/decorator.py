"""Tool decorator for registering functions as callable tools.

Usage — just decorate any typed function and the schema is inferred automatically:

    from app.orchestration.tool import tool

    @tool
    def add(a: float, b: float) -> float:
        \"\"\"Add two numbers together.\"\"\"
        return a + b

The decorator reads:
- ``func.__name__``   → tool name
- ``func.__doc__``    → description (first non-blank paragraph of the docstring)
- ``inspect.signature`` + ``typing.get_type_hints`` → parameter names, types, and
  whether each has a default (used to populate the ``required`` list)

Python type annotations are mapped to JSON Schema types automatically:

    int / float / complex  → "number"
    str                    → "string"
    bool                   → "boolean"
    list / List / Sequence → "array"
    dict / Dict / Mapping  → "object"
    anything else          → "string"   (safe fallback)
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
    Falls back to ``"string"`` for anything unknown so the schema stays valid.

    Args:
        annotation: A Python type annotation object.

    Returns:
        JSON Schema type string.
    """
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        # For generic aliases like list[str], dict[str, int], etc.
        return _PYTHON_TYPE_TO_JSON.get(origin, "string")
    return _PYTHON_TYPE_TO_JSON.get(annotation, "string")


# ---------------------------------------------------------------------------
# Docstring helpers
# ---------------------------------------------------------------------------

def _extract_description(func: Callable[..., Any]) -> str:
    """Extract the full description from a function's docstring.

    Keeps everything up to (but not including) the first Google-style section
    header (``Args:``, ``Returns:``, ``Raises:``, ``Note:``, ``Notes:``,
    ``Example:``, ``Examples:``).  This preserves multi-paragraph descriptions
    and inline code examples that are essential for the LLM to understand how
    to use a tool correctly.

    Args:
        func: The function whose docstring to parse.

    Returns:
        Description string (may be multi-line), or an empty string if unavailable.
    """
    doc = inspect.getdoc(func)
    if not doc:
        return ""

    # Section headers that mark the end of the description body
    _SECTION_HEADERS = {
        "Args:",
        "Arguments:",
        "Parameters:",
        "Returns:",
        "Return:",
        "Raises:",
        "Raise:",
        "Note:",
        "Notes:",
        "Example:",
        "Examples:",
        "See Also:",
        "References:",
        "Yields:",
        "Yield:",
    }

    description_lines: list[str] = []
    for line in doc.splitlines():
        if line.strip() in _SECTION_HEADERS:
            break
        description_lines.append(line)

    # Strip trailing blank lines
    while description_lines and not description_lines[-1].strip():
        description_lines.pop()

    return "\n".join(description_lines).strip()


def _extract_param_descriptions(func: Callable[..., Any]) -> dict[str, str]:
    """Parse Google-style ``Args:`` section from a docstring for per-param descriptions.

    Args:
        func: The function whose docstring to parse.

    Returns:
        Mapping of parameter name to its description string.
    """
    doc = inspect.getdoc(func)
    if not doc:
        return {}

    descriptions: dict[str, str] = {}
    in_args = False
    current_param: str | None = None
    current_lines: list[str] = []

    for line in doc.splitlines():
        stripped = line.strip()

        if stripped in ("Args:", "Arguments:", "Parameters:"):
            in_args = True
            continue

        # Any other top-level section header ends Args parsing
        if in_args and stripped.endswith(":") and not line.startswith(" "):
            break

        if in_args:
            # Detect a new param entry: starts with "name:" or "name (type):"
            import re  # noqa: PLC0415
            param_match = re.match(r"^\s{4}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)", line)
            if param_match:
                if current_param:
                    descriptions[current_param] = " ".join(current_lines).strip()
                current_param = param_match.group(1)
                current_lines = [param_match.group(2)]
            elif current_param and line.startswith("        "):
                # Continuation line for the current param
                current_lines.append(stripped)

    if current_param:
        descriptions[current_param] = " ".join(current_lines).strip()

    return descriptions


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------

def _build_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Introspect a function and produce an OpenAI-compatible JSON Schema.

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
    param_descriptions = _extract_param_descriptions(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        # Skip *args, **kwargs, and self/cls
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        annotation = hints.get(param_name, Any)
        json_type = _py_type_to_json_schema_type(annotation)

        prop: dict[str, Any] = {"type": json_type}
        if param_name in param_descriptions:
            prop["description"] = param_descriptions[param_name]

        properties[param_name] = prop

        # Only add to required when there is no default value
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Public decorator
# ---------------------------------------------------------------------------

def tool(func: Callable[..., Any]) -> ToolFunction:
    """Register a typed function as a callable tool.

    Derives all schema information automatically from the function signature
    and docstring — no extra arguments needed.

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
        description=_extract_description(func),
        parameters=_build_parameters_schema(func),
        func=func,
    )
    object.__setattr__(func, "__tool_metadata__", metadata)
    return cast(ToolFunction, func)
