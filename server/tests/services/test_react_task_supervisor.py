"""Unit tests for clarify-resume behavior in the ReAct task supervisor."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

Agent = import_module("app.models.agent").Agent
ReactTask = import_module("app.models.react").ReactTask
_should_run_skill_resolution = import_module(
    "app.services.react_task_supervisor"
)._should_run_skill_resolution


class ReactTaskSupervisorTestCase(unittest.TestCase):
    """Validate clarify-resume launch behavior."""

    def test_runs_skill_resolution_for_new_task(self) -> None:
        """Fresh tasks should keep the pre-task skill matcher enabled."""
        agent = Agent(name="agent-1", llm_id=1, skill_resolution_llm_id=2)
        task = ReactTask(
            task_id="task-1",
            agent_id=1,
            user="alice",
            user_message="Help me",
            user_intent="Help me",
            status="pending",
            iteration=0,
        )

        self.assertTrue(_should_run_skill_resolution(task=task, agent=agent))

    def test_skips_skill_resolution_for_waiting_input_resume(self) -> None:
        """Clarify resumes should continue the task instead of matching skills again."""
        agent = Agent(name="agent-1", llm_id=1, skill_resolution_llm_id=2)
        task = ReactTask(
            task_id="task-clarify",
            agent_id=1,
            user="alice",
            user_message="Help me export",
            user_intent="Help me export",
            status="waiting_input",
            iteration=1,
        )

        self.assertFalse(_should_run_skill_resolution(task=task, agent=agent))


if __name__ == "__main__":
    unittest.main()
