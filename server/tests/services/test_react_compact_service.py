"""Unit tests for manual session compaction service."""

import asyncio
import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
LLM = import_module("app.models.llm").LLM
SessionModel = import_module("app.models.session").Session
ReactRuntimeService = import_module(
    "app.services.react_runtime_service"
).ReactRuntimeService
react_compact_service_module = import_module("app.services.react_compact_service")
ReactCompactService = react_compact_service_module.ReactCompactService


class _FakeLLM:
    """Tiny fake LLM that records messages and returns one JSON compact result."""

    def __init__(self, response_content: str) -> None:
        self.response_content = response_content
        self.calls: list[list[dict[str, object]]] = []

    def chat(
        self,
        messages: list[dict[str, object]],
        *,
        _pivot_task_id: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append([dict(message) for message in messages])
        return SimpleNamespace(
            first=lambda: SimpleNamespace(
                message=SimpleNamespace(content=self.response_content)
            )
        )


class ReactCompactServiceTestCase(unittest.TestCase):
    """Validate session-level compact execution and no-op boundaries."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        llm = LLM(
            name="manual-compact-llm",
            endpoint="https://example.com/v1",
            model="qwen-plus",
            api_key="secret",
            max_context=8000,
        )
        self.session.add(llm)
        self.session.commit()
        self.session.refresh(llm)
        self.llm = llm

        agent = Agent(name="agent-compact", llm_id=llm.id)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        session_row = SessionModel(
            session_id="session-compact-service",
            agent_id=agent.id or 0,
            user_id=1,
            status="active",
            runtime_status="idle",
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.session.add(session_row)
        self.session.commit()
        self.session.refresh(session_row)
        self.session_row = session_row

        self.runtime_service = ReactRuntimeService(self.session)
        self.service = ReactCompactService(self.session)

    def tearDown(self) -> None:
        self.session.close()

    def test_compact_session_injects_user_instruction_and_rebuilds_runtime(
        self,
    ) -> None:
        """Manual compact should inject user guidance and persist system+compact."""
        self.runtime_service.replace_session_runtime_messages(
            self.session_row.session_id,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "Need a cleaner memory."},
                {"role": "assistant", "content": "Sure, I can help."},
            ],
            compact_result=None,
            preserve_cache_state=True,
        )
        fake_llm = _FakeLLM('{"history_summary":"compacted"}')

        with patch.object(
            react_compact_service_module,
            "create_llm_from_config",
            return_value=fake_llm,
        ):
            result = asyncio.run(
                self.service.compact_session(
                    session_id=self.session_row.session_id,
                    user_instruction="Focus on decisions and active files only.",
                )
            )

        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["compacted"])
        self.assertEqual(result["reason"], "manual_request")
        self.assertEqual(len(fake_llm.calls), 1)
        injected_prompt = str(fake_llm.calls[0][-1]["content"])
        self.assertIn("<user_compact_requirements>", injected_prompt)
        self.assertIn("Focus on decisions and active files only.", injected_prompt)

        runtime_state = self.runtime_service.load_session(self.session_row.session_id)
        self.assertEqual(
            runtime_state.messages,
            [
                {"role": "system", "content": "system prompt"},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"history_summary": "compacted"}, ensure_ascii=False
                    ),
                },
            ],
        )
        self.assertEqual(
            runtime_state.compact_result, runtime_state.messages[1]["content"]
        )

    def test_compact_session_returns_noop_when_runtime_is_already_compacted(
        self,
    ) -> None:
        """A runtime window containing only system+compact should skip the LLM call."""
        compact_result = json.dumps({"history_summary": "ready"}, ensure_ascii=False)
        self.runtime_service.replace_session_runtime_messages(
            self.session_row.session_id,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "assistant", "content": compact_result},
            ],
            compact_result=compact_result,
            preserve_cache_state=False,
        )

        with patch.object(
            react_compact_service_module,
            "create_llm_from_config",
            side_effect=AssertionError("LLM should not be called for noop compact."),
        ):
            result = asyncio.run(
                self.service.compact_session(session_id=self.session_row.session_id)
            )

        self.assertEqual(result["status"], "noop")
        self.assertFalse(result["compacted"])
        self.assertEqual(result["reason"], "already_compacted")


if __name__ == "__main__":
    unittest.main()
