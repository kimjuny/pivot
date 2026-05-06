"""Unit tests for streaming token-usage normalization in the ReAct engine."""

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
UsageInfo = import_module("app.llm.abstract_llm").UsageInfo
ReactEngine = import_module("app.orchestration.react.engine").ReactEngine
EagerToolExecutionState = import_module(
    "app.orchestration.react.engine"
)._EagerToolExecutionState
ReactContext = import_module("app.orchestration.react.context").ReactContext
ReactTask = import_module("app.models.react").ReactTask


class _StreamingLlmStub:
    """Minimal LLM stub that returns predefined streaming chunks."""

    def __init__(self, chunks: list[object]) -> None:
        """Store chunks for later iteration.

        Args:
            chunks: Streaming response chunks to yield in order.
        """
        self._chunks = chunks

    def chat_stream(self, messages: list[dict[str, object]], **kwargs: object):
        """Yield the predefined chunks.

        Args:
            messages: Unused request messages.
            **kwargs: Unused stream kwargs.

        Returns:
            An iterator over prebuilt response chunks.
        """
        del messages, kwargs
        return iter(self._chunks)


class _BlockingStreamingLlmStub:
    """Streaming stub that waits for eager tool start before yielding chunk 2."""

    def __init__(self, chunks: list[object], tool_started: threading.Event) -> None:
        self._chunks = chunks
        self._tool_started = tool_started

    def chat_stream(self, messages: list[dict[str, object]], **kwargs: object):
        del messages, kwargs
        return _BlockingIterator(self._chunks, self._tool_started)


class _BlockingIterator:
    """Iterator proving eager tool execution starts before the stream ends."""

    def __init__(self, chunks: list[object], tool_started: threading.Event) -> None:
        self._chunks = chunks
        self._tool_started = tool_started
        self._index = 0

    def __iter__(self) -> "_BlockingIterator":
        return self

    def __next__(self) -> object:
        if self._index >= len(self._chunks):
            raise StopIteration
        if self._index == 1 and not self._tool_started.wait(timeout=1):
            raise AssertionError("Tool did not start before the next stream chunk.")
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class _EagerToolManagerStub:
    """Tool manager stub that records eager execution."""

    def __init__(self, tool_started: threading.Event) -> None:
        self._tool_started = tool_started
        self.calls: list[dict[str, object]] = []

    def execute(
        self,
        name: str,
        *,
        context: object | None = None,
        path: str,
    ) -> dict[str, object]:
        del context
        self.calls.append({"name": name, "path": path})
        self._tool_started.set()
        return {"ok": True, "path": path}

    def get_tool(self, name: str) -> object | None:
        del name
        return SimpleNamespace(parameters={"properties": {"path": {"type": "string"}}})

    def list_tools(self) -> list[object]:
        return [SimpleNamespace(name="read_file")]


class _ToolResultNotifyingQueue(asyncio.Queue[dict[str, Any]]):
    """Queue that signals when a live tool result is emitted."""

    def __init__(self, tool_result_emitted: threading.Event) -> None:
        super().__init__()
        self._tool_result_emitted = tool_result_emitted

    async def put(self, item: dict[str, Any]) -> None:
        if item.get("type") == "tool_result":
            self._tool_result_emitted.set()
        await super().put(item)


