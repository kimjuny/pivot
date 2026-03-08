"""Unit tests for ReAct runtime-state persistence service."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

# The backend code imports from the ``app`` package root. unittest discovery
# does not add ``server/`` to sys.path automatically, so tests do it explicitly.
SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

ReactTask = import_module("app.models.react").ReactTask
ReactRuntimeService = import_module(
    "app.services.react_runtime_service"
).ReactRuntimeService


class _FakeDB:
    """Minimal DB stub for runtime-service unit tests."""

    def __init__(self) -> None:
        """Initialize the fake persistence tracker."""
        self.added: list[object] = []
        self.commit_count = 0

    def add(self, item: object) -> None:
        """Record added objects.

        Args:
            item: ORM object passed into the fake session.
        """
        self.added.append(item)

    def commit(self) -> None:
        """Record a commit call."""
        self.commit_count += 1


class ReactRuntimeServiceTestCase(unittest.TestCase):
    """Validate task runtime-state persistence behavior."""

    def setUp(self) -> None:
        """Create a task and service for each test."""
        self.db = _FakeDB()
        self.service = ReactRuntimeService(self.db)
        self.task = ReactTask(
            task_id="task-1",
            agent_id=1,
            user="alice",
            user_message="hello",
            user_intent="hello",
        )

    def test_initialize_append_and_load_runtime_state(self) -> None:
        """Runtime service should persist and reload normalized state."""
        state = self.service.initialize(self.task, "system prompt")
        self.assertEqual(
            state.messages,
            [{"role": "system", "content": "system prompt"}],
        )

        self.service.append_user_payload(self.task, {"iteration": 1, "foo": "bar"})
        self.service.append_assistant_message(
            self.task, '{"action":{"action_type":"REFLECT","output":{}}}'
        )
        self.service.set_next_action_result(
            self.task,
            [{"id": "call-1", "result": {"ok": True}}],
        )
        self.service.set_previous_response_id(self.task, "resp-1")

        loaded = self.service.load(self.task)
        self.assertEqual(len(loaded.messages), 3)
        self.assertEqual(loaded.messages[1]["role"], "user")
        self.assertEqual(loaded.messages[2]["role"], "assistant")
        self.assertEqual(
            loaded.pending_action_result,
            [{"id": "call-1", "result": {"ok": True}}],
        )
        self.assertEqual(loaded.previous_response_id, "resp-1")
        self.assertGreaterEqual(self.db.commit_count, 4)

    def test_rollback_last_user_message(self) -> None:
        """Rollback should only remove the latest user payload."""
        self.service.initialize(self.task, "system prompt")
        self.service.append_user_payload(self.task, {"iteration": 1})

        rolled_back = self.service.rollback_last_user_message(self.task)
        self.assertEqual(
            rolled_back.messages,
            [{"role": "system", "content": "system prompt"}],
        )

    def test_clear_resets_all_runtime_fields(self) -> None:
        """Clear should drop messages, next action result, and cache linkage."""
        self.service.initialize(self.task, "system prompt")
        self.service.set_next_action_result(self.task, [{"result": {"foo": "bar"}}])
        self.service.set_previous_response_id(self.task, "resp-1")

        self.service.clear(self.task)

        loaded = self.service.load(self.task)
        self.assertEqual(loaded.messages, [])
        self.assertIsNone(loaded.pending_action_result)
        self.assertIsNone(loaded.previous_response_id)

    def test_invalid_serialized_state_falls_back_to_empty(self) -> None:
        """Broken persisted JSON should not crash runtime-state loading."""
        self.task.llm_messages = "{invalid"
        self.task.pending_action_result = "{invalid"
        self.task.llm_cache_state = "{invalid"

        loaded = self.service.load(self.task)
        self.assertEqual(loaded.messages, [])
        self.assertIsNone(loaded.pending_action_result)
        self.assertIsNone(loaded.previous_response_id)


if __name__ == "__main__":
    unittest.main()
