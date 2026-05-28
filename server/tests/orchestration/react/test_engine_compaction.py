"""Unit tests for runtime-window compaction behavior."""

import asyncio
import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlmodel import Session, SQLModel, create_engine, select

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")
Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
User = import_module("app.models.user").User
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
        self.captured_compact_mode = "session"
        self.runtime_messages_during_compact: list[dict[str, object]] = []
        self.emitted_events: list[dict[str, object]] = []
        self.emitted_event_count_during_compact = 0

    async def _execute_compaction(
        self,
        *,
        task: Any,
        source_messages: list[dict[str, object]],
        compact_mode: str = "session",
    ) -> tuple[str, dict[str, int]]:
        """Capture the exact compaction inputs instead of calling a real LLM."""
        self.captured_source_messages = [dict(message) for message in source_messages]
        self.captured_compact_mode = compact_mode
        self.emitted_event_count_during_compact = len(self.emitted_events)
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
            json.dumps({"message": "compacted"}, ensure_ascii=False),
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

        user = User(username="alice", password_hash="hash", role_id=1)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        self.user = user

        session_row = SessionModel(
            session_id="session-compact",
            agent_id=agent.id or 0,
            user_id=user.id or 0,
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
            user_id=user.id or 0,
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
            '{"action":{"action_type":"REFLECT","output":{"message":"working"}}}',
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
            json.dumps({"message": "compacted"}, ensure_ascii=False),
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
                        '{"message":"working"}}}'
                    ),
                },
            ],
        )
        self.assertEqual(self.task.runtime_message_start_index, 2)
        self.assertIsNone(self.task.stashed_messages)

    def test_compact_start_can_be_emitted_before_compaction_runs(self) -> None:
        """Automatic compact should notify clients before the LLM compact call."""
        harness = _CompactionHarnessEngine(self.session)
        runtime_state = self.runtime_service.load(self.task)

        async def run_compact() -> tuple[Any, list[dict[str, Any]]]:
            async def emit_event(event: dict[str, Any]) -> None:
                harness.emitted_events.append(event)

            return await harness._maybe_compact_runtime_window(
                task=self.task,
                runtime_state=runtime_state,
                system_prompt="system prompt",
                max_context_tokens=1,
                threshold_percent=1,
                reason="iteration_threshold",
                emit_event=emit_event,
            )

        _updated_state, events = asyncio.run(run_compact())

        self.assertEqual(
            [event["type"] for event in harness.emitted_events],
            ["compact_start"],
        )
        self.assertEqual(harness.emitted_event_count_during_compact, 1)
        self.assertEqual(
            [event["type"] for event in events],
            ["compact_complete"],
        )

    def test_task_start_compaction_rebuilds_runtime_without_stashing(self) -> None:
        """Task-start compaction should summarize the whole pre-task session window."""
        fresh_task = ReactTask(
            task_id="task-compact-start",
            session_id=self.session_row.session_id,
            agent_id=self.agent.id or 0,
            user_id=self.user.id or 0,
            user_message="Start a new task",
            user_intent="Start a new task",
            status="running",
            iteration=0,
            max_iteration=8,
        )
        self.session.add(fresh_task)
        self.session.commit()
        self.session.refresh(fresh_task)

        self.runtime_service.replace_runtime_messages(
            fresh_task,
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "previous user"},
                {"role": "assistant", "content": "previous assistant"},
            ],
            compact_result=None,
            preserve_cache_state=True,
        )

        harness = _CompactionHarnessEngine(self.session)
        runtime_state = self.runtime_service.load(fresh_task)

        updated_state, events = asyncio.run(
            harness._maybe_compact_runtime_window(
                task=fresh_task,
                runtime_state=runtime_state,
                system_prompt="system prompt",
                max_context_tokens=1,
                threshold_percent=1,
                reason="task_start_threshold",
            )
        )

        self.session.refresh(fresh_task)
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
            updated_state.messages,
            [
                {"role": "system", "content": "system prompt"},
                {
                    "role": "assistant",
                    "content": json.dumps({"message": "compacted"}, ensure_ascii=False),
                },
            ],
        )
        self.assertEqual(fresh_task.runtime_message_start_index, 0)
        self.assertIsNone(fresh_task.stashed_messages)

    def test_preview_usage_can_trigger_compaction_before_next_send(self) -> None:
        """Preview messages should count toward the compact threshold check."""
        harness = _CompactionHarnessEngine(self.session)
        runtime_state = self.runtime_service.load(self.task)
        preview_messages = [
            {
                "role": "user",
                "content": "preview " * 600,
            }
        ]

        usage_without_preview = harness._build_usage_snapshot(
            task=self.task,
            runtime_state=runtime_state,
            max_context_tokens=500,
        )
        usage_with_preview = harness._build_usage_snapshot(
            task=self.task,
            runtime_state=runtime_state,
            max_context_tokens=500,
            preview_messages=preview_messages,
        )
        threshold_percent = usage_with_preview["used_percent"]

        self.assertLess(usage_without_preview["used_percent"], threshold_percent)

        updated_state, events = asyncio.run(
            harness._maybe_compact_runtime_window(
                task=self.task,
                runtime_state=runtime_state,
                system_prompt="system prompt",
                max_context_tokens=500,
                threshold_percent=threshold_percent,
                reason="iteration_threshold",
                preview_messages=preview_messages,
            )
        )

        self.assertEqual(
            [event["type"] for event in events],
            ["compact_start", "compact_complete"],
        )
        self.assertEqual(updated_state.messages[0]["role"], "system")
        self.assertEqual(updated_state.messages[1]["role"], "assistant")

    def test_mid_task_compaction_falls_back_to_in_task_memory(self) -> None:
        """When there is no pre-task history, compact the finished task slice."""
        fresh_task = ReactTask(
            task_id="task-in-task-compact",
            session_id=self.session_row.session_id,
            agent_id=self.agent.id or 0,
            user_id=self.user.id or 0,
            user_message="Write a long report",
            user_intent="Write a long report",
            status="running",
            iteration=2,
            max_iteration=8,
        )
        self.session.add(fresh_task)
        self.session.commit()
        self.session.refresh(fresh_task)

        self.runtime_service.replace_runtime_messages(
            fresh_task,
            [{"role": "system", "content": "system prompt"}],
            compact_result=None,
            preserve_cache_state=True,
        )
        self.runtime_service.append_task_bootstrap_prompt(
            fresh_task,
            "task bootstrap prompt",
        )
        self.runtime_service.append_user_payload(
            fresh_task,
            {
                "iteration": 1,
                "user_intent": "Write a long report",
                "current_plan": [],
            },
        )
        self.runtime_service.append_assistant_message(
            fresh_task,
            '{"action":{"action_type":"REFLECT","output":{"message":"drafted section 1"}}}',
        )

        harness = _CompactionHarnessEngine(self.session)
        runtime_state = self.runtime_service.load(fresh_task)

        updated_state, events = asyncio.run(
            harness._maybe_compact_runtime_window(
                task=fresh_task,
                runtime_state=runtime_state,
                system_prompt="system prompt",
                max_context_tokens=1,
                threshold_percent=1,
                reason="iteration_threshold",
            )
        )

        self.session.refresh(fresh_task)
        self.assertEqual(harness.captured_compact_mode, "in_task")
        self.assertEqual(
            [event["data"]["compact_mode"] for event in events],
            ["in_task", "in_task"],
        )
        self.assertEqual(
            harness.captured_source_messages,
            [
                {"role": "user", "content": "task bootstrap prompt"},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "iteration": 1,
                            "user_intent": "Write a long report",
                            "current_plan": [],
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        '{"action":{"action_type":"REFLECT","output":'
                        '{"message":"drafted section 1"}}}'
                    ),
                },
            ],
        )
        self.assertEqual(
            updated_state.messages,
            [
                {"role": "system", "content": "system prompt"},
                {
                    "role": "assistant",
                    "content": json.dumps({"message": "compacted"}, ensure_ascii=False),
                },
            ],
        )
        self.assertEqual(fresh_task.runtime_message_start_index, 1)
        self.assertIsNone(fresh_task.stashed_messages)

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
        self.assertEqual(
            self.runtime_service.load(self.task).messages, original_messages
        )
        self.assertIsNone(self.task.stashed_messages)


if __name__ == "__main__":
    unittest.main()
