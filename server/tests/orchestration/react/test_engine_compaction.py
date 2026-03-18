"""Unit tests for runtime-window compaction behavior."""

import asyncio
import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
ReactEngine = import_module("app.orchestration.react.engine").ReactEngine
ReactRuntimeService = import_module(
    "app.services.react_runtime_service"
).ReactRuntimeService


class _CompactionHarnessEngine(ReactEngine):
    """Engine subclass that exposes compaction inputs for assertions."""

    def __init__(self, db: Session, *, fail_compaction: bool = False) -> None:
        """Initialize the harness with inert dependencies."""
        super().__init__(
            llm=SimpleNamespace(),
            tool_manager=SimpleNamespace(),
            db=db,
        )
        self.fail_compaction = fail_compaction
        self.captured_source_messages: list[dict[str, object]] = []
        self.runtime_messages_during_compact: list[dict[str, object]] = []

    async def _execute_compaction(
        self,
        *,
        task: ReactTask,
        source_messages: list[dict[str, object]],
    ) -> tuple[str, dict[str, int]]:
        """Capture the exact compaction inputs instead of calling a real LLM."""
        self.captured_source_messages = [dict(message) for message in source_messages]
        session_row = self.db.exec(
            select(SessionModel).where(SessionModel.session_id == task.session_id)
        ).first()
        if session_row is None:
            raise AssertionError("Expected session row during compaction")
        self.runtime_messages_during_compact = json.loads(
            session_row.react_llm_messages
        )
        if self.fail_compaction:
            raise RuntimeError("compaction failed")
        return (
            json.dumps({"summary": "compacted"}, ensure_ascii=False),
            {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "cached_input_tokens": 0,
            },
        )


class ReactEngineCompactionTestCase(unittest.TestCase):
    """Validate task-start and mid-task compaction boundaries."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        agent = Agent(name="agent-compact", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        session_row = SessionModel(
            session_id="session-compact",
            agent_id=agent.id or 0,
            user="alice",
            status="active",
            chat_history='{"version": 1, "messages": []}',
            react_llm_messages="[]",
            react_llm_cache_state="{}",
        )
        self.session.add(session_row)
        self.session.commit()
        self.session.refresh(session_row)
        self.session_row = session_row

        task = ReactTask(
            task_id="task-compact",
            session_id=session_row.session_id,
            agent_id=agent.id or 0,
            user="alice",
            user_message="Investigate the bug",
            user_intent="Investigate the bug",
            status="running",
            iteration=0,
            max_iteration=8,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        self.task = task

        self.runtime_service = ReactRuntimeService(self.session)
        self.runtime_service.replace_runtime_messages(
            self.task,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous assistant"},
            ],
            compact_result=None,
            preserve_cache_state=True,
        )
        self.runtime_service.append_task_bootstrap_prompt(
            self.task, "task bootstrap prompt"
        )
        self.runtime_service.append_user_payload(
            self.task,
            {
                "trace_id": "trace-1",
                "iteration": 1,
                "user_intent": "Investigate the bug",
                "current_plan": [],
            },
        )
        self.runtime_service.append_assistant_message(
            self.task,
            '{"action":{"action_type":"REFLECT","output":{"summary":"working"}}}',
        )
        self.task.iteration = 2
        self.session.add(self.task)
        self.session.commit()
        self.session.refresh(self.task)

    def tearDown(self) -> None:
        """Close the database session after each test."""
        self.session.close()

    def test_mid_task_compaction_only_summarizes_pre_task_history(self) -> None:
        """Mid-task compaction should cut and later restore current-task messages."""
        harness = _CompactionHarnessEngine(self.session)
        runtime_state = self.runtime_service.load(self.task)

        updated_state, events = asyncio.run(
            harness._maybe_compact_runtime_window(
                task=self.task,
                runtime_state=runtime_state,
                system_prompt="system prompt",
                max_context_tokens=1,
                threshold_percent=1,
                reason="iteration_threshold",
            )
        )

        self.session.refresh(self.task)
        self.assertEqual(
            [event["type"] for event in events],
            ["compact_start", "compact_complete"],
        )
        self.assertEqual(
            harness.captured_source_messages,
            [
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous assistant"},
            ],
        )
        self.assertEqual(
            harness.runtime_messages_during_compact,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous assistant"},
            ],
        )
        self.assertEqual(updated_state.messages[0]["role"], "system")
        self.assertEqual(updated_state.messages[1]["role"], "assistant")
        self.assertEqual(
            updated_state.messages[1]["content"],
            json.dumps({"summary": "compacted"}, ensure_ascii=False),
        )
        self.assertEqual(
            updated_state.messages[2:],
            [
                {"role": "user", "content": "task bootstrap prompt"},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "trace_id": "trace-1",
                            "iteration": 1,
                            "user_intent": "Investigate the bug",
                            "current_plan": [],
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        '{"action":{"action_type":"REFLECT","output":'
                        '{"summary":"working"}}}'
                    ),
                },
            ],
        )
        self.assertEqual(self.task.runtime_message_start_index, 2)
        self.assertIsNone(self.task.stashed_messages)

    def test_mid_task_compaction_restores_original_messages_on_failure(self) -> None:
        """A failed mid-task compact should keep the pre-compact runtime window."""
        harness = _CompactionHarnessEngine(self.session, fail_compaction=True)
        original_messages = self.runtime_service.load(self.task).messages

        updated_state, events = asyncio.run(
            harness._maybe_compact_runtime_window(
                task=self.task,
                runtime_state=self.runtime_service.load(self.task),
                system_prompt="system prompt",
                max_context_tokens=1,
                threshold_percent=1,
                reason="iteration_threshold",
            )
        )

        self.session.refresh(self.task)
        self.assertEqual(
            [event["type"] for event in events],
            ["compact_start", "compact_failed"],
        )
        self.assertEqual(
            harness.runtime_messages_during_compact,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous assistant"},
            ],
        )
        self.assertEqual(updated_state.messages, original_messages)
        self.assertEqual(self.runtime_service.load(self.task).messages, original_messages)
        self.assertIsNone(self.task.stashed_messages)


if __name__ == "__main__":
    unittest.main()
