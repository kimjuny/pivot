"""Unit tests for strict ReAct parser behavior."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

# The backend code imports from the ``app`` package root. unittest discovery
# does not add ``server/`` to sys.path automatically, so tests do it explicitly.
SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

parse_react_output = import_module("app.orchestration.react.parser").parse_react_output


class ReactParserTestCase(unittest.TestCase):
    """Validate the strict ReAct parser contract."""

    def test_parse_call_tool_with_payload_blocks(self) -> None:
        """CALL_TOOL payload blocks should resolve into typed tool arguments."""
        content = """
{
  "observe": "Need file content",
  "thought": "Call the file tool",
  "abstract": "Read a file",
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "step_id": "1",
    "step_status_update": [
      {"step_id": "1", "status": "RUNNING"}
    ],
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"},
            "options": {"$payload_ref": "options_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"/tmp/demo.txt"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:options_payload:BEGIN_6F2D9C1A>>>
{"encoding":"utf-8"}
<<<PIVOT_PAYLOAD:options_payload:END_6F2D9C1A>>>
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "CALL_TOOL")
        self.assertEqual(decision.summary, "Reading the requested file")
        self.assertEqual(decision.action.step_id, "1")
        self.assertEqual(len(decision.action.tool_calls), 1)
        self.assertEqual(
            decision.action.tool_calls[0].arguments,
            {
                "path": "/tmp/demo.txt",
                "options": {"encoding": "utf-8"},
            },
        )
        self.assertEqual(
            [item.to_dict() for item in decision.action.step_status_update],
            [{"step_id": "1", "status": "running"}],
        )

    def test_reject_legacy_top_level_step_status_update(self) -> None:
        """Legacy step-status locations should now fail fast."""
        content = """
{
  "step_status_update": [{"step_id": "1", "status": "done"}],
  "action": {
    "action_type": "REFLECT",
    "output": {}
  }
}
""".strip()

        with self.assertRaisesRegex(
            ValueError,
            "step_status_update is only allowed under action",
        ):
            parse_react_output(content)

    def test_reject_non_object_tool_arguments(self) -> None:
        """CALL_TOOL arguments must be objects before payload resolution."""
        content = """
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": "not-an-object"
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:any_payload:BEGIN_6F2D9C1A>>>
"unused"
<<<PIVOT_PAYLOAD:any_payload:END_6F2D9C1A>>>
""".strip()

        with self.assertRaisesRegex(
            ValueError,
            r"action\.output\.tool_calls\[0\]\.arguments must be an object",
        ):
            parse_react_output(content)

    def test_reject_non_list_action_step_status_update(self) -> None:
        """Step updates must use the canonical list form."""
        content = """
{
  "action": {
    "action_type": "RE_PLAN",
    "step_status_update": {"step_id": "1", "status": "done"},
    "output": {
      "plan": []
    }
  }
}
""".strip()

        with self.assertRaisesRegex(
            ValueError,
            r"action\.step_status_update must be a list",
        ):
            parse_react_output(content)


if __name__ == "__main__":
    unittest.main()
