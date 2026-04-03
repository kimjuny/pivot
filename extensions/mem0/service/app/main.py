"""FastAPI service backing the Pivot Mem0 extension."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from mem0 import Memory
from pydantic import BaseModel, Field

DEFAULT_COLLECTION_NAME = "pivot_mem0"
DEFAULT_QDRANT_HOST = "qdrant"
DEFAULT_QDRANT_PORT = 6333


class RecallRequest(BaseModel):
    """Recall request payload sent by the Pivot extension hooks."""

    agent_id: int
    session_id: str | None = None
    task_id: str | None = None
    namespace: str = "default"
    limit: int = 5
    task: dict[str, Any] = Field(default_factory=dict)


class PersistRequest(BaseModel):
    """Persist request payload sent by the Pivot extension hooks."""

    agent_id: int
    session_id: str | None = None
    task_id: str | None = None
    namespace: str = "default"
    candidate: str
    task: dict[str, Any] = Field(default_factory=dict)


def _env(name: str, *, default: str | None = None) -> str | None:
    """Return one stripped environment variable value."""
    raw_value = os.environ.get(name, default)
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def _required_json_env(name: str) -> dict[str, Any]:
    """Parse one required JSON environment variable into a dictionary."""
    raw_value = _env(name)
    if raw_value is None:
        raise RuntimeError(f"{name} must be set to a JSON object string.")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must decode to a JSON object.")
    return parsed


def _mem0_config() -> dict[str, Any]:
    """Build the Mem0 configuration from environment variables."""
    llm_config = _required_json_env("MEM0_LLM_CONFIG_JSON")
    embedder_config = _required_json_env("MEM0_EMBEDDER_CONFIG_JSON")

    qdrant_url = _env("MEM0_QDRANT_URL")
    qdrant_api_key = _env("MEM0_QDRANT_API_KEY")
    collection_name = _env("MEM0_COLLECTION_NAME", default=DEFAULT_COLLECTION_NAME)
    qdrant_config: dict[str, Any] = {
        "collection_name": collection_name or DEFAULT_COLLECTION_NAME,
    }
    if qdrant_url is not None:
        qdrant_config["url"] = qdrant_url
    else:
        host = _env("MEM0_QDRANT_HOST", default=DEFAULT_QDRANT_HOST)
        port = _env("MEM0_QDRANT_PORT", default=str(DEFAULT_QDRANT_PORT))
        qdrant_config["host"] = host or DEFAULT_QDRANT_HOST
        qdrant_config["port"] = int(port or DEFAULT_QDRANT_PORT)
    if qdrant_api_key is not None:
        qdrant_config["api_key"] = qdrant_api_key

    return {
        "version": "v1.1",
        "llm": llm_config,
        "embedder": embedder_config,
        "vector_store": {
            "provider": "qdrant",
            "config": qdrant_config,
        },
    }


class Mem0Service:
    """Thin adapter around Mem0's Python SDK."""

    def __init__(self, memory: Memory, *, config: dict[str, Any]) -> None:
        """Store the initialized Memory client and config snapshot."""
        self._memory = memory
        self._config = config

    @classmethod
    def from_env(cls) -> "Mem0Service":
        """Create one Mem0 service from environment configuration."""
        config = _mem0_config()
        return cls(memory=Memory.from_config(config), config=config)

    @property
    def summary(self) -> dict[str, Any]:
        """Return one redacted configuration summary for health responses."""
        vector_store = self._config.get("vector_store")
        vector_store_config = (
            vector_store.get("config")
            if isinstance(vector_store, dict)
            else {}
        )
        return {
            "llm_provider": self._provider_name(self._config.get("llm")),
            "embedder_provider": self._provider_name(self._config.get("embedder")),
            "vector_store_provider": self._provider_name(vector_store),
            "collection_name": (
                vector_store_config.get("collection_name")
                if isinstance(vector_store_config, dict)
                else None
            ),
        }

    def recall(
        self,
        *,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search memories for one logical namespace."""
        raw_results = self._memory.search(query, user_id=namespace, limit=limit)
        if isinstance(raw_results, dict):
            candidates = raw_results.get("results", [])
        else:
            candidates = raw_results
        if not isinstance(candidates, list):
            return []
        return [
            normalized
            for item in candidates
            if (normalized := self._normalize_memory_item(item)) is not None
        ]

    def persist(
        self,
        *,
        namespace: str,
        messages: list[dict[str, str]] | str,
        metadata: dict[str, Any],
    ) -> int:
        """Add one interaction to Mem0 and return an approximate stored count."""
        raw_result = self._memory.add(messages, user_id=namespace, metadata=metadata)
        if isinstance(raw_result, list):
            return len(raw_result)
        if isinstance(raw_result, dict):
            results = raw_result.get("results")
            if isinstance(results, list):
                return len(results)
            if raw_result:
                return 1
            return 0
        return 1 if raw_result is not None else 0

    def _provider_name(self, payload: object) -> str | None:
        """Extract one provider label from one config subsection."""
        if not isinstance(payload, dict):
            return None
        provider = payload.get("provider")
        return provider if isinstance(provider, str) else None

    def _normalize_memory_item(self, item: object) -> dict[str, Any] | None:
        """Normalize one Mem0 search result into the Pivot service response shape."""
        if not isinstance(item, dict):
            return None
        content = item.get("memory")
        if not isinstance(content, str) or not content.strip():
            content = item.get("text")
        if not isinstance(content, str) or not content.strip():
            content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        metadata = item.get("metadata")
        score = item.get("score")
        normalized: dict[str, Any] = {"content": content.strip()}
        if isinstance(metadata, dict):
            normalized["metadata"] = metadata
        if isinstance(score, int | float):
            normalized["score"] = score
        return normalized


def _recall_query(payload: RecallRequest) -> str:
    """Build one semantic search query from the incoming Pivot task context."""
    task = payload.task if isinstance(payload.task, dict) else {}
    user_message = task.get("user_message")
    if isinstance(user_message, str) and user_message.strip():
        return user_message.strip()
    return f"Memories for {payload.namespace}"


def _persist_messages(payload: PersistRequest) -> list[dict[str, str]] | str:
    """Build one Mem0 `add()` payload from the finished Pivot task."""
    task = payload.task if isinstance(payload.task, dict) else {}
    messages: list[dict[str, str]] = []

    user_message = task.get("user_message")
    if isinstance(user_message, str) and user_message.strip():
        messages.append({"role": "user", "content": user_message.strip()})

    agent_answer = task.get("agent_answer")
    if isinstance(agent_answer, str) and agent_answer.strip():
        messages.append({"role": "assistant", "content": agent_answer.strip()})

    return messages if messages else payload.candidate


def _persist_metadata(payload: PersistRequest) -> dict[str, Any]:
    """Attach Pivot runtime metadata to the persisted memory write."""
    return {
        "pivot_agent_id": payload.agent_id,
        "pivot_session_id": payload.session_id,
        "pivot_task_id": payload.task_id,
        "pivot_namespace": payload.namespace,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the Mem0 service once and fail fast on invalid config."""
    app.state.mem0_service = Mem0Service.from_env()
    yield


app = FastAPI(title="Pivot Mem0 Service", version="0.2.0", lifespan=lifespan)


def _mem0_service(request: Request) -> Mem0Service:
    """Return the initialized Mem0 service from application state."""
    service = getattr(request.app.state, "mem0_service", None)
    if not isinstance(service, Mem0Service):
        raise HTTPException(status_code=500, detail="Mem0 service is not initialized.")
    return service


@app.get("/health")
def health(request: Request) -> dict[str, object]:
    """Return a basic health response with the configured backend summary."""
    service = _mem0_service(request)
    return {
        "ok": True,
        "status": "healthy",
        "backend": "mem0_qdrant",
        "config": service.summary,
    }


@app.post("/v1/memories/recall")
def recall_memories(payload: RecallRequest, request: Request) -> dict[str, object]:
    """Recall memories using Mem0's semantic search API."""
    service = _mem0_service(request)
    memories = service.recall(
        namespace=payload.namespace,
        query=_recall_query(payload),
        limit=payload.limit if payload.limit > 0 else 5,
    )
    return {"memories": memories}


@app.post("/v1/memories/persist")
def persist_memory(payload: PersistRequest, request: Request) -> dict[str, object]:
    """Persist one completed interaction into Mem0."""
    service = _mem0_service(request)
    stored_count = service.persist(
        namespace=payload.namespace,
        messages=_persist_messages(payload),
        metadata=_persist_metadata(payload),
    )
    return {"stored_count": stored_count}
