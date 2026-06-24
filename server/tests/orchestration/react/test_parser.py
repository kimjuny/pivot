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

react_parser = import_module("app.orchestration.react.parser")
parse_react_output = react_parser.parse_react_output
safe_load_json = react_parser.safe_load_json


class ReactParserTestCase(unittest.TestCase):
    """Validate the strict ReAct parser contract."""

    def test_parse_call_tool(self) -> None:
        """A minimal CALL_TOOL decision should parse into a typed decision."""
        content = """
{
  "message": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {}
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "CALL_TOOL")
        self.assertEqual(decision.message, "Reading the requested file")
        self.assertEqual(decision.action.output, {})

    def test_parse_answer(self) -> None:
        """An ANSWER decision should expose the answer body in action.output."""
        content = """
{
  "message": "Task complete",
  "action": {
    "action_type": "ANSWER",
    "output": {
      "answer": "# Final Answer\\n\\nEverything is ready.",
      "attachments": []
    }
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "ANSWER")
        self.assertEqual(
            decision.action.output["answer"],
            "# Final Answer\n\nEverything is ready.",
        )

    def test_parse_clarify(self) -> None:
        """A CLARIFY decision should preserve the question field."""
        content = """
{
  "message": "Need more info",
  "action": {
    "action_type": "CLARIFY",
    "output": {
      "question": "Which file?"
    }
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "CLARIFY")
        self.assertEqual(decision.action.output["question"], "Which file?")

    def test_unknown_fields_are_ignored(self) -> None:
        """Extra envelope fields (e.g. legacy thinking_next_turn) are tolerated."""
        content = """
{
  "message": "ok",
  "thinking_next_turn": true,
  "action": {
    "action_type": "ANSWER",
    "output": {}
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "ANSWER")
        self.assertEqual(decision.message, "ok")

    def test_missing_message_defaults_to_empty(self) -> None:
        """An absent message field normalizes to an empty string."""
        content = """
{
  "action": {
    "action_type": "ANSWER",
    "output": {}
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.message, "")

    def test_reject_invalid_action_type(self) -> None:
        """Unsupported action_type values must raise ValueError."""
        content = """
{
  "action": {
    "action_type": "REFLECT",
    "output": {}
  }
}
""".strip()

        with self.assertRaisesRegex(ValueError, "Unsupported action_type"):
            parse_react_output(content)

    def test_reject_missing_action(self) -> None:
        """A missing action object must raise ValueError."""
        content = """
{
  "message": "no action"
}
""".strip()

        with self.assertRaisesRegex(ValueError, "Missing or invalid action object"):
            parse_react_output(content)

    def test_reject_non_object_action_output(self) -> None:
        """action.output must be an object."""
        content = """
{
  "action": {
    "action_type": "ANSWER",
    "output": "not-an-object"
  }
}
""".strip()

        with self.assertRaisesRegex(
            ValueError, "action.output must be an object"
        ):
            parse_react_output(content)

    def test_reject_non_object_top_level(self) -> None:
        """Top-level payload must be a JSON object."""
        with self.assertRaisesRegex(
            ValueError, "must be a top-level JSON object"
        ):
            parse_react_output("[1, 2, 3]")

    def test_safe_load_json_strips_markdown_fences(self) -> None:
        """Markdown-fenced JSON should be unwrapped before parsing."""
        fenced = '```json\n{"a": 1}\n```'

        self.assertEqual(safe_load_json(fenced), {"a": 1})

    def test_safe_load_json_rejects_invalid_json(self) -> None:
        """Malformed JSON must raise ValueError."""
        with self.assertRaisesRegex(ValueError, "Failed to parse JSON"):
            safe_load_json("{not valid")


if __name__ == "__main__":
    unittest.main()
