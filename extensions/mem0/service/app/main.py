"""FastAPI service backing the Pivot Mem0 extension."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from mem0 import Memory
from pydantic import BaseModel, Field

DEFAULT_COLLECTION_NAME = "pivot_mem0"
DEFAULT_QDRANT_HOST = "qdrant"
DEFAULT_QDRANT_PORT = 6333
DEFAULT_PERSIST_WORKER_COUNT = 4
DEFAULT_JOB_HISTORY_LIMIT = 200
_PREVIEW_TEXT_LIMIT = 160

# Why: Uvicorn's default logging config already exposes this logger at INFO.
# Reusing it makes our service-level diagnostics visible without requiring
# operators to ship a custom logging config just to debug memory behavior.
logger = logging.getLogger("uvicorn.error")


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


@dataclass(slots=True)
class PersistJobRecord:
    """In-memory debug record for one background persist job."""

    job_id: str
    namespace: str
    status: str
    submitted_at: datetime
    candidate_preview: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    stored_count: int | None = None
    used_fallback: bool | None = None
    attempts: list[dict[str, Any]] | None = None
    error_type: str | None = None
    error_message: str | None = None


def _normalize_whitespace(value: str) -> str:
    """Collapse repeated whitespace so logs stay compact and readable."""
    return " ".join(value.split())


def _preview_text(value: str | None, *, limit: int = _PREVIEW_TEXT_LIMIT) -> str:
    """Return one short preview of a potentially long user-controlled string."""
    if not isinstance(value, str):
        return ""
    normalized = _normalize_whitespace(value).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


def _payload_kind(payload: list[dict[str, str]] | str | None) -> str:
    """Return one stable label describing the outgoing Mem0 add() payload."""
    if isinstance(payload, list):
        return "messages"
    if isinstance(payload, str):
        return "text"
    return "none"


def _payload_preview(payload: list[dict[str, str]] | str | None) -> str:
    """Return one short preview of the payload passed into Mem0 add()."""
    if isinstance(payload, str):
        return _preview_text(payload)
    if not isinstance(payload, list):
        return ""

    previews: list[str] = []
    for message in payload:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if isinstance(role, str) and isinstance(content, str):
            previews.append(f"{role}: {_preview_text(content, limit=80)}")
    return " | ".join(previews)


def _env(name: str, *, default: str | None = None) -> str | None:
    """Return one stripped environment variable value."""
    raw_value = os.environ.get(name, default)
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def _as_positive_int(value: str | None, *, fallback: int) -> int:
    """Return one positive integer parsed from environment configuration."""
    if value is None:
        return fallback
    try:
        normalized = int(value)
    except ValueError:
        return fallback
    return normalized if normalized > 0 else fallback


def _persist_worker_count() -> int:
    """Return the configured number of background persist workers."""
    return _as_positive_int(
        _env("MEM0_PERSIST_WORKER_COUNT"),
        fallback=DEFAULT_PERSIST_WORKER_COUNT,
    )


def _job_history_limit() -> int:
    """Return the configured max number of in-memory persist job records."""
    return _as_positive_int(
        _env("MEM0_JOB_HISTORY_LIMIT"),
        fallback=DEFAULT_JOB_HISTORY_LIMIT,
    )


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

    def __init__(
        self,
        memory: Memory,
        *,
        config: dict[str, Any],
        executor: ThreadPoolExecutor | None = None,
        job_history_limit: int = DEFAULT_JOB_HISTORY_LIMIT,
    ) -> None:
        """Store the initialized Memory client and async persist infrastructure."""
        self._memory = memory
        self._config = config
        configured_worker_count = _persist_worker_count()
        executor_worker_count = getattr(executor, "_max_workers", None)
        self._persist_worker_count = (
            executor_worker_count
            if isinstance(executor_worker_count, int) and executor_worker_count > 0
            else configured_worker_count
        )
        self._executor = executor or ThreadPoolExecutor(
            max_workers=self._persist_worker_count,
            thread_name_prefix="pivot-mem0-persist",
        )
        self._owns_executor = executor is None
        self._job_history_limit = max(1, job_history_limit)
        self._jobs: dict[str, PersistJobRecord] = {}
        self._jobs_lock = Lock()

    @classmethod
    def from_env(cls) -> "Mem0Service":
        """Create one Mem0 service from environment configuration."""
        config = _mem0_config()
        return cls(
            memory=Memory.from_config(config),
            config=config,
            job_history_limit=_job_history_limit(),
        )

    @property
    def summary(self) -> dict[str, Any]:
        """Return one redacted configuration summary for health responses."""
        vector_store = self._config.get("vector_store")
        vector_store_config = (
            vector_store.get("config")
            if isinstance(vector_store, dict)
            else {}
        )
        queued, running = self._job_counts()
        return {
            "llm_provider": self._provider_name(self._config.get("llm")),
            "embedder_provider": self._provider_name(self._config.get("embedder")),
            "vector_store_provider": self._provider_name(vector_store),
            "collection_name": (
                vector_store_config.get("collection_name")
                if isinstance(vector_store_config, dict)
                else None
            ),
            "persist_worker_count": self._persist_worker_count,
            "queued_jobs": queued,
            "running_jobs": running,
        }

    def shutdown(self) -> None:
        """Release background worker resources owned by the service."""
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=False)

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

    def submit_persist(
        self,
        *,
        namespace: str,
        candidate_preview: str,
        messages: list[dict[str, str]] | str,
        fallback_messages: list[dict[str, str]] | str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Queue one background persist job and return immediately."""
        job_id = str(uuid4())
        job_record = PersistJobRecord(
            job_id=job_id,
            namespace=namespace,
            status="queued",
            submitted_at=datetime.now(UTC),
            candidate_preview=_preview_text(candidate_preview),
        )
        with self._jobs_lock:
            self._jobs[job_id] = job_record
            self._trim_jobs_locked()

        logger.info(
            "Mem0 persist job queued. namespace=%s job_id=%s candidate_preview=%r",
            namespace,
            job_id,
            job_record.candidate_preview,
        )
        try:
            self._executor.submit(
                self._run_persist_job,
                job_id,
                namespace,
                messages,
                fallback_messages,
                metadata,
            )
        except RuntimeError as exc:
            self._mark_job_failed(job_id=job_id, error=exc, duration_ms=0)
            raise RuntimeError("Mem0 persist workers are unavailable.") from exc

        return {
            "accepted": True,
            "job_id": job_id,
            "status": "queued",
            "submitted_at": job_record.submitted_at.isoformat(),
        }

    def get_persist_job(self, job_id: str) -> dict[str, Any] | None:
        """Return one serialized background persist job when available."""
        with self._jobs_lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            return self._serialize_job(record)

    def _run_persist_job(
        self,
        job_id: str,
        namespace: str,
        messages: list[dict[str, str]] | str,
        fallback_messages: list[dict[str, str]] | str | None,
        metadata: dict[str, Any],
    ) -> None:
        """Execute one queued persist job inside the worker pool."""
        started_at = datetime.now(UTC)
        self._update_job(
            job_id=job_id,
            status="running",
            started_at=started_at,
        )
        logger.info("Mem0 persist job started. namespace=%s job_id=%s", namespace, job_id)

        started_perf = perf_counter()
        try:
            persist_result = self._persist_now(
                namespace=namespace,
                messages=messages,
                fallback_messages=fallback_messages,
                metadata=metadata,
            )
        except Exception as exc:
            duration_ms = int((perf_counter() - started_perf) * 1000)
            self._mark_job_failed(job_id=job_id, error=exc, duration_ms=duration_ms)
            logger.exception(
                "Mem0 persist job failed. namespace=%s job_id=%s duration_ms=%s",
                namespace,
                job_id,
                duration_ms,
            )
            return

        duration_ms = int((perf_counter() - started_perf) * 1000)
        self._update_job(
            job_id=job_id,
            status="completed",
            finished_at=datetime.now(UTC),
            duration_ms=duration_ms,
            stored_count=persist_result["stored_count"],
            used_fallback=persist_result["used_fallback"],
            attempts=persist_result["attempts"],
        )
        logger.info(
            "Mem0 persist job finished. namespace=%s job_id=%s stored_count=%s "
            "used_fallback=%s duration_ms=%s",
            namespace,
            job_id,
            persist_result["stored_count"],
            persist_result["used_fallback"],
            duration_ms,
        )

    def _persist_now(
        self,
        *,
        namespace: str,
        messages: list[dict[str, str]] | str,
        fallback_messages: list[dict[str, str]] | str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one immediate persist attempt sequence against Mem0."""
        attempts: list[dict[str, Any]] = []
        attempt_payloads = [
            ("primary", messages),
            ("fallback_candidate", fallback_messages),
        ]
        for attempt_name, attempt_payload in attempt_payloads:
            if attempt_payload is None:
                continue

            started = perf_counter()
            try:
                raw_result = self._memory.add(
                    attempt_payload,
                    user_id=namespace,
                    metadata=metadata,
                )
            except Exception as exc:
                duration_ms = int((perf_counter() - started) * 1000)
                attempt_record = {
                    "name": attempt_name,
                    "payload_kind": _payload_kind(attempt_payload),
                    "payload_preview": _payload_preview(attempt_payload),
                    "duration_ms": duration_ms,
                    "stored_count": 0,
                    "status": "failed",
                    "error_type": exc.__class__.__name__,
                    "error_message": str(exc),
                }
                attempts.append(attempt_record)
                logger.exception(
                    "Mem0 persist attempt failed. namespace=%s attempt=%s "
                    "payload_kind=%s duration_ms=%s payload_preview=%r",
                    namespace,
                    attempt_name,
                    attempt_record["payload_kind"],
                    duration_ms,
                    attempt_record["payload_preview"],
                )
                continue

            stored_count = self._normalize_add_result(raw_result)
            duration_ms = int((perf_counter() - started) * 1000)
            attempt_record = {
                "name": attempt_name,
                "payload_kind": _payload_kind(attempt_payload),
                "payload_preview": _payload_preview(attempt_payload),
                "duration_ms": duration_ms,
                "stored_count": stored_count,
                "status": "stored" if stored_count > 0 else "empty",
                "raw_result_kind": type(raw_result).__name__,
            }
            attempts.append(attempt_record)
            logger.info(
                "Mem0 persist attempt finished. namespace=%s attempt=%s "
                "payload_kind=%s stored_count=%s duration_ms=%s "
                "raw_result_kind=%s payload_preview=%r",
                namespace,
                attempt_name,
                attempt_record["payload_kind"],
                stored_count,
                duration_ms,
                attempt_record["raw_result_kind"],
                attempt_record["payload_preview"],
            )
            if stored_count > 0:
                return {
                    "stored_count": stored_count,
                    "used_fallback": attempt_name != "primary",
                    "attempts": attempts,
                }

        return {
            "stored_count": 0,
            "used_fallback": any(
                attempt.get("name") != "primary" for attempt in attempts
            ),
            "attempts": attempts,
        }

    def _provider_name(self, payload: object) -> str | None:
        """Extract one provider label from one config subsection."""
        if not isinstance(payload, dict):
            return None
        provider = payload.get("provider")
        return provider if isinstance(provider, str) else None

    def _normalize_add_result(self, raw_result: object) -> int:
        """Normalize Mem0 add() return values into one stored-count integer."""
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

    def _job_counts(self) -> tuple[int, int]:
        """Return the current number of queued and running persist jobs."""
        with self._jobs_lock:
            queued = sum(1 for record in self._jobs.values() if record.status == "queued")
            running = sum(
                1 for record in self._jobs.values() if record.status == "running"
            )
        return queued, running

    def _update_job(
        self,
        *,
        job_id: str,
        status: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        stored_count: int | None = None,
        used_fallback: bool | None = None,
        attempts: list[dict[str, Any]] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update one tracked persist job record in place."""
        with self._jobs_lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            if status is not None:
                record.status = status
            if started_at is not None:
                record.started_at = started_at
            if finished_at is not None:
                record.finished_at = finished_at
            if duration_ms is not None:
                record.duration_ms = duration_ms
            if stored_count is not None:
                record.stored_count = stored_count
            if used_fallback is not None:
                record.used_fallback = used_fallback
            if attempts is not None:
                record.attempts = attempts
            if error_type is not None:
                record.error_type = error_type
            if error_message is not None:
                record.error_message = error_message

    def _mark_job_failed(
        self,
        *,
        job_id: str,
        error: Exception,
        duration_ms: int,
    ) -> None:
        """Mark one job as failed with the provided exception details."""
        self._update_job(
            job_id=job_id,
            status="failed",
            finished_at=datetime.now(UTC),
            duration_ms=duration_ms,
            error_type=error.__class__.__name__,
            error_message=str(error),
        )

    def _serialize_job(self, record: PersistJobRecord) -> dict[str, Any]:
        """Convert one in-memory job record into an API payload."""
        return {
            "job_id": record.job_id,
            "namespace": record.namespace,
            "status": record.status,
            "submitted_at": record.submitted_at.isoformat(),
            "started_at": (
                record.started_at.isoformat() if record.started_at is not None else None
            ),
            "finished_at": (
                record.finished_at.isoformat()
                if record.finished_at is not None
                else None
            ),
            "duration_ms": record.duration_ms,
            "stored_count": record.stored_count,
            "used_fallback": record.used_fallback,
            "attempts": record.attempts,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "candidate_preview": record.candidate_preview,
        }

    def _trim_jobs_locked(self) -> None:
        """Drop the oldest in-memory debug records past the configured limit."""
        while len(self._jobs) > self._job_history_limit:
            oldest_job_id = next(iter(self._jobs))
            self._jobs.pop(oldest_job_id, None)


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


def _fallback_persist_messages(
    payload: PersistRequest,
) -> list[dict[str, str]] | None:
    """Build one explicit fallback prompt when Mem0 stores nothing initially."""
    candidate = payload.candidate.strip()
    if candidate == "":
        return None
    return [
        {
            "role": "user",
            "content": (
                "Please remember this user-specific memory for future tasks: "
                f"{candidate}"
            ),
        },
        {
            "role": "assistant",
            "content": "Understood. I will retain that memory for future recall.",
        },
    ]


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
    service = Mem0Service.from_env()
    app.state.mem0_service = service
    try:
        yield
    finally:
        service.shutdown()


app = FastAPI(title="Pivot Mem0 Service", version="0.3.0", lifespan=lifespan)


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


@app.get("/v1/memories/persist/jobs/{job_id}")
def get_persist_job(job_id: str, request: Request) -> dict[str, object]:
    """Return the current status of one background persist job."""
    service = _mem0_service(request)
    payload = service.get_persist_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Persist job not found.")
    return payload


@app.post("/v1/memories/recall")
def recall_memories(payload: RecallRequest, request: Request) -> dict[str, object]:
    """Recall memories using Mem0's semantic search API."""
    service = _mem0_service(request)
    query = _recall_query(payload)
    normalized_limit = payload.limit if payload.limit > 0 else 5
    started = perf_counter()
    logger.info(
        "Mem0 recall started. namespace=%s limit=%s query_preview=%r",
        payload.namespace,
        normalized_limit,
        _preview_text(query),
    )
    try:
        memories = service.recall(
            namespace=payload.namespace,
            query=query,
            limit=normalized_limit,
        )
    except Exception as exc:
        duration_ms = int((perf_counter() - started) * 1000)
        logger.exception(
            "Mem0 recall failed. namespace=%s limit=%s duration_ms=%s "
            "query_preview=%r",
            payload.namespace,
            normalized_limit,
            duration_ms,
            _preview_text(query),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Mem0 recall failed: {exc.__class__.__name__}: {exc}",
        ) from exc

    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "Mem0 recall finished. namespace=%s count=%s duration_ms=%s "
        "query_preview=%r",
        payload.namespace,
        len(memories),
        duration_ms,
        _preview_text(query),
    )
    return {
        "memories": memories,
        "count": len(memories),
        "duration_ms": duration_ms,
    }


