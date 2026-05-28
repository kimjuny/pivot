"""Session-level manual compaction helpers for the chat composer."""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.llm.llm_factory import create_llm_from_config
from app.llm.token_estimator import estimate_messages_tokens
from app.orchestration.compact.compact_prompt import build_compact_prompt
from app.orchestration.react.parser import safe_load_json
from app.services.agent_release_runtime_service import AgentReleaseRuntimeService
from app.services.llm_service import LLMService
from app.services.react_runtime_service import ReactRuntimeService
from app.services.session_service import SessionService
from fastapi.concurrency import run_in_threadpool

if TYPE_CHECKING:
    from sqlmodel import Session as DBSession

logger = logging.getLogger(__name__)


class ReactCompactService:
    """Execute one user-triggered compact pass against an idle session runtime."""

    def __init__(self, db: DBSession) -> None:
        """Store the active database session and supporting services."""
        self.db = db
        self.runtime_service = ReactRuntimeService(db)

    async def compact_session(
        self,
        *,
        session_id: str,
        user_instruction: str | None = None,
    ) -> dict[str, Any]:
        """Compact one idle session runtime window with optional user guidance."""
        session = SessionService(self.db).get_session(session_id)
        if session is None:
            raise ValueError("Session not found.")
        if session.runtime_status != "idle":
            raise ValueError(
                "Manual compact is only available when the session is idle."
            )

        runtime_config = AgentReleaseRuntimeService(self.db).resolve_for_session(
            session_id
        )
        if runtime_config.llm_id is None:
            raise ValueError("This agent runtime has no LLM configured for compact.")

        llm_config = LLMService(self.db).get_llm(runtime_config.llm_id)
        if llm_config is None:
            raise ValueError("Configured LLM for this session could not be loaded.")

        max_context_tokens = max(int(llm_config.max_context or 0), 0)
        runtime_state = self.runtime_service.load_session(session_id)
        original_messages = [dict(message) for message in runtime_state.messages]
        usage_before = self._build_usage_snapshot(
            session_id=session_id,
            messages=original_messages,
            max_context_tokens=max_context_tokens,
        )

        if not original_messages:
            return self._build_noop_response(
                session_id=session_id,
                reason="empty_runtime_window",
                usage_before=usage_before,
            )

        system_message = original_messages[0]
        if system_message.get("role") != "system":
            raise ValueError("Session runtime window is missing the system prompt.")

        source_messages = [
            dict(message)
            for message in original_messages
            if message.get("role") != "system"
        ]
        if not source_messages:
            return self._build_noop_response(
                session_id=session_id,
                reason="no_history_to_compact",
                usage_before=usage_before,
            )

        if (
            runtime_state.compact_result is not None
            and len(source_messages) == 1
            and source_messages[0].get("role") == "assistant"
            and source_messages[0].get("content") == runtime_state.compact_result
        ):
            return self._build_noop_response(
                session_id=session_id,
                reason="already_compacted",
                usage_before=usage_before,
            )

        llm = create_llm_from_config(llm_config)
        compact_messages = [dict(message) for message in source_messages]
        compact_messages.append(
            {
                "role": "user",
                "content": build_compact_prompt(user_instruction),
            }
        )
        compact_started_at = perf_counter()
        logger.info(
            "Manual context compact started session_id=%s used_percent=%s "
            "used_tokens=%s max_context_tokens=%s source_messages=%s",
            session_id,
            usage_before.get("used_percent"),
            usage_before.get("used_tokens"),
            usage_before.get("max_context_tokens"),
            len(source_messages),
        )

        try:
            response = await run_in_threadpool(
                llm.chat,
                compact_messages,
                _pivot_task_id=f"manual_compact:{session_id}",
            )
            compact_payload = safe_load_json(response.first().message.content or "{}")
            compact_result = json.dumps(compact_payload, ensure_ascii=False)

            updated_state = self.runtime_service.replace_session_runtime_messages(
                session_id,
                [
                    {
                        "role": "system",
                        "content": str(system_message.get("content", "")),
                    },
                    {"role": "assistant", "content": compact_result},
                ],
                compact_result=compact_result,
                preserve_pending_action_result=True,
                preserve_cache_state=False,
            )
            usage_after = self._build_usage_snapshot(
                session_id=session_id,
                messages=updated_state.messages,
                max_context_tokens=max_context_tokens,
            )
        except Exception:
            logger.exception(
                "Manual context compact failed session_id=%s elapsed_ms=%s",
                session_id,
                round((perf_counter() - compact_started_at) * 1000),
            )
            raise

        logger.info(
            "Manual context compact completed session_id=%s elapsed_ms=%s "
            "used_percent_before=%s used_percent_after=%s "
            "used_tokens_before=%s used_tokens_after=%s",
            session_id,
            round((perf_counter() - compact_started_at) * 1000),
            usage_before.get("used_percent"),
            usage_after.get("used_percent"),
            usage_before.get("used_tokens"),
            usage_after.get("used_tokens"),
        )
        return {
            "session_id": session_id,
            "status": "completed",
            "compacted": True,
            "reason": "manual_request",
            "usage_before": usage_before,
            "usage_after": usage_after,
        }

    @staticmethod
    def _to_percent(used_tokens: int, max_context_tokens: int) -> int:
        """Convert token counts into a bounded integer percentage."""
        if max_context_tokens <= 0:
            return 0
        raw_percent = round((used_tokens / max_context_tokens) * 100)
        return max(min(int(raw_percent), 100), 0)

    def _build_usage_snapshot(
        self,
        *,
        session_id: str,
        messages: list[dict[str, Any]],
        max_context_tokens: int,
    ) -> dict[str, Any]:
        """Build a context-usage payload matching the composer summary shape."""
        used_tokens = estimate_messages_tokens(messages)
        remaining_tokens = max(max_context_tokens - used_tokens, 0)
        used_percent = self._to_percent(used_tokens, max_context_tokens)
        system_tokens = 0
        if messages and messages[0].get("role") == "system":
            system_tokens = estimate_messages_tokens([messages[0]])
        conversation_tokens = max(used_tokens - system_tokens, 0)
        return {
            "task_id": None,
            "session_id": session_id,
            "estimation_mode": "session_runtime",
            "message_count": len(messages),
            "session_message_count": len(messages),
            "used_tokens": used_tokens,
            "remaining_tokens": remaining_tokens,
            "max_context_tokens": max_context_tokens,
            "used_percent": used_percent,
            "remaining_percent": max(100 - used_percent, 0),
            "system_tokens": system_tokens,
            "conversation_tokens": conversation_tokens,
            "session_tokens": used_tokens,
            "preview_tokens": 0,
            "bootstrap_tokens": 0,
            "draft_tokens": 0,
            "includes_task_bootstrap": False,
        }

    def _build_noop_response(
        self,
        *,
        session_id: str,
        reason: str,
        usage_before: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a deterministic noop payload when compact is unnecessary."""
        return {
            "session_id": session_id,
            "status": "noop",
            "compacted": False,
            "reason": reason,
            "usage_before": usage_before,
            "usage_after": usage_before,
        }
