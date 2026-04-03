"""Lifecycle hooks for the sample external-memory extension."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_PATH = "/tmp/pivot-sample-memory.json"
MEMORY_PATH_ENV = "PIVOT_SAMPLE_MEMORY_PATH"
MAX_MEMORIES_PER_AGENT = 5


def _memory_path() -> Path:
    """Return the external store path used by the sample extension."""
    return Path(os.environ.get(MEMORY_PATH_ENV, DEFAULT_MEMORY_PATH))


def _load_store() -> dict[str, list[str]]:
    """Load the current external store from disk."""
    path = _memory_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for agent_key, memories in payload.items():
        if not isinstance(agent_key, str) or not isinstance(memories, list):
            continue
        normalized[agent_key] = [
            memory.strip()
            for memory in memories
            if isinstance(memory, str) and memory.strip()
        ]
    return normalized


def _load_recent_memories(*, agent_id: int, limit: int = 3) -> list[str]:
    """Return the newest stored memories for one agent."""
    store = _load_store()
    agent_key = f"agent:{agent_id}"
    return store.get(agent_key, [])[-limit:]


def _persist_memory(*, agent_id: int, memory: str) -> int:
    """Persist one new memory string and return the remaining memory count."""
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    store = _load_store()
    agent_key = f"agent:{agent_id}"
    existing = store.get(agent_key, [])
    next_memories = [*existing, memory.strip()][-MAX_MEMORIES_PER_AGENT:]
    store[agent_key] = next_memories
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(next_memories)


def _build_memory_candidate(*, task: dict[str, Any]) -> str | None:
    """Create one minimal memory candidate from the completed task snapshot."""
    user_message = task.get("user_message")
    agent_answer = task.get("agent_answer")
    if not isinstance(user_message, str) or not user_message.strip():
        return None
    if not isinstance(agent_answer, str) or not agent_answer.strip():
        return None

    condensed_answer = " ".join(agent_answer.strip().split())
    if len(condensed_answer) > 160:
        condensed_answer = f"{condensed_answer[:157]}..."
    return f"User asked: {user_message.strip()} | Answered: {condensed_answer}"


def inject_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Recall external memories and prepend them to the task bootstrap prompt."""
    agent_id = context.get("agent_id")
    if not isinstance(agent_id, int):
        return []

    memories = _load_recent_memories(agent_id=agent_id, limit=3)
    if not memories:
        return []

    formatted_lines = "\n".join(f"- {memory}" for memory in memories)
    return [
        {
            "type": "append_prompt_block",
            "payload": {
                "target": "task_bootstrap",
                "position": "head",
                "content": (
                    "## Retrieved External Memory\n"
                    "Use these recalled memories only when they help answer the new task.\n"
                    f"{formatted_lines}"
                ),
            },
        }
    ]


def persist_memory(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Persist one new memory candidate into the external store after success."""
    if context.get("execution_mode") != "live":
        return []

    agent_id = context.get("agent_id")
    task = context.get("task")
    if not isinstance(agent_id, int) or not isinstance(task, dict):
        return []

    candidate = _build_memory_candidate(task=task)
    if candidate is None:
        return []

    memory_count = _persist_memory(agent_id=agent_id, memory=candidate)
    return [
        {
            "type": "emit_event",
            "payload": {
                "type": "memory_persisted",
                "data": {
                    "kind": "external_memory_write",
                    "stored_count": memory_count,
                },
            },
        }
    ]
