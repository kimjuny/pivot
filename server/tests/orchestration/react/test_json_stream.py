"""Tests for StreamingFieldExtractor and EmitBuffer."""

from __future__ import annotations

import unittest

from app.orchestration.react.json_stream import (
    EmitBuffer,
    FieldDelta,
    StreamingFieldExtractor,
)


def _feed_all(extractor: StreamingFieldExtractor, text: str) -> list[FieldDelta]:
    """Feed a string one char at a time, collecting all deltas."""
    deltas: list[FieldDelta] = []
    for ch in text:
        deltas.extend(extractor.feed(ch))
    return deltas


def _concat(deltas: list[FieldDelta], field: str) -> str:
    """Concatenate all non-final deltas for a field."""
    return "".join(d.delta for d in deltas if d.field_name == field)


class StreamingFieldExtractorTest(unittest.TestCase):
    def test_single_chunk_complete_field(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, '{"content": "hello"}')
        content_text = _concat(deltas, "content")
        self.assertEqual(content_text, "hello")
        self.assertTrue(any(d.is_final and d.field_name == "content" for d in deltas))

    def test_multi_chunk_incremental_field(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas: list[FieldDelta] = []
        deltas.extend(ex.feed('{"content": "'))
        deltas.extend(ex.feed("hello "))
        deltas.extend(ex.feed("world"))
        deltas.extend(ex.feed('"}'))
        content_text = _concat(deltas, "content")
        self.assertEqual(content_text, "hello world")
        # Should have received multiple non-final deltas.
        non_final = [d for d in deltas if d.field_name == "content" and not d.is_final]
        self.assertGreater(len(non_final), 1)

    def test_unknown_field_skipped(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, '{"path": "ignored", "content": "kept"}')
        # No deltas for path.
        self.assertFalse(any(d.field_name == "path" for d in deltas))
        self.assertEqual(_concat(deltas, "content"), "kept")

    def test_escape_newline(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, r'{"content": "line1\nline2"}')
        self.assertEqual(_concat(deltas, "content"), "line1\nline2")

    def test_escape_quote_and_backslash(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, r'{"content": "a\"b\\c"}')
        self.assertEqual(_concat(deltas, "content"), 'a"b\\c')

    def test_escape_split_across_chunks(self) -> None:
        """Backslash at end of one chunk, escape char at start of next."""
        ex = StreamingFieldExtractor({"content"})
        deltas: list[FieldDelta] = []
        deltas.extend(ex.feed('{"content": "line1'))  # ... ends mid-content
        deltas.extend(ex.feed("\\"))  # lone backslash at end of chunk
        deltas.extend(ex.feed("nline2"))  # escape target arrives next chunk
        deltas.extend(ex.feed('"}'))
        self.assertEqual(_concat(deltas, "content"), "line1\nline2")

    def test_unicode_escape(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, r'{"content": "\u4e2d\u6587"}')
        self.assertEqual(_concat(deltas, "content"), "中文")

    def test_unicode_escape_split_across_chunks(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas: list[FieldDelta] = []
        # Feed \u and hex digits one at a time across multiple feeds.
        deltas.extend(ex.feed('{"content": "'))
        for ch in r"\u4e2d":
            deltas.extend(ex.feed(ch))
        deltas.extend(ex.feed('"}'))
        self.assertEqual(_concat(deltas, "content"), "中")

    def test_two_known_fields(self) -> None:
        ex = StreamingFieldExtractor({"old_string", "new_string"})
        deltas = _feed_all(
            ex,
            r'{"path": "a.py", "old_string": "foo", "new_string": "bar"}',
        )
        self.assertEqual(_concat(deltas, "old_string"), "foo")
        self.assertEqual(_concat(deltas, "new_string"), "bar")

    def test_two_known_fields_incremental(self) -> None:
        ex = StreamingFieldExtractor({"old_string", "new_string"})
        deltas: list[FieldDelta] = []
        deltas.extend(ex.feed('{"old_string": "old'))
        deltas.extend(ex.feed('part1", "new_string": "new'))
        deltas.extend(ex.feed('part2"}'))
        self.assertEqual(_concat(deltas, "old_string"), "oldpart1")
        self.assertEqual(_concat(deltas, "new_string"), "newpart2")

    def test_stream_cut_mid_field_mark_complete_emits_final(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas: list[FieldDelta] = []
        deltas.extend(ex.feed('{"content": "hello '))
        deltas.extend(ex.feed("world"))  # stream ends without closing quote
        deltas.extend(ex.mark_complete())
        self.assertEqual(_concat(deltas, "content"), "hello world")
        self.assertTrue(any(d.is_final and d.field_name == "content" for d in deltas))

    def test_field_does_not_re_enter_after_completion(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(
            ex, '{"content": "first", "other": "x", "content": "second"}'
        )
        # Second "content" should be ignored (already completed).
        self.assertEqual(_concat(deltas, "content"), "first")

    def test_nested_object_answer_field(self) -> None:
        """ANSWER envelope has answer nested in action.output.answer."""
        ex = StreamingFieldExtractor({"answer"})
        deltas = _feed_all(
            ex,
            '{"iteration": 1, "action": {"action_type": "ANSWER", '
            '"output": {"answer": "# Title\n\nbody"}}',
        )
        self.assertEqual(_concat(deltas, "answer"), "# Title\n\nbody")

    def test_empty_field_emits_single_final(self) -> None:
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, '{"content": ""}')
        # Empty field: no non-final deltas, exactly one final delta.
        content_deltas = [d for d in deltas if d.field_name == "content"]
        self.assertEqual(len(content_deltas), 1)
        self.assertTrue(content_deltas[0].is_final)
        self.assertEqual(content_deltas[0].delta, "")

    def test_message_field_extraction(self) -> None:
        """Used by _extract_call_tool_message to pull message from envelope."""
        ex = StreamingFieldExtractor({"message"})
        deltas = _feed_all(ex, '{"iteration": 2, "message": "Reading file", "action": ')
        # Stream cut mid-envelope (truncated JSON).
        self.assertEqual(_concat(deltas, "message"), "Reading file")

    def test_field_name_followed_by_other_string_value(self) -> None:
        """A known field name as a *value* should not trigger extraction.

        e.g. {"x": "content"} -- here "content" is a value, not a field name.
        The extractor should not enter _IN_STRING for it.
        """
        ex = StreamingFieldExtractor({"content"})
        deltas = _feed_all(ex, '{"x": "content", "content": "real"}')
        self.assertEqual(_concat(deltas, "content"), "real")

    def test_large_chunk_batch(self) -> None:
        """Feed the whole JSON in one chunk should still work."""
        ex = StreamingFieldExtractor({"content"})
        big = "x" * 5000
        deltas = ex.feed('{"content": "' + big + '"}')
        self.assertEqual(_concat(deltas, "content"), big)


# ---------------------------------------------------------------------- #
# EmitBuffer tests
# ---------------------------------------------------------------------- #


class EmitBufferTest(unittest.TestCase):
    def test_raw_fragment_accumulates_silently(self) -> None:
        buf = EmitBuffer(interval=0.1)
        self.assertEqual(
            buf.add_tool_payload_delta("c1", "write_file", "hel", 0.0),
            [],
        )
        self.assertEqual(
            buf.add_tool_payload_delta("c1", "write_file", "lo", 0.0),
            [],
        )

    def test_window_flushes_accumulated_raw_fragments(self) -> None:
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_tool_payload_delta("c1", "write_file", "hel", 0.01)
        buf.add_tool_payload_delta("c1", "write_file", "lo", 0.02)
        events = buf.maybe_flush(0.11)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["delta"], "hello")
        self.assertEqual(ev["tool_call_id"], "c1")
        self.assertEqual(ev["tool_name"], "write_file")
        # No is_final key: finalization is the parsed tool_call event's job.
        self.assertNotIn("is_final", ev)

    def test_window_not_elapsed_returns_empty(self) -> None:
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_reasoning_delta("thinking", 0.05)
        self.assertEqual(buf.maybe_flush(0.08), [])

    def test_window_elapsed_flushes_all_buckets(self) -> None:
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_reasoning_delta("think", 0.02)
        buf.add_reasoning_delta(" more", 0.05)
        buf.add_answer_delta("Hello", False, 0.05)
        events = buf.maybe_flush(0.11)
        self.assertEqual(len(events), 2)
        reasoning_ev = next(e for e in events if e["type"] == "reasoning")
        answer_ev = next(e for e in events if e["type"] == "answer_delta")
        self.assertEqual(reasoning_ev["delta"], "think more")
        self.assertEqual(answer_ev["delta"], "Hello")
        self.assertFalse(answer_ev["is_final"])

    def test_separate_buckets_per_tool_call(self) -> None:
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_tool_payload_delta("c1", "edit_file", "foo", 0.01)
        buf.add_tool_payload_delta("c2", "write_file", "baz", 0.03)
        events = buf.maybe_flush(0.11)
        # Two tool calls -> two buckets.
        self.assertEqual(len(events), 2)
        call_ids = sorted(e["tool_call_id"] for e in events)
        self.assertEqual(call_ids, ["c1", "c2"])

    def test_flush_all_emits_remaining(self) -> None:
        """Stream end flushes everything regardless of window."""
        buf = EmitBuffer(interval=0.1)
        buf.add_reasoning_delta("unfinished", 0.0)
        events = buf.flush_all(now=0.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["delta"], "unfinished")

    def test_flushed_buckets_clear_text(self) -> None:
        """After a flush, subsequent deltas start fresh."""
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_reasoning_delta("first", 0.01)
        first = buf.maybe_flush(0.11)
        self.assertEqual(first[0]["delta"], "first")
        buf.add_reasoning_delta("second", 0.12)
        second = buf.maybe_flush(0.22)
        self.assertEqual(second[0]["delta"], "second")

    def test_reasoning_has_no_is_final_field(self) -> None:
        buf = EmitBuffer(interval=0.1)
        buf._last_flush = 0.0
        buf.add_reasoning_delta("text", 0.0)
        events = buf.maybe_flush(0.11)
        self.assertNotIn("is_final", events[0])


if __name__ == "__main__":
    unittest.main()
