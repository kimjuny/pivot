"""Unit tests for Auto thinking-mode decisions in the ReAct engine."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import_module("app.models")

if TYPE_CHECKING:
    from app.models.react import ReactTask
    from app.orchestration.react.engine import ReactEngine

Agent = import_module("app.models.agent").Agent
ReactRecursion = import_module("app.models.react").ReactRecursion
ReactTask = import_module("app.models.react").ReactTask
SessionModel = import_module("app.models.session").Session
ReactEngine = import_module("app.orchestration.react.engine").ReactEngine


def _build_assistant_decision(thinking_next_turn: bool) -> str:
    """Return a minimal valid assistant decision JSON string."""
    return json.dumps(
        {
            "trace_id": "trace-1",
            "observe": "Observed current state.",
            "reason": "Choose the next best action.",
            "summary": "Progress update.",
            "thinking_next_turn": thinking_next_turn,
            "session_title": "",
            "action": {
                "action_type": "REFLECT",
                "output": {},
            },
        },
        ensure_ascii=False,
    )


class ReactEngineThinkingModeTestCase(unittest.TestCase):
    """Verify engine Auto mode honors the previous recursion's hint."""

    def setUp(self) -> None:
        """Create an isolated database session and engine fixture."""
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        agent = Agent(name="thinking-agent", llm_id=None)
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        self.agent = agent

        session_row = SessionModel(
            session_id="session-thinking",
            agent_id=agent.id or 0,
            user="alice",
            react_llm_messages="[]",
        )
        self.session.add(session_row)
        self.session.commit()
        self.session.refresh(session_row)
        self.session_row = session_row

    def tearDown(self) -> None:
        """Close the database session."""
        self.session.close()

    def _create_task(self):
        """Create one session-backed task for runtime thinking tests."""
        task = ReactTask(
            task_id="task-thinking",
            session_id=self.session_row.session_id,
            agent_id=self.agent.id or 0,
            user="alice",
            user_message="hello",
            user_intent="hello",
            iteration=1,
            runtime_message_start_index=0,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return task

    def _build_engine(self):
        """Create a ReactEngine configured for Auto thinking-mode resolution."""
        return ReactEngine(
            llm=cast(Any, SimpleNamespace()),
            tool_manager=cast(Any, SimpleNamespace()),
            db=self.session,
            stream_llm_responses=False,
            thinking_runtime_config={
                "protocol": "openai_response_llm",
                "thinking_policy": "openai-response-reasoning-effort",
                "thinking_effort": "high",
                "thinking_mode": "auto",
            },
        )

    def test_auto_mode_uses_previous_assistant_hint(self) -> None:
        """Previous assistant JSON should decide whether Auto turns thinking on."""
        task = self._create_task()
        self.session_row.react_llm_messages = json.dumps(
            [{"role": "assistant", "content": _build_assistant_decision(True)}],
            ensure_ascii=False,
        )
        self.session.add(self.session_row)
        self.session.commit()

        runtime_kwargs = self._build_engine()._build_iteration_llm_runtime_kwargs(task)

        self.assertEqual(runtime_kwargs, {"reasoning": {"effort": "high"}})

    def test_auto_mode_forces_thinking_after_failure_even_when_declined(self) -> None:
        """Previous recursion failures should override a false agent hint."""
        task = self._create_task()
        self.session_row.react_llm_messages = json.dumps(
            [{"role": "assistant", "content": _build_assistant_decision(False)}],
            ensure_ascii=False,
        )
        self.session.add(self.session_row)
        self.session.commit()

        failed_recursion = ReactRecursion(
            trace_id="trace-prev",
            task_id=task.task_id,
            react_task_id=task.id or 0,
            iteration_index=0,
            status="error",
        )
        self.session.add(failed_recursion)
        self.session.commit()

        runtime_kwargs = self._build_engine()._build_iteration_llm_runtime_kwargs(task)

        self.assertEqual(runtime_kwargs, {"reasoning": {"effort": "high"}})


if __name__ == "__main__":
    unittest.main()
