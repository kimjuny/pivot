"""Lint service for Python source code analysis.

Provides three progressive check tiers designed for real-time editor feedback:

- ``check_ast``     — built-in syntax check, in-process, < 5 ms.
- ``check_ruff``    — style / import / bug lints via ruff CLI, ~100–300 ms.
- ``check_pyright`` — full type checking via pyright CLI, ~1–3 s.

All returned diagnostics use **1-based** line and column numbers so they can
be forwarded directly to Monaco Editor's ``setModelMarkers`` API without any
coordinate transformation.

The service is intentionally stateless and dependency-free so the same
functions can be called both from HTTP endpoints and from Agent tool-calls.
"""

from __future__ import annotations

import ast
import json
import logging
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.models.tool import LintDiagnostic

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# Project root that contains pyproject.toml — lets ruff pick up its config.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Server source root — added to pyright's extraPaths so that
# ``from app.orchestration.tool import tool`` resolves correctly.
_SERVER_SRC = str(Path(__file__).resolve().parent.parent.parent)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LintResult:
    """Structured result returned by every lint check function.

    Attributes:
        check: Which checker produced this result.
        diagnostics: Ordered list of diagnostics (may be empty).
        elapsed_ms: Wall-clock time the check took in milliseconds.
        error_count: Number of diagnostics with severity ``"error"``.
        warning_count: Number of diagnostics with severity ``"warning"``.
    """

    check: Literal["ast", "ruff", "pyright"]
    diagnostics: list[LintDiagnostic]
    elapsed_ms: float
    error_count: int
    warning_count: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_cmd(name: str) -> list[str]:
    """Resolve the command prefix for a CLI tool.

    Checks the PATH first (works when the Poetry venv ``bin/`` is active, which
    is the normal case under ``poetry run uvicorn``).  Falls back to
    ``poetry run <name>`` for development environments where only the project
    venv is available.

    Args:
        name: Executable name, e.g. ``"ruff"`` or ``"pyright"``.

    Returns:
        Argv prefix list, e.g. ``["ruff"]`` or ``["poetry", "run", "ruff"]``.
    """
    if shutil.which(name):
        return [name]
    return ["poetry", "run", name]


def _extract_json(raw: str) -> str | None:
    """Extract the first complete JSON value (object or array) from a string.

    Some tools (e.g. pyright on first invocation) print non-JSON platform /
    environment information to stdout *before* the actual JSON payload.  This
    function locates the first JSON-start character — either ``{`` (object) or
    ``[`` (array, as ruff emits) — and returns the substring from that point
    so it can be passed directly to ``json.loads``.

    Args:
        raw: Raw stdout string from a subprocess call.

    Returns:
        A substring beginning at the first ``{`` or ``[``, whichever comes
        first; ``None`` if neither character is present.
    """
    obj_idx = raw.find("{")
    arr_idx = raw.find("[")

    # Pick whichever start character appears first (ignore -1 sentinels)
    candidates = [i for i in (obj_idx, arr_idx) if i != -1]
    if not candidates:
        return None
    return raw[min(candidates):]


def _count_severities(
    diagnostics: list[LintDiagnostic],
) -> tuple[int, int]:
    """Count error and warning diagnostics.

    Args:
        diagnostics: List of LintDiagnostic objects.

    Returns:
        Tuple of ``(error_count, warning_count)``.
    """
    errors = sum(1 for d in diagnostics if d.severity == "error")
    warnings = sum(1 for d in diagnostics if d.severity == "warning")
    return errors, warnings


# ---------------------------------------------------------------------------
# Public check functions
# ---------------------------------------------------------------------------


def check_ast(
    source_code: str,
    *,
    filename: str = "<tool>",
    username: str = "<unknown>",
) -> LintResult:
    """Run Python's built-in AST parser and return any syntax errors.

    Runs entirely in-process — no subprocess, no temp files — completing in
    well under 10 ms even for large files.

    Args:
        source_code: Python source code to analyse.
        filename: Logical filename for log messages (e.g. ``"my_tool.py"``).
        username: Username of the tool author, used for structured logging.

    Returns:
        A :class:`LintResult` with at most one diagnostic for a SyntaxError.
    """
    t0 = time.perf_counter()
    diagnostics: list[LintDiagnostic] = []

    try:
        ast.parse(source_code)
    except SyntaxError as exc:
        line = exc.lineno or 1
        col = exc.offset or 1
        end_line = getattr(exc, "end_lineno", None) or line
        end_col = getattr(exc, "end_offset", None) or col
        diagnostics.append(
            LintDiagnostic(
                line=line,
                col=col,
                end_line=end_line,
                end_col=end_col,
                severity="error",
                message=exc.msg,
                source="ast",
                code=None,
            )
        )

    elapsed = (time.perf_counter() - t0) * 1000
    errors, warnings = _count_severities(diagnostics)

    logger.info(
        "[lint:ast] user=%s file=%s elapsed=%.1fms errors=%d warnings=%d",
        username,
        filename,
        elapsed,
        errors,
        warnings,
    )

    return LintResult(
        check="ast",
        diagnostics=diagnostics,
        elapsed_ms=elapsed,
        error_count=errors,
        warning_count=warnings,
    )


