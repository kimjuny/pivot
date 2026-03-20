"""Helpers for normalizing provider token-usage reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .abstract_llm import UsageInfo

TOKEN_USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_input_tokens",
)


def _empty_token_counter() -> dict[str, int]:
    """Create a zeroed token counter dictionary.

    Returns:
        A token counter with all known usage fields initialized to zero.
    """
    return {field: 0 for field in TOKEN_USAGE_FIELDS}


def _coerce_usage_value(usage: Any, field_name: str) -> int:
    """Read one usage field from dict-like or object-like payloads.

    Args:
        usage: Provider usage payload or `UsageInfo`.
        field_name: Normalized token field to extract.

    Returns:
        A non-negative integer token count.
    """
    if usage is None:
        return 0

    raw_value = (
        usage.get(field_name, 0)
        if isinstance(usage, dict)
        else getattr(usage, field_name, 0)
    )
    try:
        return max(int(raw_value or 0), 0)
    except (TypeError, ValueError):
        return 0


def usage_to_token_counter(usage: Any | None) -> dict[str, int]:
    """Normalize provider usage payloads into a token counter.

    Args:
        usage: Provider usage payload or `UsageInfo`.

    Returns:
        A normalized token counter dictionary.
    """
    return {
        field_name: _coerce_usage_value(usage, field_name)
        for field_name in TOKEN_USAGE_FIELDS
    }


@dataclass
class StreamingUsageAccumulator:
    """Normalize usage chunks reported during one streaming LLM request.

    Different providers use different semantics for chunk-level `usage`:

    - Some emit a single terminal usage payload.
    - Some repeat cumulative snapshots on multiple chunks.
    - A few may emit per-event deltas.

    This accumulator records both the additive interpretation and the
    monotonic-snapshot interpretation, then resolves to the safest final tally
    at the end of the stream.
    """

    _snapshot_count: int = 0
    _monotonic_snapshots: bool = True
    _last_snapshot: dict[str, int] = field(default_factory=_empty_token_counter)
    _max_snapshot: dict[str, int] = field(default_factory=_empty_token_counter)
    _additive_total: dict[str, int] = field(default_factory=_empty_token_counter)

    def observe(self, usage: Any | None) -> None:
        """Record one provider usage payload seen during streaming.

        Args:
            usage: Provider usage payload for the current stream chunk.
        """
        token_counter = usage_to_token_counter(usage)
        if all(value == 0 for value in token_counter.values()):
            return

        self._snapshot_count += 1
        for field_name in TOKEN_USAGE_FIELDS:
            field_value = token_counter[field_name]
            self._additive_total[field_name] += field_value
            self._max_snapshot[field_name] = max(
                self._max_snapshot[field_name],
                field_value,
            )
            if field_value < self._last_snapshot[field_name]:
                self._monotonic_snapshots = False

        self._last_snapshot = token_counter

    def build_token_counter(self) -> dict[str, int]:
        """Resolve the final usage tally for the completed stream.

        Returns:
            A normalized token counter for the stream.
        """
        if self._snapshot_count == 0:
            return _empty_token_counter()

        if self._snapshot_count == 1 or self._monotonic_snapshots:
            return dict(self._max_snapshot)
        return dict(self._additive_total)

    def build_usage_info(self) -> UsageInfo | None:
        """Convert the resolved tally into `UsageInfo` when non-empty.

        Returns:
            A `UsageInfo` instance, or `None` if the stream never reported usage.
        """
        token_counter = self.build_token_counter()
        if all(value == 0 for value in token_counter.values()):
            return None

        return UsageInfo(
            prompt_tokens=token_counter["prompt_tokens"],
            completion_tokens=token_counter["completion_tokens"],
            total_tokens=token_counter["total_tokens"],
            cached_input_tokens=token_counter["cached_input_tokens"],
        )
