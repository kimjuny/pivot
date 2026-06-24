"""Unified prompt-window usage estimation for chat UI and compaction."""

from __future__ import annotations

from typing import Any

from app.llm.token_estimator import estimate_messages_tokens, estimate_tools_tokens


class ReactPromptUsageService:
    """Compute runtime and preview prompt occupancy with one shared algorithm."""

    @staticmethod
    def estimate_runtime_tokens(
        *,
        messages: list[dict[str, Any]],
        exact_prompt_tokens: int | None,
        exact_prompt_message_count: int | None,
    ) -> int:
        """Estimate current runtime occupancy from a persisted exact baseline."""
        if (
            isinstance(exact_prompt_tokens, int)
            and exact_prompt_tokens > 0
            and isinstance(exact_prompt_message_count, int)
            and 0 <= exact_prompt_message_count <= len(messages)
        ):
            delta_tokens = estimate_messages_tokens(
                messages[exact_prompt_message_count:]
            )
            return exact_prompt_tokens + delta_tokens
        return estimate_messages_tokens(messages)

    @staticmethod
    def build_usage_summary(
        *,
        task_id: str | None,
        session_id: str | None,
        estimation_mode: str,
        messages: list[dict[str, Any]],
        max_context_tokens: int,
        exact_prompt_tokens: int | None = None,
        exact_prompt_message_count: int | None = None,
        preview_messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        bootstrap_tokens: int = 0,
        draft_tokens: int = 0,
        includes_task_bootstrap: bool = False,
        cache_hit_rate: int | None = None,
    ) -> dict[str, Any]:
        """Build one normalized context-usage payload."""
        runtime_tokens = ReactPromptUsageService.estimate_runtime_tokens(
            messages=messages,
            exact_prompt_tokens=exact_prompt_tokens,
            exact_prompt_message_count=exact_prompt_message_count,
        )
        preview_message_list = preview_messages or []
        preview_tokens = estimate_messages_tokens(preview_message_list)
        # Tool/function definitions are passed to the provider via ``tools``
        # (separate from messages) but still occupy context window; count them
        # so used_tokens reflects the real prompt footprint.
        tools_tokens = estimate_tools_tokens(tools or [])
        used_tokens = runtime_tokens + preview_tokens + tools_tokens
        remaining_tokens = max(max_context_tokens - used_tokens, 0)
        used_percent = ReactPromptUsageService._to_percent(
            used_tokens,
            max_context_tokens,
        )
        system_tokens = 0
        combined_messages = [*messages, *preview_message_list]
        if combined_messages and combined_messages[0].get("role") == "system":
            system_tokens = estimate_messages_tokens([combined_messages[0]])

        return {
            "task_id": task_id,
            "session_id": session_id,
            "estimation_mode": estimation_mode,
            "message_count": len(messages) + len(preview_message_list),
            "session_message_count": len(messages),
            "used_tokens": used_tokens,
            "remaining_tokens": remaining_tokens,
            "max_context_tokens": max_context_tokens,
            "used_percent": used_percent,
            "remaining_percent": max(100 - used_percent, 0),
            "system_tokens": system_tokens,
            "conversation_tokens": max(used_tokens - system_tokens - tools_tokens, 0),
            "session_tokens": runtime_tokens,
            "preview_tokens": preview_tokens,
            "tools_tokens": tools_tokens,
            "bootstrap_tokens": bootstrap_tokens,
            "draft_tokens": draft_tokens,
            "includes_task_bootstrap": includes_task_bootstrap,
            "cache_hit_rate": cache_hit_rate,
        }

    @staticmethod
    def _to_percent(used_tokens: int, max_context_tokens: int) -> int:
        """Convert token counts into a bounded integer percentage."""
        if max_context_tokens <= 0:
            return 0
        raw_percent = round((used_tokens / max_context_tokens) * 100)
        return max(min(int(raw_percent), 100), 0)