def check_ruff(
    source_code: str,
    *,
    filename: str = "<tool>",
    username: str = "<unknown>",
) -> LintResult:
    """Run ``ruff check`` and return normalised diagnostics.

    Writes source to a temporary file, invokes the ruff CLI, and parses its
    JSON output.  All coordinates are 1-based to match Monaco Editor.

    Args:
        source_code: Python source code to analyse.
        filename: Logical filename for log messages.
        username: Username of the tool author, used for structured logging.

    Returns:
        A :class:`LintResult` with zero or more ruff diagnostics.
    """
    t0 = time.perf_counter()
    diagnostics: list[LintDiagnostic] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "tool_lint.py"
        tmp_file.write_text(source_code, encoding="utf-8")

        cmd = [
            *_find_cmd("ruff"),
            "check",
            str(tmp_file),
            "--output-format=json",
            "--no-cache",
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_PROJECT_ROOT),
        )

        raw = proc.stdout.strip()
        if raw:
            json_str = _extract_json(raw)
            if json_str is None:
                logger.warning(
                    "[lint:ruff] user=%s file=%s — non-JSON output: %.200s",
                    username,
                    filename,
                    raw,
                )
            else:
                try:
                    items: list[dict[str, Any]] = json.loads(json_str)
                    for item in items:
                        loc = item.get("location", {})
                        end_loc = item.get("end_location", {})
                        # ruff JSON uses 1-based row / column
                        diagnostics.append(
                            LintDiagnostic(
                                line=loc.get("row", 1),
                                col=loc.get("column", 1),
                                end_line=end_loc.get("row", loc.get("row", 1)),
                                end_col=end_loc.get("column", loc.get("column", 1)),
                                severity="warning",
                                message=item.get("message", ""),
                                source="ruff",
                                code=item.get("code"),
                            )
                        )
                except json.JSONDecodeError:
                    logger.warning(
                        "[lint:ruff] user=%s file=%s — JSON decode error: %.200s",
                        username,
                        filename,
                        json_str,
                    )

    elapsed = (time.perf_counter() - t0) * 1000
    errors, warnings = _count_severities(diagnostics)

    logger.info(
        "[lint:ruff] user=%s file=%s elapsed=%.1fms errors=%d warnings=%d",
        username,
        filename,
        elapsed,
        errors,
        warnings,
    )

    return LintResult(
        check="ruff",
        diagnostics=diagnostics,
        elapsed_ms=elapsed,
        error_count=errors,
        warning_count=warnings,
    )


def check_pyright(
    source_code: str,
    *,
    filename: str = "<tool>",
    username: str = "<unknown>",
) -> LintResult:
    """Run ``pyright`` and return normalised diagnostics.

    Writes source and a minimal ``pyrightconfig.json`` to a temporary
    directory.  The config adds the server source tree to ``extraPaths`` so
    that imports like ``from app.orchestration.tool import tool`` resolve
    correctly.

    pyright occasionally emits non-JSON platform/environment information on
    its first invocation.  :func:`_extract_json` strips any such prefix before
    parsing.

    Args:
        source_code: Python source code to analyse.
        filename: Logical filename for log messages.
        username: Username of the tool author, used for structured logging.

    Returns:
        A :class:`LintResult` with zero or more pyright diagnostics.
    """
    t0 = time.perf_counter()
    diagnostics: list[LintDiagnostic] = []

    severity_map: dict[str, Literal["error", "warning", "info"]] = {
        "error": "error",
        "warning": "warning",
        "information": "info",
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "tool_lint.py"
        tmp_file.write_text(source_code, encoding="utf-8")

        pyright_cfg: dict[str, Any] = {
            "include": ["tool_lint.py"],
            "pythonVersion": "3.10",
            "typeCheckingMode": "standard",
            "extraPaths": [_SERVER_SRC],
            "reportUnusedImport": "warning",
            "reportUnusedVariable": "warning",
            "reportOptionalMemberAccess": "error",
            "reportGeneralTypeIssues": "error",
        }
        (Path(tmp_dir) / "pyrightconfig.json").write_text(
            json.dumps(pyright_cfg), encoding="utf-8"
        )

        cmd = [*_find_cmd("pyright"), str(tmp_file), "--outputjson"]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=tmp_dir,
        )

        raw = proc.stdout.strip()
        if raw:
            json_str = _extract_json(raw)
            if json_str is None:
                logger.warning(
                    "[lint:pyright] user=%s file=%s — no JSON found in output: %.200s",
                    username,
                    filename,
                    raw,
                )
            else:
                try:
                    output: dict[str, Any] = json.loads(json_str)
                    for diag in output.get("generalDiagnostics", []):
                        # pyright uses LSP ranges: 0-based line, 0-based character
                        rng = diag.get("range", {})
                        start = rng.get("start", {})
                        end = rng.get("end", {})
                        raw_sev: str = diag.get("severity", "error")
                        severity = severity_map.get(raw_sev, "error")
                        diagnostics.append(
                            LintDiagnostic(
                                line=start.get("line", 0) + 1,
                                col=start.get("character", 0) + 1,
                                end_line=end.get("line", 0) + 1,
                                end_col=end.get("character", 0) + 1,
                                severity=severity,
                                message=diag.get("message", ""),
                                source="pyright",
                                code=diag.get("rule"),
                            )
                        )
                except json.JSONDecodeError:
                    logger.warning(
                        "[lint:pyright] user=%s file=%s — JSON decode error: %.200s",
                        username,
                        filename,
                        json_str,
                    )

    elapsed = (time.perf_counter() - t0) * 1000
    errors, warnings = _count_severities(diagnostics)

    logger.info(
        "[lint:pyright] user=%s file=%s elapsed=%.1fms errors=%d warnings=%d",
        username,
        filename,
        elapsed,
        errors,
        warnings,
    )

    return LintResult(
        check="pyright",
        diagnostics=diagnostics,
        elapsed_ms=elapsed,
        error_count=errors,
        warning_count=warnings,
    )