@app.post("/v1/memories/persist", status_code=202)
def persist_memory(payload: PersistRequest, request: Request) -> dict[str, object]:
    """Accept one persist request and process it in the background."""
    service = _mem0_service(request)
    primary_messages = _persist_messages(payload)
    fallback_messages = _fallback_persist_messages(payload)
    started = perf_counter()
    logger.info(
        "Mem0 persist submit started. namespace=%s candidate_preview=%r "
        "primary_payload_kind=%s fallback_payload_kind=%s",
        payload.namespace,
        _preview_text(payload.candidate),
        _payload_kind(primary_messages),
        _payload_kind(fallback_messages),
    )
    try:
        submit_result = service.submit_persist(
            namespace=payload.namespace,
            candidate_preview=payload.candidate,
            messages=primary_messages,
            fallback_messages=fallback_messages,
            metadata=_persist_metadata(payload),
        )
    except Exception as exc:
        duration_ms = int((perf_counter() - started) * 1000)
        logger.exception(
            "Mem0 persist submit failed. namespace=%s duration_ms=%s "
            "candidate_preview=%r",
            payload.namespace,
            duration_ms,
            _preview_text(payload.candidate),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Mem0 persist submit failed: {exc.__class__.__name__}: {exc}",
        ) from exc

    duration_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "Mem0 persist submit accepted. namespace=%s job_id=%s duration_ms=%s "
        "candidate_preview=%r",
        payload.namespace,
        submit_result["job_id"],
        duration_ms,
        _preview_text(payload.candidate),
    )
    return {
        **submit_result,
        "duration_ms": duration_ms,
    }
