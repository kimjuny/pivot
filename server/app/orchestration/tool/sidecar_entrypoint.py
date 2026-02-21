"""Entrypoint for executing a single tool call inside a sidecar container."""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .manager import ToolManager

_PIVOT_CONTEXT_KEY = "__pivot_context"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _read_stdin_json() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return parsed


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-name", required=True)
    args = parser.parse_args()

    tool_kwargs = _read_stdin_json()
    pivot_context = tool_kwargs.pop(_PIVOT_CONTEXT_KEY, None)
    if pivot_context is not None and not isinstance(pivot_context, dict):
        pivot_context = None

    start_ts = time.perf_counter()
    tool_manager = ToolManager()
    tools_dir = Path(__file__).resolve().parent / "builtin"
    refresh_start_ts = time.perf_counter()
    tool_manager.refresh(tools_dir)
    refresh_ms = (time.perf_counter() - refresh_start_ts) * 1000

    include_diagnostics = os.getenv("PIVOT_SIDECAR_DIAGNOSTICS", "") in {"1", "true", "True"}

    try:
        exec_start_ts = time.perf_counter()
        result = tool_manager.execute_local(args.tool_name, **tool_kwargs)
        exec_ms = (time.perf_counter() - exec_start_ts) * 1000
        total_ms = (time.perf_counter() - start_ts) * 1000
        payload: dict[str, Any] = {"success": True, "result": _json_safe(result)}
        if include_diagnostics:
            payload["diagnostics"] = {
                "hostname": os.getenv("HOSTNAME", ""),
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "uid": os.getuid(),
                "gid": os.getgid(),
                "thread_id": threading.get_ident(),
                "pivot_context": pivot_context,
                "uid_map": _read_text(Path("/proc/self/uid_map")),
                "gid_map": _read_text(Path("/proc/self/gid_map")),
                "cgroup": _read_text(Path("/proc/self/cgroup")),
                "timings_ms": {
                    "refresh_ms": refresh_ms,
                    "execute_ms": exec_ms,
                    "total_ms": total_ms,
                },
            }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as exc:
        total_ms = (time.perf_counter() - start_ts) * 1000
        payload = {
            "success": False,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "timings_ms": {"total_ms": total_ms},
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
