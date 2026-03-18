"""ReAct orchestration module.

This package exposes the primary orchestration entry points while avoiding eager
imports that would otherwise create circular dependencies during test startup.
"""

from typing import Any

from .context import ReactContext
from .prompt_template import build_runtime_system_prompt, build_runtime_user_prompt

__all__ = [
    "ReactContext",
    "ReactEngine",
    "build_runtime_system_prompt",
    "build_runtime_user_prompt",
]


def __getattr__(name: str) -> Any:
    """Load heavyweight exports lazily to avoid import-time cycles."""
    if name == "ReactEngine":
        from .engine import ReactEngine

        return ReactEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
