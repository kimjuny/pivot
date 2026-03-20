"""Unit tests for streaming token-usage normalization in the ReAct engine."""

import asyncio
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
