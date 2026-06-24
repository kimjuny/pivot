"""Unit tests for streaming token-usage normalization in the ReAct engine.

Covers three live-rendering pipelines powered by ``StreamingFieldExtractor``:
  * tokens/s rate reporting (reasoning + content + tool_call arguments)
  * tool_payload_delta for field-internal streaming of write_file/edit_file
    arguments (content/diff/old_string/new_string)
  * answer_delta for incremental ANSWER text rendering
plus eager tool execution while the provider stream is still open.
"""

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


def _stream_chunk(
    content: str = "",
    *,
    resp_id: str = "resp-1",
    model: str = "stream-model",
    tool_calls: list[dict[str, Any]] | None = None,
    usage: UsageInfo | None = None,
    finish_reason: str | None = None,
) -> Response:
    """Build one streaming Response chunk with native tool_calls support."""
    message_kwargs: dict[str, Any] = {"role": "assistant"}
    if content:
        message_kwargs["content"] = content
    if tool_calls:
        message_kwargs["tool_calls"] = tool_calls
    return Response(
        id=resp_id,
        choices=[
            Choice(
                index=0,
                message=ChatMessage(**message_kwargs),
                finish_reason=finish_reason,
            )
        ],
        created=0,
        model=model,
        usage=usage,
    )


class _StreamingLlmStub:
    """Minimal LLM stub that returns predefined streaming chunks."""

    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def chat_stream(self, messages: list[dict[str, object]], **kwargs: object):
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

    def _drain(self, queue: asyncio.Queue[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while not queue.empty():
            items.append(queue.get_nowait())
        return items

    # ------------------------------------------------------------------ #
    # Token-usage normalization (unchanged from original protocol).
    # ------------------------------------------------------------------ #

    def test_stream_uses_latest_cumulative_usage_snapshot_once(self) -> None:
        """Monotonic snapshot chunks should resolve to one final usage record."""
        llm = _StreamingLlmStub(
            [
                _stream_chunk("hel"),
                _stream_chunk(
                    "lo",
                    usage=UsageInfo(
                        prompt_tokens=1200,
                        completion_tokens=1,
                        total_tokens=1201,
                        cached_input_tokens=900,
                    ),
                ),
                _stream_chunk(
                    "",
                    usage=UsageInfo(
                        prompt_tokens=1200,
                        completion_tokens=2,
                        total_tokens=1202,
                        cached_input_tokens=900,
                    ),
                ),
                _stream_chunk(
                    "",
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

    def test_stream_falls_back_to_additive_mode_for_non_monotonic_usage(self) -> None:
        """Non-monotonic chunks should be treated as deltas instead of snapshots."""
        llm = _StreamingLlmStub(
            [
                _stream_chunk(
                    "ok",
                    usage=UsageInfo(
                        prompt_tokens=5,
                        completion_tokens=1,
                        total_tokens=6,
                        cached_input_tokens=0,
                    ),
                ),
                _stream_chunk(
                    "",
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

    # ------------------------------------------------------------------ #
    # New: tokens/s counts tool_call argument fragments too.
    # ------------------------------------------------------------------ #

    def test_token_rate_counts_tool_call_argument_fragments(self) -> None:
        """A pure tool-call iteration must still report a positive tokens/s.

        Regression guard: previously only reasoning + content were counted,
        so tool-call-only iterations always reported 0 tokens/s and the
        frontend suppressed the counter.
        """
        llm = _StreamingLlmStub(
            [
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path": "a.txt", "content": "',
                            },
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "",
                                "arguments": "line1\\nline2\\nline3",
                            },
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "", "arguments": '"}'},
                        }
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
            )
        )

        items = self._drain(queue)
        rate_items = [i for i in items if i.get("type") == "token_rate"]
        # The final token_rate snapshot should reflect argument tokens.
        self.assertGreater(len(rate_items), 0)
        last_rate = rate_items[-1]
        self.assertGreater(last_rate["estimated_completion_tokens"], 0)

    # ------------------------------------------------------------------ #
    # New: write_file arguments stream as raw-JSON tool_payload_delta
    # fragments.  Field-level extraction (content / diff / ...) has moved
    # to the frontend, so the backend just forwards the raw arguments
    # text verbatim for the frontend extractor to parse.
    # ------------------------------------------------------------------ #

    def test_write_file_args_stream_as_raw_fragments(self) -> None:
        """Raw arguments JSON fragments stream through untouched."""
        llm = _StreamingLlmStub(
            [
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-wf",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path": "README.md", "content": "',
                            },
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-wf",
                            "type": "function",
                            "function": {"name": "", "arguments": "# Title\\n"},
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-wf",
                            "type": "function",
                            "function": {"name": "", "arguments": "body text"},
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-wf",
                            "type": "function",
                            "function": {"name": "", "arguments": '"}'},
                        }
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
            )
        )

        items = self._drain(queue)
        deltas = [i for i in items if i.get("type") == "tool_payload_delta"]
        # Concatenated raw fragments reconstruct the full arguments JSON the
        # LLM emitted.  The frontend extractor parses this to surface content.
        concatenated = "".join(i["delta"] for i in deltas)
        self.assertEqual(
            concatenated,
            '{"path": "README.md", "content": "# Title\\nbody text"}',
        )
        # No field-name / is_final keys anymore: the backend is a dumb pipe.
        for delta in deltas:
            self.assertNotIn("argument_name", delta)
            self.assertNotIn("is_final", delta)
        # A finalized tool_call event carries the parsed arguments.
        tool_calls = [i for i in items if i.get("type") == "tool_call"]
        finalized = [
            tc
            for tc in tool_calls
            for call in tc.get("tool_calls", [])
            if not call.get("pending_arguments", True)
        ]
        self.assertTrue(finalized)

    def test_edit_file_args_stream_as_raw_fragments(self) -> None:
        """edit_file arguments (old_string + new_string) stream as raw JSON."""
        llm = _StreamingLlmStub(
            [
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-ef",
                            "type": "function",
                            "function": {
                                "name": "edit_file",
                                "arguments": '{"path": "a.py", "old_string": "foo", "new_string": "',
                            },
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-ef",
                            "type": "function",
                            "function": {"name": "", "arguments": "bar"},
                        }
                    ]
                ),
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-ef",
                            "type": "function",
                            "function": {"name": "", "arguments": '"}'},
                        }
                    ],
                    finish_reason="tool_calls",
                ),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
            )
        )

        items = self._drain(queue)
        deltas = [i for i in items if i.get("type") == "tool_payload_delta"]
        concatenated = "".join(i["delta"] for i in deltas)
        self.assertEqual(
            concatenated,
            '{"path": "a.py", "old_string": "foo", "new_string": "bar"}',
        )

    # ------------------------------------------------------------------ #
    # New: ANSWER text streams as answer_delta.
    # ------------------------------------------------------------------ #

    def test_answer_streams_as_answer_delta(self) -> None:
        """ANSWER envelope's answer field streams incrementally as deltas."""
        envelope = (
            '{"iteration": 1, "message": "Done", '
            '"action": {"action_type": "ANSWER", "output": {"answer": "'
        )
        llm = _StreamingLlmStub(
            [
                _stream_chunk(envelope),
                _stream_chunk("Hello"),
                _stream_chunk(" world"),
                _stream_chunk('"}}}'),
            ]
        )
        engine = ReactEngine(
            llm=llm,
            tool_manager=SimpleNamespace(),
            db=self.session,
        )
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
            )
        )

        items = self._drain(queue)
        answer_deltas = [i for i in items if i.get("type") == "answer_delta"]
        # The emit buffer may coalesce the two fragments into one batched
        # delta when they arrive within the same window.  What matters is
        # the concatenated content is correct and a final delta settles it.
        concatenated = "".join(i["delta"] for i in answer_deltas)
        self.assertEqual(concatenated, "Hello world")
        self.assertTrue(answer_deltas[-1]["is_final"])

    # ------------------------------------------------------------------ #
    # Regression: the run_task yield pump must forward queued answer_delta
    # items to the SSE stream.  Previously the pump had no answer_delta
    # branch, so every fragment fell through to the token_rate fallback and
    # ANSWER text only arrived as a single dump on recursion end.
    # ------------------------------------------------------------------ #

    def test_answer_delta_meter_to_sse_forwards_text(self) -> None:
        """A text-bearing answer_delta meter item becomes an SSE event."""
        event = ReactEngine._answer_delta_meter_to_sse(
            {"delta": "Hello", "is_final": False}
        )
        self.assertIsNotNone(event)
        assert event is not None  # for the type checker
        self.assertEqual(event["type"], "answer_delta")
        self.assertEqual(event["data"], {"delta": "Hello"})

    def test_answer_delta_meter_to_sse_marks_final(self) -> None:
        """The final fragment carries is_final=True so the frontend can settle."""
        event = ReactEngine._answer_delta_meter_to_sse({"delta": "", "is_final": True})
        self.assertEqual(event["data"], {"delta": "", "is_final": True})

    def test_answer_delta_meter_to_sse_drops_empty_non_final(self) -> None:
        """An empty coalesced tick with no final flag produces no wire noise."""
        self.assertIsNone(
            ReactEngine._answer_delta_meter_to_sse({"delta": "", "is_final": False})
        )

    # ------------------------------------------------------------------ #
    # Eager tool execution: native tool-call args complete mid-stream.
    # ------------------------------------------------------------------ #

    def test_eager_tool_starts_when_arguments_complete_mid_stream(self) -> None:
        """Closing the args JSON mid-stream should start the tool eagerly."""
        complete_args = '{"path": "README.md"}'
        tool_started = threading.Event()
        tool_manager = _EagerToolManagerStub(tool_started)
        llm = _BlockingStreamingLlmStub(
            [
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": complete_args,
                            },
                        }
                    ]
                ),
                _stream_chunk(content=""),
            ],
            tool_started,
        )
        engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=self.session)
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        eager_state = EagerToolExecutionState()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
                eager_state=eager_state,
            )
        )

        items = self._drain(queue)
        # Tool started before stream finished (BlockingIterator enforces this).
        self.assertTrue(tool_started.is_set())
        self.assertEqual(
            tool_manager.calls,
            [{"name": "read_file", "path": "README.md"}],
        )
        self.assertEqual(eager_state.started_call_ids, {"call-1"})
        # Final tool_call event has resolved arguments and no pending flag.
        final_tool_calls = [
            i
            for i in items
            if i.get("type") == "tool_call" and not i.get("tool_results")
        ]
        last_call = final_tool_calls[-1]
        self.assertEqual(last_call["tool_calls"][0]["arguments"], {"path": "README.md"})
        self.assertFalse(last_call["tool_calls"][0]["pending_arguments"])

    def test_eager_tool_starts_and_drains_after_stream(self) -> None:
        """Eager tool starts mid-stream and its result is drained by stream end.

        The result is emitted after stream completion (via
        ``_drain_eager_results``), not between chunks; this verifies the
        tool executed eagerly (during streaming) and the result is available
        once the stream closes.
        """
        complete_args = '{"path": "README.md"}'
        tool_started = threading.Event()
        tool_manager = _EagerToolManagerStub(tool_started)
        llm = _StreamingLlmStub(
            [
                _stream_chunk(
                    tool_calls=[
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": complete_args,
                            },
                        }
                    ]
                ),
                _stream_chunk(content=""),
            ]
        )
        engine = ReactEngine(llm=llm, tool_manager=tool_manager, db=self.session)
        token_counter = engine._new_token_counter()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        eager_state = EagerToolExecutionState()

        asyncio.run(
            engine._stream_chat_response(
                messages=[{"role": "user", "content": "hello"}],
                llm_chat_kwargs={},
                token_counter=token_counter,
                token_meter_queue=queue,
                eager_state=eager_state,
            )
        )

        # Tool started during streaming (eager) and result drained by stream end.
        self.assertTrue(tool_started.is_set())
        self.assertIn("call-1", eager_state.result_by_call_id)
        items = self._drain(queue)
        tool_result_items = [i for i in items if i.get("type") == "tool_result"]
        self.assertEqual(len(tool_result_items), 1)
        self.assertEqual(
            tool_manager.calls,
            [{"name": "read_file", "path": "README.md"}],
        )


if __name__ == "__main__":
    unittest.main()
