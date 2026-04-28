"""Tests for ReAct tool-call batch execution."""

import asyncio
import sys
import threading
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
ChatMessage = import_module("app.llm.abstract_llm").ChatMessage
Choice = import_module("app.llm.abstract_llm").Choice
Response = import_module("app.llm.abstract_llm").Response
ReactContext = import_module("app.orchestration.react.context").ReactContext
ReactEngine = import_module("app.orchestration.react.engine").ReactEngine
ReactTask = import_module("app.models.react").ReactTask


class _LlmStub:
    """Minimal LLM stub that returns one prebuilt assistant response."""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        del messages, kwargs
        return Response(
            id="resp-batch",
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(role="assistant", content=self._content),
                )
            ],
            created=0,
            model="batch-model",
        )


class _BatchToolManager:
    """Tool manager stub that records execution order and proves concurrency."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batch_one_barrier = threading.Barrier(2)
        self.started: list[str] = []
        self.finished: list[str] = []
        self.batch_one_ran_concurrently = False

    def execute(self, name: str, *, context: object | None = None, label: str) -> str:
        del name, context
        with self._lock:
            self.started.append(label)

        if label in {"a", "b"}:
            self._batch_one_barrier.wait(timeout=1)
            with self._lock:
                self.batch_one_ran_concurrently = True

        with self._lock:
            self.finished.append(label)
        return f"done-{label}"

    def list_tools(self) -> list[object]:
        return [SimpleNamespace(name="record_tool")]

    def get_tool(self, name: str) -> object | None:
        del name
        return None


def _build_batch_response_content() -> str:
    return """
{
  "observe": "Need parallel reads before verification.",
  "reason": "The first two calls are independent; the third should wait.",
  "summary": "Running batched tools.",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-a",
          "name": "record_tool",
          "batch": 1,
          "arguments": {
            "label": {"$payload_ref": "payload_a"}
          }
        },
        {
          "id": "call-b",
          "name": "record_tool",
          "batch": 1,
          "arguments": {
            "label": {"$payload_ref": "payload_b"}
          }
        },
        {
          "id": "call-c",
          "name": "record_tool",
          "batch": 2,
          "arguments": {
            "label": {"$payload_ref": "payload_c"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:payload_a:BEGIN_6F2D9C1A>>>
"a"
<<<PIVOT_PAYLOAD:payload_a:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:payload_b:BEGIN_6F2D9C1A>>>
"b"
<<<PIVOT_PAYLOAD:payload_b:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:payload_c:BEGIN_6F2D9C1A>>>
"c"
<<<PIVOT_PAYLOAD:payload_c:END_6F2D9C1A>>>
""".strip()


class ReactEngineToolBatchTestCase(unittest.TestCase):
    """Verify tool-call batch execution semantics."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()

    def _create_task(self) -> Any:
        task = ReactTask(
            task_id="task-batch",
            session_id="session-batch",
            agent_id=1,
            user="alice",
            user_message="Run batched tools",
            user_intent="Run batched tools",
            status="running",
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def test_tool_calls_execute_parallel_within_batch_and_serial_between_batches(
        self,
    ) -> None:
        """Batch 1 runs concurrently while batch 2 waits for batch 1 completion."""
        tool_manager = _BatchToolManager()
        task = self._create_task()
        context = ReactContext.from_task(task, self.session)
        engine = ReactEngine(
            llm=_LlmStub(_build_batch_response_content()),
            tool_manager=tool_manager,
            db=self.session,
            stream_llm_responses=False,
        )
        token_meter_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        _recursion, event_data = asyncio.run(
            engine.execute_recursion(
                task=task,
                context=context,
                trace_id="trace-batch",
                input_message={"role": "user", "content": "Run batched tools"},
                messages=[{"role": "user", "content": "Run batched tools"}],
                token_meter_queue=token_meter_queue,
            )
        )

        self.assertTrue(tool_manager.batch_one_ran_concurrently)
        self.assertLess(
            tool_manager.started.index("a"), tool_manager.started.index("c")
        )
        self.assertLess(
            tool_manager.started.index("b"), tool_manager.started.index("c")
        )
        self.assertEqual(
            [item["tool_call_id"] for item in event_data["tool_results"]],
            [
                "call-a",
                "call-b",
                "call-c",
            ],
        )
        self.assertEqual(
            [item["result"] for item in event_data["tool_results"]],
            ["done-a", "done-b", "done-c"],
        )

        queued_items: list[dict[str, Any]] = []
        while not token_meter_queue.empty():
            queued_items.append(token_meter_queue.get_nowait())
        tool_call_events = [
            item for item in queued_items if item.get("type") == "tool_call"
        ]

        self.assertEqual(len(tool_call_events), 2)
        self.assertEqual(
            [item["id"] for item in tool_call_events[0]["tool_calls"]],
            ["call-a", "call-b"],
        )
        self.assertEqual(
            [item["id"] for item in tool_call_events[1]["tool_calls"]],
            ["call-c"],
        )


if __name__ == "__main__":
    unittest.main()
