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

Parameter descriptions and return descriptions are extracted from Google-style
docstrings (``Args``/``Returns``) and can be overridden via decorator kwargs.
"""

from __future__ import annotations

import inspect
import re
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Protocol,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from collections.abc import Callable


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


def _parse_docstring_sections(docstring: str) -> tuple[dict[str, str], str]:
    """Extract Args/Returns descriptions from a Google-style docstring.

    Args:
        docstring: Raw function docstring.

    Returns:
        A tuple of ``(parameter_descriptions, return_description)``.
    """
    parameter_descriptions: dict[str, str] = {}
    return_lines: list[str] = []
    mode: Literal["none", "args", "returns"] = "none"
    current_arg_name: str | None = None

    for raw_line in docstring.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            continue

        if stripped in {"Args:", "Arguments:", "Parameters:"}:
            mode = "args"
            current_arg_name = None
            continue
        if stripped == "Returns:":
            mode = "returns"
            current_arg_name = None
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_ ]*:\s*$", stripped):
            mode = "none"
            current_arg_name = None
            continue

        if mode == "args":
            arg_match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
            if arg_match:
                arg_name = arg_match.group(1)
                arg_desc = arg_match.group(2).strip()
                parameter_descriptions[arg_name] = arg_desc
                current_arg_name = arg_name
                continue

            if current_arg_name and line.startswith(" "):
                continuation = stripped
                if continuation:
                    previous = parameter_descriptions[current_arg_name]
                    parameter_descriptions[current_arg_name] = (
                        f"{previous} {continuation}"
                    ).strip()
            continue

        if mode == "returns":
            return_lines.append(stripped)

    return parameter_descriptions, " ".join(return_lines).strip()


def _annotation_to_json_schema(annotation: Any) -> dict[str, Any]:
    """Map Python type annotations to JSON Schema snippets.

    Args:
        annotation: A Python annotation object.

    Returns:
        JSON Schema snippet for one parameter.
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in {UnionType, Union}:
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1:
            return _annotation_to_json_schema(non_none_args[0])
        return {"type": "string"}

    if origin in {list, tuple, set}:
        if args:
            return {
                "type": "array",
                "items": _annotation_to_json_schema(args[0]),
            }
        return {"type": "array"}

    if origin is dict:
        return {"type": "object"}

    if origin is Literal:
        literal_values = [
            value for value in args if isinstance(value, str | int | float | bool)
        ]
        if literal_values:
            first_literal = literal_values[0]
            base_type = _PYTHON_TYPE_TO_JSON.get(type(first_literal), "string")
            return {"type": base_type, "enum": literal_values}
        return {"type": "string"}

    if annotation is Any:
        return {"type": "string"}

    return {"type": _PYTHON_TYPE_TO_JSON.get(annotation, "string")}


def _is_annotation_optional(annotation: Any) -> bool:
    """Whether an annotation allows None."""
    origin = get_origin(annotation)
    if origin not in {UnionType, Union}:
        return False
    return type(None) in get_args(annotation)


# ---------------------------------------------------------------------------
# Schema builder
# ---------------------------------------------------------------------------


def _build_parameters_schema(
    func: Callable[..., Any],
    parameter_descriptions: dict[str, str],
) -> dict[str, Any]:
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
        parameter_schema = _annotation_to_json_schema(annotation)
        parameter_description = parameter_descriptions.get(param_name, "").strip()
        if parameter_description:
            parameter_schema["description"] = parameter_description
        properties[param_name] = parameter_schema

        if param.default is inspect.Parameter.empty and not _is_annotation_optional(
            annotation
        ):
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


def tool(
    func: Callable[..., Any] | None = None,
    *,
    tool_type: ToolType = "normal",
    parameter_descriptions: dict[str, str] | None = None,
    return_description: str | None = None,
) -> ToolFunction | Callable[[Callable[..., Any]], ToolFunction]:
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

    def _decorate(target: Callable[..., Any]) -> ToolFunction:
        docstring = inspect.getdoc(target) or ""
        doc_param_descriptions, doc_return_description = _parse_docstring_sections(
            docstring
        )
        merged_parameter_descriptions = dict(doc_param_descriptions)
        if parameter_descriptions:
            merged_parameter_descriptions.update(parameter_descriptions)

        effective_return_description = (return_description or "").strip()
        if not effective_return_description:
            effective_return_description = doc_return_description

        metadata = ToolMetadata(
            name=target.__name__,
            description=docstring,
            parameters=_build_parameters_schema(target, merged_parameter_descriptions),
            parameter_descriptions=merged_parameter_descriptions,
            return_description=effective_return_description,
            func=target,
            tool_type=tool_type,
        )
        object.__setattr__(target, "__tool_metadata__", metadata)
        return cast(ToolFunction, target)

    if func is None:
        return _decorate
    return _decorate(func)
