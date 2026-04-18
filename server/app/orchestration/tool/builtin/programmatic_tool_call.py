"""Built-in tool: execute a small Python snippet that composes other registered tools.

Design principle
----------------
LLMs sometimes need to *chain* or *combine* multiple tools in a single step
(e.g. uppercase the result of word_count, or sum a list of add() calls).
Rather than forcing the LLM to make N sequential tool calls, this tool lets it
write a tiny Python program that calls the other tools directly.

How it works
------------
1. The LLM writes ``python_code`` that imports tools by their registered name::

       from uppercase import uppercase
       from word_count import word_count

       result = uppercase(word_count("hello world"))   # demo: wrong types on purpose
       result = f"{word_count('hello world')} words"

2. A custom ``__import__`` hook intercepts every ``import`` / ``from … import``
   call made *inside* the exec sandbox.  If the module name matches a key in the
   ToolManager registry, the real callable is injected into the sandbox namespace
   instead of a real Python module.  Unknown imports fall through to the normal
   Python importer so standard-library helpers (math, json, re …) still work.

3. The snippet runs inside a restricted ``exec`` environment whose globals
   contain only builtins + the import hook.  No filesystem, no network, no
   ``__import__`` escape.

4. After execution the value stored in the ``result`` variable is returned.
   If the snippet raises an exception, the exception is **re-raised** so the
   engine can record it as a tool failure and surface it to the LLM as an
   error result rather than a normal answer.

Security note
-------------
``exec`` is inherently unrestricted in CPython.  This sandbox prevents
*accidental* misuse (wrong imports, typos) but is NOT a security boundary
against a malicious actor.  Keep this tool out of untrusted / public-facing
deployments.

Runtime tool-callables injection
---------------------------------
The ``tool_callables`` dict is intentionally **not** obtained via
``get_tool_manager()`` inside this function.  The global singleton only contains
built-in (shared) tools loaded at startup; private workspace tools are absent.

Instead, the ``react.py`` request handler replaces the ``func`` attribute on
this tool's ``ToolMetadata`` with a closure that already has the full
request-scoped ``tool_callables`` bound in.  See
``make_programmatic_tool_call(tool_callables)`` below.
"""

from __future__ import annotations

import builtins
import logging
from typing import Any

from app.orchestration.tool import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reusable exec core - extracted so both the default stub and any dynamically
# bound closure share exactly the same logic.
# ---------------------------------------------------------------------------


def _run_snippet(python_code: str, tool_callables: dict[str, Any]) -> str:
    """Execute *python_code* inside a sandbox with *tool_callables* available.

    Args:
        python_code: Python source code. Must assign output to ``result``.
        tool_callables: Mapping of tool name → callable, injected via import hook.

    Returns:
        ``str(result)`` on success.

    Raises:
        RuntimeError: Wraps any exception raised inside the snippet, preserving
            the original traceback message so the engine can record it and feed
            it back to the LLM as a tool error.
    """
    _real_import = builtins.__import__

    class _FakeModule:
        """Minimal module shim that exposes a single callable attribute."""

        def __init__(self, name: str, func: Any) -> None:
            self.__name__ = name
            setattr(self, name, func)

    def _sandboxed_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name in tool_callables:
            mod = _FakeModule(name, tool_callables[name])
            if fromlist and globals is not None:
                for attr in fromlist:
                    if hasattr(mod, attr):
                        globals[attr] = getattr(mod, attr)
            return mod
        return _real_import(name, globals, locals, fromlist, level)

    sandbox_globals: dict[str, Any] = {
        "__builtins__": {**vars(builtins), "__import__": _sandboxed_import},
    }

    try:
        exec(python_code, sandbox_globals)
    except Exception as exc:
        # Re-raise so the engine marks this tool call as failed and the LLM
        # receives a structured error result instead of a silent "Error:" string.
        logger.error(
            "programmatic_tool_call snippet raised %s: %s\n--- snippet ---\n%s\n---",
            type(exc).__name__,
            exc,
            python_code,
        )
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

    output = sandbox_globals.get("result")
    if output is None:
        raise RuntimeError("No 'result' variable was assigned in the snippet.")

    return str(output)


# ---------------------------------------------------------------------------
# Factory - called by react.py to create a request-scoped closure
# ---------------------------------------------------------------------------


def make_programmatic_tool_call(tool_callables: dict[str, Any]):
    """Return a bound implementation of programmatic_tool_call.

    This factory is called once per ReAct request by ``react.py`` after the
    full request-scoped ToolManager (shared + private tools) has been built.
    The returned function is used to **replace** the ``func`` on the
    ToolMetadata for ``programmatic_tool_call``, giving the snippet access to
    private workspace tools without exposing them as extra parameters in the
    LLM-facing schema.

    Args:
        tool_callables: Mapping of tool name → callable from the request-scoped
            ToolManager (includes both shared and private tools).

    Returns:
        A callable with the same signature as ``programmatic_tool_call``.
    """

    def _bound(python_code: str) -> str:
        return _run_snippet(python_code, tool_callables)

    return _bound


# ---------------------------------------------------------------------------
# Registered @tool stub - uses only the global singleton (shared tools).
# react.py replaces .func at request time via make_programmatic_tool_call().
# ---------------------------------------------------------------------------


@tool
def programmatic_tool_call(python_code: str) -> str:
    """Execute a Python snippet that may call other registered tools by name.

    Use ``from <tool_name> import <tool_name>`` to pull in any tool that is
    currently registered.  Store the final answer in a variable called
    ``result``; its string representation is returned.

    Example::

        from uppercase import uppercase
        from word_count import word_count

        text = "hello world"
        result = f"{uppercase(text)} has {word_count(text)} words"

    Args:
        python_code (required, str): Python snippet to execute. It must assign
            the final output to a variable named ``result``.

    Returns:
        String representation of ``result``.

    Raises:
        RuntimeError: If the snippet raises any exception or does not assign
            ``result``.
    """
    from app.orchestration.tool import get_tool_manager

    tool_callables: dict[str, Any] = {
        meta.name: meta.func for meta in get_tool_manager().list_tools()
    }
    return _run_snippet(python_code, tool_callables)
