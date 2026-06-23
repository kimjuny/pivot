"""Streaming extraction of known string fields from an incomplete JSON stream.

This module provides :class:`StreamingFieldExtractor`, a tiny state machine
that scans an incrementally-arriving JSON text buffer *character by
character* and emits field-internal deltas the moment they decode.  It is:

* **Incremental** -- each chunk only processes its own characters plus at
  most a tiny carry-over for escape-sequence boundaries.  Total cost is
  O(N) in the whole stream.
* **Schema-aware** -- the caller passes the set of string field names it
  cares about; everything else is skipped over without copying.
* **Decoupled from structural validation** -- it does not verify JSON
  well-formedness.  Final validation is still done by ``json.loads`` after
  the stream closes.

The extractor handles JSON string escapes (``\\n``, ``\\\"``, ``\\\\``,
``\\uXXXX`` ...) on the fly, so every emitted ``delta`` is already-unescaped
plain text.

Backend usage is limited to extracting the ``answer`` field from the
ANSWER envelope and the ``message`` field from the CALL_TOOL envelope.
Field-level extraction of tool-call arguments (``content`` / ``diff`` /
``old_string`` / ``new_string``) has moved to the frontend: the backend
forwards the raw ``arguments`` JSON fragments verbatim via
``tool_payload_delta`` events, and a TypeScript twin of this extractor runs
in the browser to surface those fields for live +/- line rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FieldDelta:
    """One emitted fragment for a known string field.

    ``is_final=True`` is emitted exactly once per field, when its closing
    quote is seen in the stream (or on :meth:`mark_complete` if the stream
    ends mid-field).  Before that, zero or more ``is_final=False`` deltas
    carry the incrementally-decoded content.
    """

    field_name: str
    delta: str
    is_final: bool


# Scanner states.
_SCANNING = 0  # outside any string, looking for the next `"`
_READING_NAME = 1  # between the quotes of a potential field name
_AFTER_NAME = 2  # saw closing quote of name; expecting `:` (then opening quote)
_IN_STRING = 3  # inside a *known* string field, decoding
_IN_OTHER_STRING = 4  # inside a string we don't care about

# Single-char escapes (the char after `\`).
_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
}


@dataclass(slots=True)
class StreamingFieldExtractor:
    """Incrementally extract known string fields from a JSON text stream.

    Typical usage::

        extractor = StreamingFieldExtractor({"content", "diff"})
        for chunk in llm_stream:
            for delta in extractor.feed(chunk):
                await emit(delta)
        for delta in extractor.mark_complete():
            await emit(delta)
    """

    field_names: set[str]
    _state: int = field(default=_SCANNING)
    # Buffer while reading a candidate field name (between the opening `"`
    # and its closing `"`).
    _name_buf: str = field(default="")
    # The field currently being extracted once we enter _IN_STRING.
    _current_field: str = field(default="")
    # True when the previous char was an unescaped backslash inside a string.
    _escape_pending: bool = field(default=False)
    # Buffer for an in-progress `\uXXXX` sequence (the 4 hex digits).
    _unicode_buf: str = field(default="")
    # True while collecting `\u` hex digits (supersedes _escape_pending).
    _unicode_pending: bool = field(default=False)
    # Fields whose closing quote has been seen (so we don't re-enter them).
    _completed_fields: set[str] = field(default_factory=set)
    # Most recently closed field name (used in _AFTER_NAME to decide whether
    # the *next* string is the field's value).
    _pending_field_for_value: str = field(default="")
    # In _AFTER_NAME: have we seen the `:` separator yet?
    _after_name_seen_colon: bool = field(default=False)

    def feed(self, chunk: str) -> list[FieldDelta]:
        """Consume one stream chunk; return deltas decoded from it."""
        if not chunk:
            return []
        deltas: list[FieldDelta] = []
        for ch in chunk:
            self._consume(ch, deltas)
        return deltas

    def mark_complete(self) -> list[FieldDelta]:
        """Flush trailing state when the stream has ended.

        If we were mid-field (stream cut off before the closing quote), emit
        a final ``is_final=True`` delta so the frontend can settle the field.
        """
        deltas: list[FieldDelta] = []
        if self._state == _IN_STRING and self._current_field:
            field_name = self._current_field
            self._completed_fields.add(field_name)
            self._current_field = ""
            self._state = _SCANNING
            deltas.append(FieldDelta(field_name=field_name, delta="", is_final=True))
        # Discard any half-read name: the stream ended before the field's
        # opening quote, so there is nothing to emit.
        self._name_buf = ""
        self._pending_field_for_value = ""
        self._after_name_seen_colon = False
        return deltas

    # ------------------------------------------------------------------ #
    # Internal character-level consumer.
    # ------------------------------------------------------------------ #

    def _consume(self, ch: str, deltas: list[FieldDelta]) -> None:
        state = self._state
        if state == _IN_STRING:
            self._consume_in_string(ch, deltas)
        elif state == _IN_OTHER_STRING:
            self._consume_in_other_string(ch)
        elif state == _READING_NAME:
            self._consume_reading_name(ch)
        elif state == _AFTER_NAME:
            self._consume_after_name(ch)
        else:  # _SCANNING
            self._consume_scanning(ch)

    def _consume_scanning(self, ch: str) -> None:
        # We're outside any string.  Only `"` is interesting: it could open
        # a field name.  Everything else (braces, colons, commas, digits,
        # whitespace) is structural noise we ignore.
        if ch == '"':
            self._name_buf = ""
            self._state = _READING_NAME

    def _consume_reading_name(self, ch: str) -> None:
        # We're between the quotes of a candidate field name.
        if ch == '"':
            # Name closed.  Decide whether it's one we care about.
            name = self._name_buf
            self._name_buf = ""
            if name in self.field_names and name not in self._completed_fields:
                # Tentatively remember it; commit only when we see the `:`
                # separator (a string value followed by `,` or `}` is not a
                # field name and must not trigger extraction).
                self._pending_field_for_value = name
                self._after_name_seen_colon = False
                self._state = _AFTER_NAME
            else:
                # Not a field we track (or already completed).  Its value
                # string (if any) will be skipped by _IN_OTHER_STRING.
                self._pending_field_for_value = ""
                self._state = _SCANNING
        else:
            self._name_buf += ch

    def _consume_after_name(self, ch: str) -> None:
        # We just closed a candidate field name.  We need a `:` before the
        # next `"` to be sure this really was a field name (not a string
        # value that happened to match a known name).
        if ch == ":":
            self._after_name_seen_colon = True
            return
        if ch == '"':
            if self._after_name_seen_colon:
                # Opening quote of the value string -- commit.
                self._current_field = self._pending_field_for_value
                self._pending_field_for_value = ""
                self._after_name_seen_colon = False
                self._state = _IN_STRING
            else:
                # No `:` seen -- the matched name was actually a string value.
                # Treat this `"` as opening an other-string we skip.
                self._pending_field_for_value = ""
                self._after_name_seen_colon = False
                self._state = _IN_OTHER_STRING
            return
        # Whitespace, commas, braces: ignore.  But if we see a non-`:`
        # structural char before any `:`, the candidate wasn't a field name;
        # cancel to avoid mis-extracting.
        if not self._after_name_seen_colon and ch in ",{}[]":
            self._pending_field_for_value = ""
            self._state = _SCANNING

    def _consume_in_other_string(self, ch: str) -> None:
        # Inside a string whose field we don't track.  We only need to detect
        # its closing quote (respecting escapes) so we can return to scanning.
        if self._unicode_pending:
            self._unicode_buf += ch
            if len(self._unicode_buf) >= 4:
                self._unicode_buf = ""
                self._unicode_pending = False
            return
        if self._escape_pending:
            self._escape_pending = False
            if ch == "u":
                self._unicode_pending = True
                self._unicode_buf = ""
            return
        if ch == "\\":
            self._escape_pending = True
            return
        if ch == '"':
            self._state = _SCANNING

    def _consume_in_string(self, ch: str, deltas: list[FieldDelta]) -> None:
        field_name = self._current_field
        # Continue an in-progress `\uXXXX`.
        if self._unicode_pending:
            self._unicode_buf += ch
            if len(self._unicode_buf) >= 4:
                code = _safe_hex(self._unicode_buf)
                self._unicode_buf = ""
                self._unicode_pending = False
                if code is not None:
                    deltas.append(
                        FieldDelta(
                            field_name=field_name,
                            delta=chr(code),
                            is_final=False,
                        )
                    )
            return
        if self._escape_pending:
            self._escape_pending = False
            simple = _SIMPLE_ESCAPES.get(ch)
            if simple is not None:
                deltas.append(
                    FieldDelta(field_name=field_name, delta=simple, is_final=False)
                )
            elif ch == "u":
                self._unicode_pending = True
                self._unicode_buf = ""
            # Unknown escape: drop silently (JSON disallows it anyway).
            return
        if ch == "\\":
            self._escape_pending = True
            return
        if ch == '"':
            # Field closed.
            self._completed_fields.add(field_name)
            self._current_field = ""
            self._state = _SCANNING
            deltas.append(FieldDelta(field_name=field_name, delta="", is_final=True))
            return
        # Regular character: emit as-is.
        deltas.append(FieldDelta(field_name=field_name, delta=ch, is_final=False))


def _safe_hex(text: str) -> int | None:
    try:
        return int(text, 16)
    except ValueError:
        return None


# ---------------------------------------------------------------------- #
# Emit coalescing buffer for high-frequency streaming-content events.
# ---------------------------------------------------------------------- #
#
# The extractor yields one delta per character (~132/sec for a typical LLM
# stream).  Pushing every delta straight onto the SSE queue floods the
# frontend (10000+ events for a single write_file) and freezes the UI.
# This buffer accumulates deltas per (event-type, identity) bucket and only
# produces a merged event when either:
#   * the time window elapses (``maybe_flush``), or
#   * a field-final delta arrives (flushed immediately so users see instant
#     "write complete" feedback), or
#   * the stream ends (``flush_all``).
#
# Only "streaming content" events are buffered (tool_payload_delta /
# answer_delta / reasoning).  Discrete events (tool_call / action /
# tool_result / token_rate) are never fed to this buffer; they are emitted
# directly by the engine.


@dataclass(slots=True)
class _Bucket:
    """Accumulated text + event-builder for one stream, awaiting flush."""

    text: str = ""
    # Frozen event template (without the ``delta``/``is_final`` fields, which
    # are filled at flush time).  Storing the full context per bucket means
    # ``maybe_flush`` / ``flush_all`` can emit well-formed events without
    # needing to reconstruct tool_call_id / tool_name / field_name.
    template: dict[str, Any] = field(default_factory=dict)
    # True for events that carry an ``is_final`` flag (tool_payload_delta,
    # answer_delta); False for reasoning (no final signal).
    has_final: bool = False


@dataclass(slots=True)
class EmitBuffer:
    """Coalesces high-frequency streaming-content events.

    Three event families share one time window.  Each family is keyed by an
    identity string so independent streams don't merge:

    * ``tool_payload_delta`` -- identity is ``tool_call_id`` (raw args JSON
      fragments for one tool call are merged into one growing delta)
    * ``answer_delta``       -- single bucket (identity ``""``)
    * ``reasoning``          -- single bucket (identity ``""``)

    Usage::

        buf = EmitBuffer(interval=0.1)
        for chunk in llm_stream:
            for ev in buf.add_tool_payload_delta(
                call_id, name, raw_args_fragment, now
            ):
                await queue.put(ev)
            for ev in buf.maybe_flush(now):
                await queue.put(ev)
        for ev in buf.flush_all():
            await queue.put(ev)
    """

    interval: float
    _buckets: dict[tuple[str, str], _Bucket] = field(default_factory=dict)
    _last_flush: float = field(default=0.0)

    # ------------------------------------------------------------------ #
    # Producers.  Each returns a list of events to emit immediately.
    # ------------------------------------------------------------------ #

    def add_tool_payload_delta(
        self,
        tool_call_id: str,
        tool_name: str,
        delta_text: str,
        now: float,
    ) -> list[dict[str, object]]:
        """Accumulate one raw-arguments fragment for a tool call.

        The frontend appends ``delta`` to its own per-call raw-arguments
        buffer and runs a local field extractor to surface ``content`` /
        ``diff`` / etc.  There is no ``is_final`` signal: the stream is
        considered finalised when the parsed ``tool_call`` event arrives
        with the complete ``arguments`` dict.
        """
        key = ("tool_payload_delta", tool_call_id)
        template = {
            "type": "tool_payload_delta",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
        }
        return self._add(
            key=key,
            delta_text=delta_text,
            is_final=False,
            template=template,
            has_final=False,
        )

    def add_answer_delta(
        self, delta_text: str, is_final: bool, now: float
    ) -> list[dict[str, object]]:
        """Accumulate (or flush on final) one answer_delta fragment."""
        key = ("answer_delta", "")
        return self._add(
            key=key,
            delta_text=delta_text,
            is_final=is_final,
            template={"type": "answer_delta"},
            has_final=True,
        )

    def add_reasoning_delta(
        self, delta_text: str, now: float
    ) -> list[dict[str, object]]:
        """Accumulate one reasoning fragment (reasoning has no final signal)."""
        key = ("reasoning", "")
        template: dict[str, object] = {"type": "reasoning"}
        return self._add(
            key=key,
            delta_text=delta_text,
            is_final=False,
            template=template,
            has_final=False,
        )

    # ------------------------------------------------------------------ #
    # Flush triggers.
    # ------------------------------------------------------------------ #

    def maybe_flush(self, now: float) -> list[dict[str, object]]:
        """Flush every non-empty bucket if the window has elapsed.

        Returns merged events for all flushed buckets (empty list if the
        window has not elapsed yet or all buckets are empty).
        """
        if now - self._last_flush < self.interval:
            return []
        return self._flush_all_buckets(now)

    def flush_all(self, now: float = 0.0) -> list[dict[str, object]]:
        """Flush every non-empty bucket unconditionally (stream-end use)."""
        return self._flush_all_buckets(now)

    # ------------------------------------------------------------------ #
    # Internals.
    # ------------------------------------------------------------------ #

    def _add(
        self,
        *,
        key: tuple[str, str],
        delta_text: str,
        is_final: bool,
        template: dict[str, Any],
        has_final: bool,
    ) -> list[dict[str, object]]:
        """Core accumulation logic shared by all producers.

        On ``is_final`` the bucket's accumulated text is merged with this
        final fragment and a single ``is_final=True`` event is returned
        immediately (the bucket is then discarded).  Otherwise the fragment
        is appended to the bucket and nothing is returned yet.
        """
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(template=dict(template), has_final=has_final)
            self._buckets[key] = bucket
        if is_final:
            merged = bucket.text + delta_text
            self._buckets.pop(key, None)
            event = dict(bucket.template)
            event["delta"] = merged
            if bucket.has_final:
                event["is_final"] = True
            return [event]
        bucket.text += delta_text
        return []

    def _flush_all_buckets(self, now: float) -> list[dict[str, object]]:
        """Emit one merged non-final event per non-empty bucket, then clear."""
        if not self._buckets:
            return []
        events: list[dict[str, object]] = []
        for _key, bucket in self._buckets.items():
            if not bucket.text:
                continue
            event = dict(bucket.template)
            event["delta"] = bucket.text
            if bucket.has_final:
                event["is_final"] = False
            events.append(event)
            bucket.text = ""
        self._last_flush = now
        return events
