"""Unit tests for strict ReAct parser behavior."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

# The backend code imports from the ``app`` package root. unittest discovery
# does not add ``server/`` to sys.path automatically, so tests do it explicitly.
SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

react_parser = import_module("app.orchestration.react.parser")
parse_react_output = react_parser.parse_react_output
parse_react_control_section = react_parser.parse_react_control_section
collect_complete_payload_blocks = react_parser.collect_complete_payload_blocks
resolve_tool_call_payloads = react_parser.resolve_tool_call_payloads
ToolCallRequest = import_module("app.orchestration.react.types").ToolCallRequest


class _StubToolManager:
    """Minimal tool manager stub for schema-aware payload decoding tests."""

    def __init__(self, tool_schemas: dict[str, dict[str, object]]) -> None:
        self._tool_schemas = tool_schemas

    def get_tool(self, name: str) -> object | None:
        parameters = self._tool_schemas.get(name)
        if parameters is None:
            return None
        return SimpleNamespace(parameters=parameters)


class ReactParserTestCase(unittest.TestCase):
    """Validate the strict ReAct parser contract."""

    def test_parse_call_tool_with_payload_blocks(self) -> None:
        """CALL_TOOL payload blocks should resolve into typed tool arguments."""
        content = """
{
  "observe": "Need file content",
  "reason": "Call the file tool",
  "summary": "Reading the requested file",
  "thinking_next_turn": true,
  "session_title": "Read demo file",
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
          "batch": 2,
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
        self.assertIs(decision.thinking_next_turn, True)
        self.assertEqual(decision.session_title, "Read demo file")
        self.assertEqual(decision.action.step_id, "1")
        self.assertEqual(len(decision.action.tool_calls), 1)
        self.assertEqual(decision.action.tool_calls[0].batch, 2)
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

    def test_parse_call_tool_tolerates_payload_markdown_fence(self) -> None:
        """A mistaken ```text wrapper around payload blocks should be stripped."""
        content = """
{
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "batch": 1,
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
```text
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"/tmp/demo.txt"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
```
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.action_type, "CALL_TOOL")
        self.assertEqual(
            decision.action.tool_calls[0].arguments,
            {"path": "/tmp/demo.txt"},
        )

    def test_parse_control_section_keeps_payload_refs_for_stream_preview(self) -> None:
        """Early control parsing should not require completed payload bodies."""
        content = """
{
  "observe": "Need file content",
  "reason": "Call the file tool",
  "summary": "Reading the requested file",
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "batch": 1,
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
""".strip()

        decision = parse_react_control_section(content)

        self.assertEqual(decision.summary, "Reading the requested file")
        self.assertEqual(decision.action.action_type, "CALL_TOOL")
        self.assertEqual(
            decision.action.tool_calls[0].arguments,
            {"path": {"$payload_ref": "path_payload"}},
        )
        self.assertEqual(decision.action.tool_calls[0].batch, 1)

    def test_collect_complete_payload_blocks_ignores_incomplete_tail(self) -> None:
        """Streaming payload collection should return only closed blocks."""
        content = """
{"action":{"action_type":"CALL_TOOL","output":{"tool_calls":[]}}}
<<<PIVOT_PAYLOAD:ready_payload:BEGIN_6F2D9C1A>>>
"ready"
<<<PIVOT_PAYLOAD:ready_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:pending_payload:BEGIN_6F2D9C1A>>>
"pending
""".strip()

        self.assertEqual(
            collect_complete_payload_blocks(content),
            {"ready_payload": '"ready"'},
        )

    def test_resolve_single_tool_call_payloads(self) -> None:
        """One preview call can be resolved without parsing the whole response."""
        tool_call = ToolCallRequest(
            id="call-1",
            name="read_file",
            batch=3,
            arguments={"path": {"$payload_ref": "path_payload"}},
        )
        tool_manager = _StubToolManager(
            {"read_file": {"properties": {"path": {"type": "string"}}}}
        )

        resolved = resolve_tool_call_payloads(
            tool_call,
            {"path_payload": '"README.md"'},
            tool_manager=tool_manager,
        )

        self.assertEqual(resolved.id, "call-1")
        self.assertEqual(resolved.batch, 3)
        self.assertEqual(resolved.arguments, {"path": "README.md"})

    def test_parse_call_tool_defaults_batch_to_one(self) -> None:
        """CALL_TOOL batch remains optional for compatibility and defaults to one."""
        content = """
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.action.tool_calls[0].batch, 1)
        self.assertEqual(
            decision.action.tool_calls[0].to_dict(),
            {
                "id": "call-1",
                "name": "read_file",
                "batch": 1,
                "arguments": {"path": "README.md"},
            },
        )

    def test_reject_invalid_tool_call_batch(self) -> None:
        """CALL_TOOL batch must be a positive integer, not bool or string."""
        invalid_batches = [
            ("0", 0),
            ("negative", -1),
            ("bool", True),
            ("string", "1"),
        ]

        for _label, invalid_batch in invalid_batches:
            batch_json = (
                f'"{invalid_batch}"'
                if isinstance(invalid_batch, str)
                else json.dumps(invalid_batch)
            )
            content = f"""
{{
  "action": {{
    "action_type": "CALL_TOOL",
    "output": {{
      "tool_calls": [
        {{
          "id": "call-1",
          "name": "read_file",
          "batch": {batch_json},
          "arguments": {{
            "path": {{"$payload_ref": "path_payload"}}
          }}
        }}
      ]
    }}
  }}
}}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
""".strip()

            with (
                self.subTest(invalid_batch=invalid_batch),
                self.assertRaisesRegex(
                    ValueError,
                    r"action\.output\.tool_calls\[0\]\.batch must be a positive integer",
                ),
            ):
                parse_react_output(content)

    def test_reject_duplicate_tool_call_id(self) -> None:
        """CALL_TOOL ids must be unique within one recursion."""
        content = """
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"}
          }
        },
        {
          "id": "call-1",
          "name": "read_file",
          "arguments": {
            "path": {"$payload_ref": "other_path_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"README.md"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:other_path_payload:BEGIN_6F2D9C1A>>>
"package.json"
<<<PIVOT_PAYLOAD:other_path_payload:END_6F2D9C1A>>>
""".strip()

        with self.assertRaisesRegex(ValueError, "Duplicate tool_call id: call-1"):
            parse_react_output(content)

    def test_normalizes_legacy_top_level_step_status_update(self) -> None:
        """Top-level step-status drift should normalize into action."""
        content = """
{
  "step_status_update": [{"step_id": "1", "status": "done"}],
  "action": {
    "action_type": "REFLECT",
    "output": {}
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(
            [item.to_dict() for item in decision.action.step_status_update],
            [{"step_id": "1", "status": "done"}],
        )
        self.assertNotIn("step_status_update", decision.raw_payload)

    def test_normalizes_action_output_step_status_update(self) -> None:
        """action.output step-status drift should normalize into action."""
        content = """
{
  "action": {
    "action_type": "RE_PLAN",
    "output": {
      "step_status_update": [{"step_id": "2", "status": "running"}],
      "plan": []
    }
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(
            [item.to_dict() for item in decision.action.step_status_update],
            [{"step_id": "2", "status": "running"}],
        )
        self.assertNotIn("step_status_update", decision.action.output)

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

    def test_reject_non_boolean_thinking_next_turn(self) -> None:
        """thinking_next_turn must be a boolean when present."""
        content = """
{
  "thinking_next_turn": "yes",
  "action": {
    "action_type": "REFLECT",
    "output": {}
  }
}
""".strip()

        with self.assertRaisesRegex(
            ValueError,
            "thinking_next_turn must be a boolean",
        ):
            parse_react_output(content)

    def test_parse_missing_observe_and_reason_as_empty_strings(self) -> None:
        """Missing observe/reason should stay parseable and normalize to empty strings."""
        content = """
{
  "summary": "Proceeding without extra trace text",
  "action": {
    "action_type": "REFLECT",
    "output": {}
  }
}
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(decision.observe, "")
        self.assertEqual(decision.reason, "")
        self.assertEqual(decision.summary, "Proceeding without extra trace text")
        self.assertEqual(decision.action.action_type, "REFLECT")

    def test_raw_string_payload_strips_block_terminator_newline(self) -> None:
        """Raw string payloads should not inherit the formatting newline before END."""
        content = """
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "edit_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"},
            "old_string": {"$payload_ref": "old_payload"},
            "new_string": {"$payload_ref": "new_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"/workspace/example.txt"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:old_payload:BEGIN_6F2D9C1A>>>
export default App;
<<<PIVOT_PAYLOAD:old_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:new_payload:BEGIN_6F2D9C1A>>>

<<<PIVOT_PAYLOAD:new_payload:END_6F2D9C1A>>>
""".strip()

        decision = parse_react_output(content)

        self.assertEqual(
            decision.action.tool_calls[0].arguments["old_string"],
            "export default App;",
        )
        self.assertEqual(decision.action.tool_calls[0].arguments["new_string"], "")

    def test_string_tool_argument_keeps_json_like_payload_as_text(self) -> None:
        """String parameters should keep JSON-looking payloads as raw text."""
        content = """
{
  "action": {
    "action_type": "CALL_TOOL",
    "output": {
      "tool_calls": [
        {
          "id": "call-1",
          "name": "write_file",
          "arguments": {
            "path": {"$payload_ref": "path_payload"},
            "content": {"$payload_ref": "content_payload"}
          }
        }
      ]
    }
  }
}
<<<PIVOT_PAYLOAD:path_payload:BEGIN_6F2D9C1A>>>
"/workspace/survey-app/package.json"
<<<PIVOT_PAYLOAD:path_payload:END_6F2D9C1A>>>
<<<PIVOT_PAYLOAD:content_payload:BEGIN_6F2D9C1A>>>
{
  "name": "xiangan-survey",
  "private": true,
  "version": "1.0.0"
}
<<<PIVOT_PAYLOAD:content_payload:END_6F2D9C1A>>>
""".strip()
        tool_manager = _StubToolManager(
            {
                "write_file": {
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    }
                }
            }
        )

        decision = parse_react_output(content, tool_manager=tool_manager)

        self.assertEqual(
            decision.action.tool_calls[0].arguments,
            {
                "path": "/workspace/survey-app/package.json",
                "content": (
                    "{\n"
                    '  "name": "xiangan-survey",\n'
                    '  "private": true,\n'
                    '  "version": "1.0.0"\n'
                    "}"
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
