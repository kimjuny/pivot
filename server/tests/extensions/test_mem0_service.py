"""Tests for the standalone Pivot Mem0 service helpers."""

import importlib.util
import sys
import types
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SERVICE_MAIN_PATH = (
    PROJECT_ROOT / "extensions" / "mem0" / "service" / "app" / "main.py"
)


def _load_mem0_service_module():
    """Load the Mem0 service module with one stubbed mem0 dependency."""
    module_name = "test_mem0_service_module"
    fake_mem0_module: Any = types.ModuleType("mem0")
    fake_mem0_module.Memory = type("Memory", (), {})
    fake_fastapi_module: Any = types.ModuleType("fastapi")
    fake_pydantic_module: Any = types.ModuleType("pydantic")
    original_fastapi = sys.modules.get("fastapi")
    original_mem0 = sys.modules.get("mem0")
    original_pydantic = sys.modules.get("pydantic")
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_MAIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Mem0 service module for tests.")

    class _FakeHttpError(Exception):
        """Small stand-in for FastAPI's HTTPException."""

        def __init__(self, status_code: int, detail: str) -> None:
            """Store the failure detail for assertions and compatibility."""
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class _FakeRequest:
        """Stand-in request type used only for importing the module."""

        def __init__(self) -> None:
            """Expose the minimal app.state shape used by helper functions."""
            self.app = types.SimpleNamespace(state=types.SimpleNamespace())

    class _FakeFastAPI:
        """Tiny decorator-compatible replacement for FastAPI."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Store one empty state namespace used in tests."""
            del args, kwargs
            self.state = types.SimpleNamespace()

        def get(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            """Return one no-op route decorator."""
            del args, kwargs
            return lambda func: func

        def post(
            self,
            *args: Any,
            **kwargs: Any,
        ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            """Return one no-op route decorator."""
            del args, kwargs
            return lambda func: func

    class _FakeBaseModel:
        """Minimal subset of pydantic BaseModel used in this test module."""

        def __init__(self, **kwargs: object) -> None:
            """Populate annotated fields from kwargs or class defaults."""
            for field_name in getattr(self.__class__, "__annotations__", {}):
                if field_name in kwargs:
                    value: Any = kwargs[field_name]
                else:
                    value = getattr(self.__class__, field_name)
                setattr(self, field_name, value)

    def _fake_field(
        *,
        default: Any = None,
        default_factory: Callable[[], Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Return one default value during class creation."""
        del kwargs
        if default_factory is not None:
            return default_factory()
        return default

    fake_fastapi_module.FastAPI = _FakeFastAPI
    fake_fastapi_module.HTTPException = _FakeHttpError
    fake_fastapi_module.Request = _FakeRequest
    fake_pydantic_module.BaseModel = _FakeBaseModel
    fake_pydantic_module.Field = _fake_field

    module = importlib.util.module_from_spec(spec)
    sys.modules["mem0"] = fake_mem0_module
    sys.modules["fastapi"] = fake_fastapi_module
    sys.modules[module_name] = module
    sys.modules["pydantic"] = fake_pydantic_module
    try:
        spec.loader.exec_module(module)
    finally:
        if original_fastapi is not None:
            sys.modules["fastapi"] = original_fastapi
        else:
            sys.modules.pop("fastapi", None)
        sys.modules.pop(module_name, None)
        if original_mem0 is not None:
            sys.modules["mem0"] = original_mem0
        else:
            sys.modules.pop("mem0", None)
        if original_pydantic is not None:
            sys.modules["pydantic"] = original_pydantic
        else:
            sys.modules.pop("pydantic", None)
    return module


mem0_service_module = _load_mem0_service_module()


class _FakeMemoryClient:
    """Small fake Mem0 client for persist-path unit tests."""

    def __init__(self, add_results: list[object]) -> None:
        """Store the sequence of add() results returned to the service."""
        self._add_results = list(add_results)
        self.add_calls: list[dict[str, object]] = []

    def add(
        self,
        messages: list[dict[str, str]] | str,
        *,
        user_id: str,
        metadata: dict[str, object],
    ) -> object:
        """Record one add() call and return the next fake result."""
        self.add_calls.append(
            {
                "messages": messages,
                "user_id": user_id,
                "metadata": metadata,
            }
        )
        return self._add_results.pop(0)


class _FakeExecutor:
    """Simple executor double that records submitted jobs without threads."""

    def __init__(self) -> None:
        """Initialize one empty submitted-call log."""
        self.submit_calls: list[dict[str, object]] = []

    def submit(self, fn: Callable[..., object], *args: object) -> None:
        """Record one background submission."""
        self.submit_calls.append(
            {
                "fn": fn,
                "args": args,
            }
        )


class Mem0ServiceTestCase(unittest.TestCase):
    """Validate background submit and fallback helpers for the Mem0 service."""

    def test_fallback_persist_messages_wrap_candidate_as_explicit_memory(self) -> None:
        """Fallback payload should carry the candidate in a compact prompt."""
        payload = mem0_service_module.PersistRequest(
            agent_id=2,
            namespace="user:1:default:agent:2",
            candidate="User wants the assistant to be called Smith Commissioner.",
            task={},
        )

        fallback_messages = mem0_service_module._fallback_persist_messages(payload)

        self.assertIsNotNone(fallback_messages)
        self.assertEqual(len(fallback_messages or []), 2)
        self.assertIn(
            "Smith Commissioner",
            (fallback_messages or [])[0]["content"],
        )

    def test_submit_persist_accepts_job_without_waiting(self) -> None:
        """Submit should return one queued job immediately."""
        fake_memory = _FakeMemoryClient(add_results=[[{"id": "memory-1"}]])
        fake_executor = _FakeExecutor()
        service = mem0_service_module.Mem0Service(
            memory=fake_memory,
            config={},
            executor=fake_executor,
        )

        result = service.submit_persist(
            namespace="user:1:default:agent:2",
            candidate_preview="User wants the assistant to be called Smith Commissioner.",
            messages=[{"role": "user", "content": "Call me Smith Commissioner."}],
            fallback_messages=[
                {"role": "user", "content": "Please remember this memory."}
            ],
            metadata={"pivot_agent_id": 2},
        )

        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "queued")
        self.assertTrue(isinstance(result["job_id"], str))
        self.assertEqual(len(fake_executor.submit_calls), 1)
        job_payload = service.get_persist_job(result["job_id"])
        self.assertIsNotNone(job_payload)
        self.assertEqual(job_payload["status"], "queued")

    def test_persist_now_returns_primary_result_without_fallback(self) -> None:
        """Successful primary writes should stop before any fallback attempt."""
        fake_memory = _FakeMemoryClient(add_results=[[{"id": "memory-1"}]])
        service = mem0_service_module.Mem0Service(memory=fake_memory, config={})

        result = service._persist_now(
            namespace="user:1:default:agent:2",
            messages=[{"role": "user", "content": "Call me Smith Commissioner."}],
            fallback_messages=[
                {"role": "user", "content": "Please remember this memory."}
            ],
            metadata={"pivot_agent_id": 2},
        )

        self.assertEqual(result["stored_count"], 1)
        self.assertFalse(result["used_fallback"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(len(fake_memory.add_calls), 1)

    def test_persist_now_retries_with_fallback_after_empty_primary_result(
        self,
    ) -> None:
        """Zero-result primary writes should trigger one fallback attempt."""
        fake_memory = _FakeMemoryClient(
            add_results=[[], [{"id": "memory-2"}]],
        )
        service = mem0_service_module.Mem0Service(memory=fake_memory, config={})

        result = service._persist_now(
            namespace="user:1:default:agent:2",
            messages=[{"role": "user", "content": "You are Smith Commissioner."}],
            fallback_messages=[
                {
                    "role": "user",
                    "content": (
                        "Please remember this user-specific memory for future "
                        "tasks: User wants the assistant to be called "
                        "Smith Commissioner."
                    ),
                },
                {
                    "role": "assistant",
                    "content": "Understood. I will retain that memory.",
                },
            ],
            metadata={"pivot_agent_id": 2},
        )

        self.assertEqual(result["stored_count"], 1)
        self.assertTrue(result["used_fallback"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["status"], "empty")
        self.assertEqual(result["attempts"][1]["status"], "stored")
        self.assertEqual(len(fake_memory.add_calls), 2)


if __name__ == "__main__":
    unittest.main()