class ReactEngineStreamUsageTestCase(unittest.TestCase):
    """Verify streaming usage is normalized before persistence."""

    def setUp(self) -> None:
        """Create an isolated database session per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        """Close the test database session."""
        self.session.close()

    def _create_task(self) -> Any:
        """Create a persisted task for full recursion tests."""
        task = ReactTask(
            task_id="task-stream-usage",
            session_id="session-stream-usage",
            agent_id=1,
            user="alice",
            user_message="Run streaming test",
            user_intent="Run streaming test",
            status="running",
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def test_stream_uses_latest_cumulative_usage_snapshot_once(self) -> None:
        """Monotonic snapshot chunks should resolve to one final usage record."""
        llm = _StreamingLlmStub(
            [
                Response(
                    id="resp-1",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content="hel"),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-1",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content="lo"),
                        )
                    ],
                    created=0,
                    model="stream-model",
                    usage=UsageInfo(
                        prompt_tokens=1200,
                        completion_tokens=1,
                        total_tokens=1201,
                        cached_input_tokens=900,
                    ),
                ),
                Response(
                    id="resp-1",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content=""),
                        )
                    ],
                    created=0,
                    model="stream-model",
                    usage=UsageInfo(
                        prompt_tokens=1200,
                        completion_tokens=2,
                        total_tokens=1202,
                        cached_input_tokens=900,
                    ),
                ),
                Response(
                    id="resp-1",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content=""),
                        )
                    ],
                    created=0,
                    model="stream-model",
                    usage=UsageInfo(
                        prompt_tokens=1200,
                        completion_tokens=3,
                        total_tokens=1203,
                        cached_input_tokens=900,
                    ),
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()

        response = asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
            )
        )

        self.assertEqual(response.first().message.content, "hello")
        self.assertIsNotNone(response.usage)
        self.assertEqual(response.usage.prompt_tokens, 1200)  # type: ignore[union-attr]
        self.assertEqual(response.usage.completion_tokens, 3)  # type: ignore[union-attr]
        self.assertEqual(response.usage.total_tokens, 1203)  # type: ignore[union-attr]
        self.assertEqual(
            response.usage.cached_input_tokens,  # type: ignore[union-attr]
            900,
        )
        self.assertEqual(
            token_counter,
            {
                "prompt_tokens": 1200,
                "completion_tokens": 3,
                "total_tokens": 1203,
                "cached_input_tokens": 900,
            },
        )

    def test_stream_falls_back_to_additive_mode_for_non_monotonic_usage(self) -> None:
        """Non-monotonic chunks should be treated as deltas instead of snapshots."""
        llm = _StreamingLlmStub(
            [
                Response(
                    id="resp-2",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content="ok"),
                        )
                    ],
                    created=0,
                    model="stream-model",
                    usage=UsageInfo(
                        prompt_tokens=5,
                        completion_tokens=1,
                        total_tokens=6,
                        cached_input_tokens=0,
                    ),
                ),
                Response(
                    id="resp-2",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content=""),
                        )
                    ],
                    created=0,
                    model="stream-model",
                    usage=UsageInfo(
                        prompt_tokens=0,
                        completion_tokens=2,
                        total_tokens=2,
                        cached_input_tokens=0,
                    ),
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()

        response = asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
            )
        )

        self.assertIsNotNone(response.usage)
        self.assertEqual(response.usage.prompt_tokens, 5)  # type: ignore[union-attr]
        self.assertEqual(response.usage.completion_tokens, 3)  # type: ignore[union-attr]
        self.assertEqual(response.usage.total_tokens, 8)  # type: ignore[union-attr]
        self.assertEqual(
            token_counter,
            {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
                "cached_input_tokens": 0,
            },
        )

    def test_stream_emits_react_control_preview_at_payload_boundary(self) -> None:
        """The first payload marker should unlock early summary/tool UI events."""
        control_json = """
{
  "observe": "Need file content",
  "reason": "Call the file tool",
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
""".strip()
        llm = _StreamingLlmStub(
            [
                Response(
                    id="resp-3",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=control_json[:120],
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-3",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=(
                                    control_json[120:]
                                    + "\n<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>\n"
                                ),
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        token_meter_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        response = asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=token_meter_queue,
            )
        )

        queued_items: list[dict[str, object]] = []
        while not token_meter_queue.empty():
            queued_items.append(token_meter_queue.get_nowait())
        control_items = [
            item for item in queued_items if item.get("type") == "react_control"
        ]

        expected_content = (
            control_json + "\n<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>\n"
        )

        self.assertEqual(response.first().message.content, expected_content)
        self.assertEqual(len(control_items), 1)
        self.assertEqual(control_items[0]["summary"], "Reading the requested file")
        self.assertEqual(control_items[0]["action_type"], "CALL_TOOL")
        self.assertEqual(
            control_items[0]["tool_calls"],
            [
                {
                    "id": "call-1",
                    "name": "read_file",
                    "batch": 1,
                    "arguments": {"path": {"$payload_ref": "path_payload"}},
                }
            ],
        )

    def test_stream_emits_live_answer_payload_deltas(self) -> None:
        """ANSWER payload bodies should stream as answer_delta events."""
        control_json = """
{
  "summary": "Task complete",
  "action": {
    "action_type": "ANSWER",
    "output": {
      "answer": {"$payload_ref": "answer_payload"},
      "attachments": []
    }
  },
  "task_summary": {
    "narrative": "Completed.",
    "key_findings": [],
    "final_decisions": []
  }
}
""".strip()
        llm = _StreamingLlmStub(
            [
                Response(
                    id="resp-answer-stream",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=(
                                    control_json
                                    + "\n<<<PIVOT_PAYLOAD:answer_payload:BEGIN_6F2D9C1A>>>\n"
                                    "Hello"
                                ),
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-answer-stream",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=(
                                    " world\n<<<PIVOT_PAYLOAD:answer_payload:END_6F2D9C1A>>>"
                                ),
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        token_meter_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=token_meter_queue,
            )
        )

        queued_items: list[dict[str, object]] = []
        while not token_meter_queue.empty():
            queued_items.append(token_meter_queue.get_nowait())

        control_items = [
            item for item in queued_items if item.get("type") == "react_control"
        ]
        answer_delta_items = [
            item for item in queued_items if item.get("type") == "answer_delta"
        ]

        self.assertEqual(len(control_items), 1)
        self.assertEqual(control_items[0]["action_type"], "ANSWER")
        self.assertEqual(len(answer_delta_items), 2)
        self.assertEqual(answer_delta_items[0]["delta"], "Hello")
        self.assertEqual(answer_delta_items[1]["delta"], " world")
        self.assertIs(answer_delta_items[1]["is_final"], True)

    def test_stream_starts_tool_when_payload_is_complete_before_stream_end(
        self,
    ) -> None:
        """A closed payload block should start its tool before later chunks arrive."""
        content = """
{
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
""".strip()
        tool_started = threading.Event()
        tool_manager = _EagerToolManagerStub(tool_started)
        llm = _BlockingStreamingLlmStub(
            [
                Response(
                    id="resp-eager",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content=content),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-eager",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content="\n"),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
            ],
            tool_started,
        )
        engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=self.session)
        token_counter = engine._new_token_counter()
        token_meter_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        eager_state = EagerToolExecutionState()

        response = asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=token_meter_queue,
                eager_tool_state=eager_state,
            )
        )

        queued_items: list[dict[str, object]] = []
        while not token_meter_queue.empty():
            queued_items.append(token_meter_queue.get_nowait())
        resolved_tool_calls = [
            item for item in queued_items if item.get("type") == "tool_call"
        ]
        tool_results = [
            item for item in queued_items if item.get("type") == "tool_result"
        ]

        self.assertEqual(response.first().message.content, content + "\n")
        self.assertEqual(
            tool_manager.calls,
            [{"name": "read_file", "path": "README.md"}],
        )
        self.assertEqual(eager_state.started_call_ids, {"call-1"})
        self.assertEqual(
            resolved_tool_calls[-1]["tool_calls"],
            [
                {
                    "id": "call-1",
                    "name": "read_file",
                    "batch": 1,
                    "arguments": {"path": "README.md"},
                }
            ],
        )
        self.assertEqual(
            tool_results[-1]["tool_results"],
            [
                {
                    "tool_call_id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                    "result": {"ok": True, "path": "README.md"},
                    "success": True,
                }
            ],
        )

    def test_stream_emits_eager_tool_result_while_provider_stream_is_blocked(
        self,
    ) -> None:
        """Eager results should not wait for the next provider chunk."""
        content = """
{
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
""".strip()
        tool_result_emitted = threading.Event()
        tool_manager = _EagerToolManagerStub(threading.Event())
        llm = _BlockingStreamingLlmStub(
            [
                Response(
                    id="resp-eager-pump",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content=content),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-eager-pump",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(role="assistant", content="\n"),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
            ],
            tool_result_emitted,
        )
        engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=self.session)
        token_counter = engine._new_token_counter()
        token_meter_queue = _ToolResultNotifyingQueue(tool_result_emitted)
        eager_state = EagerToolExecutionState()

        response = asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=token_meter_queue,
                eager_tool_state=eager_state,
            )
        )

        self.assertEqual(response.first().message.content, content + "\n")
        self.assertEqual(
            tool_manager.calls,
            [{"name": "read_file", "path": "README.md"}],
        )
        self.assertIn("call-1", eager_state.result_by_call_id)

    def test_execute_recursion_preserves_eager_tool_results_after_parse_failure(
        self,
    ) -> None:
        """After a tool starts, parse failure becomes next-turn recovery context."""
        content = """
{
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:unused_payload:BEGIN_6F2D9C1A>>>
"unused"
<<<PIVOT_PAYLOAD:unused_payload:END_6F2D9C1A>>>
""".strip()
        tool_started = threading.Event()
        tool_manager = _EagerToolManagerStub(tool_started)
        split_at = content.index("<<<PIVOT_PAYLOAD:unused_payload:BEGIN_6F2D9C1A>>>")
        llm = _StreamingLlmStub(
            [
                Response(
                    id="resp-eager-parse-failed",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=content[:split_at],
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
                Response(
                    id="resp-eager-parse-failed",
                    choices=[
                        Choice(
                            index=0,
                            message=ChatMessage(
                                role="assistant",
                                content=content[split_at:],
                            ),
                        )
                    ],
                    created=0,
                    model="stream-model",
                ),
            ]
        )
        engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=self.session)
        task = self._create_task()
        context = ReactContext.from_task(task, self.session)

        recursion, event_data = asyncio.run(
            engine.execute_recursion(
                task=task,
                context=context,
                trace_id="trace-eager-parse-failed",
                input_message={"role": "user", "content": "Run streaming test"},
                messages=[{"role": "user", "content": "Run streaming test"}],
                token_meter_queue=asyncio.Queue(),
            )
        )

        self.assertEqual(recursion.status, "error")
        self.assertEqual(event_data["action_type"], "CALL_TOOL")
        self.assertFalse(event_data["rollback_messages"])
        self.assertIn("Unused payload blocks detected", event_data["parse_error"])
        self.assertEqual(
            event_data["tool_results"],
            [
                {
                    "tool_call_id": "call-1",
                    "name": "read_file",
                    "arguments": {"path": "README.md"},
                    "result": {"ok": True, "path": "README.md"},
                    "success": True,
                }
            ],
        )
        self.assertEqual(
            tool_manager.calls,
            [{"name": "read_file", "path": "README.md"}],
        )

        next_action_result = engine._build_next_pending_action_result(event_data)
        self.assertEqual(
            next_action_result,
            [
                {"id": "call-1", "result": {"ok": True, "path": "README.md"}},
                {
                    "error": event_data["parse_error"],
                    "source": "assistant_response_parse",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
