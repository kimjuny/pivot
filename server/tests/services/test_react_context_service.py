"""Unit tests for ReAct prompt-context estimation service."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models.file")
AgentRelease = import_module("app.models.agent_release").AgentRelease
LLM = import_module("app.models.llm").LLM
Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
ReactRuntimeService = import_module(
    "app.services.react_runtime_service"
).ReactRuntimeService
ReactContextUsageService = import_module(
    "app.services.react_context_service"
).ReactContextUsageService


class ReactContextUsageServiceTestCase(unittest.TestCase):
    """Validate prompt-context estimation for preview and active-task states."""

    def setUp(self) -> None:
        """Create an isolated in-memory database per test."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        llm = LLM(
            name="qwen-test",
            endpoint="https://example.com/v1",
            model="qwen-plus",
            api_key="secret",
            max_context=5000,
        )
        self.session.add(llm)
        self.session.commit()
        self.session.refresh(llm)
        self.llm = llm

        release_llm = LLM(
            name="qwen-release",
            endpoint="https://example.com/v1",
            model="qwen-max",
            api_key="secret",
            max_context=9000,
        )
        self.session.add(release_llm)
        self.session.commit()
        self.session.refresh(release_llm)
        self.release_llm = release_llm

        agent = Agent(name="agent-1", llm_id=llm.id)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        release = AgentRelease(
            agent_id=agent.id or 0,
            version=1,
            snapshot_json=(
                f'{{"schema_version":1,"agent":{{"id":{agent.id},"name":"agent-1",'
                f'"description":null,"llm_id":{release_llm.id},'
                '"session_idle_timeout_minutes":15,'
                '"sandbox_timeout_seconds":60,'
                '"compact_threshold_percent":60,'
                '"is_active":true,'
                '"max_iteration":30,'
                '"tool_ids":null,'
                '"skill_ids":null},'
                '"channel_bindings":[],"web_search_bindings":[]}'
            ),
            snapshot_hash="release-hash",
            change_summary_json="[]",
        )
        self.session.add(release)
        self.session.commit()
        self.session.refresh(release)
        self.release = release

        session_row = SessionModel(
            session_id="session-1",
            agent_id=agent.id or 0,
            release_id=release.id or 0,
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

        self.runtime_service = ReactRuntimeService(self.session)
        self.service = ReactContextUsageService(self.session)

    def tearDown(self) -> None:
        """Close the session after each test."""
        self.session.close()

    def test_estimate_next_turn_preview_includes_system_and_draft(self) -> None:
        """Preview mode should count both the system prompt and draft payload."""
        result = self.service.estimate(
            agent_id=self.agent.id or 0,
            username="alice",
            session_id=self.session_row.session_id,
            draft_message="Explain how this project works.",
        )

        self.assertEqual(result.estimation_mode, "next_turn_preview")
        self.assertEqual(result.message_count, 3)
        self.assertGreater(result.system_tokens, 0)
        self.assertGreater(result.draft_tokens, 0)
        self.assertEqual(
            result.used_tokens, result.system_tokens + result.conversation_tokens
        )
        self.assertEqual(
            result.remaining_tokens,
            self.release_llm.max_context - result.used_tokens,
        )
        self.assertEqual(result.max_context_tokens, self.release_llm.max_context)

    def test_estimate_reply_preview_uses_runtime_messages(self) -> None:
        """Reply preview should extend persisted runtime messages with a new user turn."""
        task = ReactTask(
            task_id="task-1",
            agent_id=self.agent.id or 0,
            session_id=self.session_row.session_id,
            user="alice",
            user_message="Need help",
            user_intent="Need help",
            status="waiting_input",
            iteration=1,
            max_iteration=8,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)

        self.runtime_service.initialize(task, "system prompt")
        self.runtime_service.append_user_payload(
            task,
            {
                "trace_id": "trace-1",
                "iteration": 1,
                "user_intent": "Need help",
                "current_plan": [],
            },
        )
        self.runtime_service.append_assistant_message(
            task,
            '{"action":{"action_type":"CLARIFY","output":{"question":"Which file?"}}}',
        )
        self.runtime_service.set_next_action_result(
            task,
            [{"result": {"question": "Which file?"}}],
        )

        result = self.service.estimate(
            agent_id=self.agent.id or 0,
            username="alice",
            task_id=task.task_id,
            draft_message="Look at ReactChatInterface.tsx.",
        )

        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.estimation_mode, "reply_preview")
        self.assertEqual(result.message_count, 4)
        self.assertGreater(result.draft_tokens, 0)
        self.assertGreater(result.conversation_tokens, result.draft_tokens)

    def test_estimate_studio_test_preview_uses_working_copy_snapshot(self) -> None:
        """Studio previews should use the unsaved working-copy runtime config."""
        result = self.service.estimate(
            agent_id=self.agent.id or 0,
            username="alice",
            session_type="studio_test",
            test_snapshot={
                "schema_version": 1,
                "agent": {
                    "name": "agent-1 draft",
                    "description": "Draft preview",
                    "llm_id": self.llm.id,
                    "session_idle_timeout_minutes": 15,
                    "sandbox_timeout_seconds": 60,
                    "compact_threshold_percent": 60,
                    "is_active": True,
                    "max_iteration": 12,
                    "tool_ids": ["web_search"],
                    "skill_ids": None,
                },
            },
            draft_message="Preview my unsaved test session.",
        )

        self.assertEqual(result.estimation_mode, "next_turn_preview")
        self.assertEqual(result.max_context_tokens, self.llm.max_context)
        self.assertGreater(result.used_tokens, 0)


if __name__ == "__main__":
    unittest.main()
