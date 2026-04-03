"""Lifecycle hooks for the external Mem0-style memory extension."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_RECALL_LIMIT = 5


def _as_string(value: Any) -> str | None:
    """Return one stripped string or ``None`` when the value is blank."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _as_positive_int(value: Any, *, fallback: int) -> int:
    """Return one positive integer or the provided fallback."""
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int | float):
        normalized = int(value)
        if normalized > 0:
            return normalized
    return fallback


def _installation_config(context: dict[str, Any]) -> dict[str, Any]:
    """Return the installation-scoped setup configuration."""
    payload = context.get("installation_config")
    return payload if isinstance(payload, dict) else {}


def _service_settings(context: dict[str, Any]) -> tuple[str | None, int]:
    """Resolve the external memory service endpoint and timeout."""
    installation = _installation_config(context)
    base_url = _as_string(installation.get("base_url"))
    return base_url, DEFAULT_TIMEOUT_SECONDS


def _namespace(context: dict[str, Any]) -> str:
    """Derive one stable user-plus-agent namespace for the memory service."""
    agent_id = context.get("agent_id")
    user = context.get("user")
    user_id = None
    username = None
    if isinstance(user, dict):
        raw_user_id = user.get("id")
        raw_username = user.get("username")
        if isinstance(raw_user_id, int | float) and not isinstance(raw_user_id, bool):
            user_id = int(raw_user_id)
        if isinstance(raw_username, str) and raw_username.strip():
            username = raw_username.strip()

    normalized_username = (
        username.replace(":", "-").replace("/", "-")
        if username is not None
        else "unknown"
    )
    if isinstance(agent_id, bool):
        normalized_agent_id = "unknown"
    elif isinstance(agent_id, int | float):
        normalized_agent_id = str(int(agent_id))
    else:
        normalized_agent_id = "unknown"
    normalized_user_id = str(user_id) if user_id is not None else "unknown"
    return (
        f"user:{normalized_user_id}:{normalized_username}"
        f":agent:{normalized_agent_id}"
    )


def _recall_limit(context: dict[str, Any]) -> int:
    """Return the default recall limit used by this sample extension."""
    return DEFAULT_RECALL_LIMIT


def _request_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Send one JSON HTTP request to the external memory service."""
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    http_request = request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise RuntimeError(
            f"Memory service request failed with status {exc.code}."
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Memory service is unavailable: {exc.reason}.") from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Memory service returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Memory service returned an invalid JSON payload.")
    return parsed


def _build_recall_request(context: dict[str, Any]) -> dict[str, Any]:
    """Build one recall request payload from hook context."""
    task_snapshot = context.get("task")
    return {
        "agent_id": context.get("agent_id"),
        "session_id": context.get("session_id"),
        "task_id": context.get("task_id"),
        "namespace": _namespace(context),
        "limit": _recall_limit(context),
        "task": task_snapshot if isinstance(task_snapshot, dict) else {},
    }


def _build_memory_candidate(context: dict[str, Any]) -> str | None:
    """Condense one completed task into a short memory candidate."""
    task = context.get("task")
    if not isinstance(task, dict):
        return None

    user_message = _as_string(task.get("user_message"))
    agent_answer = _as_string(task.get("agent_answer"))
    if user_message is None or agent_answer is None:
        return None

    condensed_answer = " ".join(agent_answer.split())
    if len(condensed_answer) > 240:
        condensed_answer = f"{condensed_answer[:237]}..."
    return f"User asked: {user_message} | Answered: {condensed_answer}"


def _build_persist_request(
    context: dict[str, Any],
    *,
    candidate: str,
) -> dict[str, Any]:
    """Build one persist request payload from hook context and candidate text."""
    task_snapshot = context.get("task")
    return {
        "agent_id": context.get("agent_id"),
        "session_id": context.get("session_id"),
        "task_id": context.get("task_id"),
        "namespace": _namespace(context),
        "candidate": candidate,
        "task": task_snapshot if isinstance(task_snapshot, dict) else {},
    }


def _format_memories(memories: list[dict[str, Any]]) -> str | None:
    """Render recalled memories into a prompt block body."""
    lines: list[str] = []
    for memory in memories:
        if not isinstance(memory, dict):
            continue
        content = _as_string(memory.get("content"))
        if content is None:
            continue
        lines.append(f"- {content}")
    if not lines:
        return None
    return (
        "## Retrieved Memory\n"
        "Use these recalled memories only when they are relevant to the new task.\n"
        + "\n".join(lines)
    )


def inject_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Recall memory from the external service before the task starts."""
    base_url, timeout_seconds = _service_settings(context)
    if base_url is None:
        return []

    try:
        payload = _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/v1/memories/recall",
            payload=_build_recall_request(context),
            timeout_seconds=timeout_seconds,
        )
    except RuntimeError as exc:
        return [
            {
                "type": "emit_event",
                "payload": {
                    "type": "observe",
                    "data": {
                        "type": "memory_recall_failed",
                        "message": str(exc),
                    },
                },
            }
        ]

    raw_memories = payload.get("memories")
    memories = raw_memories if isinstance(raw_memories, list) else []
    formatted = _format_memories(memories)
    if formatted is None:
        return []

    return [
        {
            "type": "append_prompt_block",
            "payload": {
                "target": "task_bootstrap",
                "position": "head",
                "content": formatted,
            },
        },
        {
            "type": "emit_event",
            "payload": {
                "type": "observe",
                "data": {
                    "type": "memory_recalled",
                    "retrieved_count": len(memories),
                },
            },
        },
    ]


def persist_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Persist one memory candidate after successful live task completion."""
    if context.get("execution_mode") != "live":
        return []

    base_url, timeout_seconds = _service_settings(context)
    if base_url is None:
        return []

    candidate = _build_memory_candidate(context)
    if candidate is None:
        return []

    try:
        payload = _request_json(
            method="POST",
            url=f"{base_url.rstrip('/')}/v1/memories/persist",
            payload=_build_persist_request(context, candidate=candidate),
            timeout_seconds=timeout_seconds,
        )
    except RuntimeError as exc:
        return [
            {
                "type": "emit_event",
                "payload": {
                    "type": "observe",
                    "data": {
                        "type": "memory_persist_failed",
                        "message": str(exc),
                    },
                },
            }
        ]

    stored_count = payload.get("stored_count")
    normalized_count = stored_count if isinstance(stored_count, int) else None
    return [
        {
            "type": "emit_event",
            "payload": {
                "type": "observe",
                "data": {
                    "type": "memory_persisted",
                    "stored_count": normalized_count,
                },
            },
        }
    ]
