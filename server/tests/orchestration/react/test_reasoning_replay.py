"""Unit tests for reasoning_content replay through ReactRuntimeService."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
ReactRuntimeService = import_module(
    "app.services.react_runtime_service"
).ReactRuntimeService


class ReasoningReplayTestCase(unittest.TestCase):
    """Verify reasoning_content is persisted and replayed across recursions."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        agent = Agent(name="replay-agent", llm_id=None)
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        self.agent = agent

        session_row = SessionModel(
            session_id="session-replay",
            agent_id=agent.id or 0,
            user_id=1,
            react_llm_messages="[]",
        )
        self.db.add(session_row)
        self.db.commit()
        self.db.refresh(session_row)
        self.session_row = session_row

    def tearDown(self) -> None:
        self.db.close()

    def _create_task(self) -> ReactTask:
        task = ReactTask(
            task_id="task-replay",
            session_id=self.session_row.session_id,
            agent_id=self.agent.id or 0,
            user_id=1,
            user_message="hello",
            user_intent="hello",
            iteration=0,
            runtime_message_start_index=0,
        )
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def test_reasoning_content_is_persisted_and_reloaded(self) -> None:
        """append_assistant_message should round-trip reasoning_content."""
        task = self._create_task()
        service = ReactRuntimeService(self.db)

        service.append_assistant_message(
            task,
            content="answer",
            reasoning_content="my chain of thought",
        )

        reloaded = service.load(task)
        assistant_msgs = [
            m for m in reloaded.messages if m.get("role") == "assistant"
        ]
        self.assertEqual(len(assistant_msgs), 1)
        self.assertEqual(assistant_msgs[0]["content"], "answer")
        self.assertEqual(
            assistant_msgs[0]["reasoning_content"], "my chain of thought"
        )

    def test_empty_reasoning_content_not_stored(self) -> None:
        """Empty/None reasoning_content must not pollute the message dict."""
        task = self._create_task()
        service = ReactRuntimeService(self.db)

        service.append_assistant_message(task, content="answer", reasoning_content="")
        service.append_assistant_message(task, content="answer2")

        reloaded = service.load(task)
        for msg in reloaded.messages:
            if msg.get("role") == "assistant":
                self.assertNotIn("reasoning_content", msg)

    def test_reasoning_replay_feeds_next_recursion(self) -> None:
        """A multi-turn scenario: round 1 reasoning present in round 2 messages."""
        task = self._create_task()
        service = ReactRuntimeService(self.db)

        # Round 1: assistant returns reasoning + tool call.
        service.append_assistant_message(
            task,
            content="",
            reasoning_content="thinking about the task",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "search",
                    "arguments": '{"q": "test"}',
                }
            ],
        )

        # Round 2 messages (loaded fresh) must contain round 1's reasoning.
        reloaded = service.load(task)
        assistant_msg = reloaded.messages[-1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertEqual(assistant_msg["reasoning_content"], "thinking about the task")
        self.assertEqual(assistant_msg["tool_calls"][0]["name"], "search")


if __name__ == "__main__":
    unittest.main()
