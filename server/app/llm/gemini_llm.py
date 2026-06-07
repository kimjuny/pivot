"""Gemini REST API LLM implementation.

Uses the Classic GenerateContent API over raw HTTP requests:
  - Non-streaming: POST /v1beta/models/{model}:generateContent
  - Streaming:     POST /v1beta/models/{model}:streamGenerateContent?alt=sse
"""

import contextlib
import json
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import requests

from .abstract_llm import (
    AbstractLLM,
    ChatMessage,
    Choice,
    FinishReason,
    Response,
    UsageInfo,
)
from .cache_policy import DEFAULT_CACHE_POLICY, validate_cache_policy
from .message_converter import to_gemini_messages
from .thinking_policy import DEFAULT_THINKING_POLICY, validate_thinking_policy

logger = logging.getLogger(__name__)

# Gemini finish reasons → our FinishReason enum
_GEMINI_FINISH_REASON_MAP: dict[str, FinishReason] = {
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "BLOCKLIST": FinishReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": FinishReason.CONTENT_FILTER,
    "SPII": FinishReason.CONTENT_FILTER,
    "MALFORMED_FUNCTION_CALL": FinishReason.STOP,
    "TOOL_CALL": FinishReason.TOOL_CALLS,
    "FUNCTION_CALL": FinishReason.TOOL_CALLS,
}


class GeminiLLM(AbstractLLM):
    """Implementation for Google Gemini REST API (Classic GenerateContent).

    Supports text generation, multimodal input, thinking (2.5 budget / 3.x
    level), function calling, and SSE streaming.
    """

    DEFAULT_TIMEOUT = 120
    DEFAULT_MAX_TOKENS = 8192

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        cache_policy: str = DEFAULT_CACHE_POLICY,
        thinking_policy: str = DEFAULT_THINKING_POLICY,
        thinking_effort: str | None = None,
        thinking_budget_tokens: int | None = None,
        timeout: int | None = None,
        extra_config: dict[str, Any] | None = None,
    ):
        if not endpoint:
            raise ValueError("Endpoint is required")
        if not model:
            raise ValueError("Model is required")
        if not api_key:
            raise ValueError("API key is required")

        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.cache_policy = validate_cache_policy("gemini_compatible", cache_policy)
        (
            self.thinking_policy,
            self.thinking_effort,
            self.thinking_budget_tokens,
        ) = validate_thinking_policy(
            "gemini_compatible",
            thinking_policy,
            thinking_effort,
            thinking_budget_tokens,
        )
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.extra_config = extra_config or {}

    # ------------------------------------------------------------------
    # Tool conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(
        openai_tools: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Convert OpenAI-format tools to Gemini ``functionDeclarations``."""
        if not openai_tools:
            return None

        declarations: list[dict[str, Any]] = []
        for tool in openai_tools:
            if tool.get("type") != "function":
                continue
            func = tool.get("function", {})
            declarations.append(
                {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                }
            )

        return declarations or None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _build_generate_url(self) -> str:
        base = self.endpoint.rstrip("/")
        return f"{base}/v1beta/models/{self.model}:generateContent"

    def _build_stream_url(self) -> str:
        base = self.endpoint.rstrip("/")
        return f"{base}/v1beta/models/{self.model}:streamGenerateContent?alt=sse"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build the full API request payload."""
        kwargs.pop("_pivot_task_id", None)
        kwargs.pop("_pivot_previous_response_id", None)

        system_instruction, contents = to_gemini_messages(messages)
        merged = {**self.extra_config, **kwargs}

        tools = merged.pop("tools", None)
        gemini_tools = self._convert_tools(tools)

        generation_config: dict[str, Any] = {}
        if "max_tokens" in merged:
            generation_config["maxOutputTokens"] = merged.pop("max_tokens")
        elif "max_completion_tokens" in merged:
            generation_config["maxOutputTokens"] = merged.pop("max_completion_tokens")
        else:
            generation_config["maxOutputTokens"] = self.DEFAULT_MAX_TOKENS

        for key in ("temperature", "topP", "topK", "stopSequences"):
            if key in merged:
                generation_config[key] = merged.pop(key)
            # Also accept snake_case variants from upper layers.
            snake = {
                "temperature": "temperature",
                "topP": "top_p",
                "topK": "top_k",
            }
            if key in snake and snake[key] in merged:
                generation_config[key] = merged.pop(snake[key])

        # Merge any remaining unknown keys into generationConfig so users
        # can pass arbitrary Gemini parameters via extra_config.
        remaining_keys = list(merged.keys())
        for key in remaining_keys:
            if key not in ("thinking", "reasoning"):
                generation_config[key] = merged.pop(key)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction is not None:
            payload["system_instruction"] = system_instruction
        if gemini_tools is not None:
            payload["tools"] = [{"function_declarations": gemini_tools}]

        return payload

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, raw: dict[str, Any]) -> Response:
        """Parse a non-streaming Gemini response dict."""
        response_id = raw.get("id", str(uuid.uuid4()))
        model_version = raw.get("modelVersion", self.model)

        content_text = ""
        reasoning_text = ""
        tool_calls: list[dict[str, Any]] = []

        candidates = raw.get("candidates", [])
        if candidates and isinstance(candidates[0], dict):
            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])

            for part in parts:
                if not isinstance(part, dict):
                    continue

                if "text" in part:
                    if part.get("thought") is True:
                        reasoning_text += part["text"]
                    else:
                        content_text += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    # Prefer provider-returned id, fall back to tool_use_id,
                    # then synthetic UUID.
                    call_id = fc.get("id") or fc.get("tool_use_id") or str(uuid.uuid4())
                    tool_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fc.get("name", ""),
                                "arguments": json.dumps(
                                    fc.get("args", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    )

            finish_reason = _GEMINI_FINISH_REASON_MAP.get(
                candidate.get("finishReason", "")
            )
        else:
            finish_reason = None

        message = ChatMessage(
            role="assistant",
            content=content_text or None,
            reasoning_content=reasoning_text or None,
            tool_calls=tool_calls or None,
        )
        choice = Choice(index=0, message=message, finish_reason=finish_reason)

        usage = None
        raw_usage = raw.get("usageMetadata")
        if isinstance(raw_usage, dict):
            prompt_tokens = raw_usage.get("promptTokenCount", 0)
            candidates_tokens = raw_usage.get("candidatesTokenCount", 0)
            total_tokens = raw_usage.get("totalTokenCount", 0)
            usage = UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=candidates_tokens,
                total_tokens=total_tokens,
                cached_input_tokens=raw_usage.get("cachedContentTokenCount", 0),
            )

        return Response(
            id=response_id,
            choices=[choice],
            created=int(time.time()),
            model=model_version,
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def chat_stream(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> Iterator[Response]:
        try:
            url = self._build_stream_url()
            headers = self._build_headers()
            payload = self._build_payload(messages, **kwargs)

            with requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                stream=True,
            ) as resp:
                if not resp.ok:
                    detail = self._http_error_detail(resp)
                    raise RuntimeError(
                        f"Gemini streaming failed for {self.endpoint}: "
                        f"HTTP {resp.status_code} - {detail}"
                    )

                for line in resp.iter_lines():
                    if not line:
                        continue
                    decoded = line.decode("utf-8").strip()
                    if not decoded.startswith("data:"):
                        continue

                    data_str = decoded.split(":", 1)[1].strip()
                    if not data_str:
                        continue

                    with contextlib.suppress(json.JSONDecodeError):
                        event = json.loads(data_str)
                        yield self._parse_stream_chunk(event)

        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            detail = self._http_error_detail(resp)
            logger.error(
                "Gemini streaming failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                resp.status_code if resp is not None else "unknown",
                detail,
            )
            raise RuntimeError(
                f"Gemini streaming failed for {self.endpoint}: "
                f"HTTP {resp.status_code if resp is not None else 'Unknown'} - {detail}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Gemini streaming failed for {self.endpoint}: {e!s}"
            ) from e

    def _parse_stream_chunk(self, chunk: dict[str, Any]) -> Response:
        """Parse one SSE JSON chunk from ``streamGenerateContent``."""
        candidates = chunk.get("candidates", [])

        content_text = ""
        reasoning_text = ""
        tool_calls: list[dict[str, Any]] = []

        if candidates and isinstance(candidates[0], dict):
            parts = candidates[0].get("content", {}).get("parts", [])
            for part_idx, part in enumerate(parts):
                if not isinstance(part, dict):
                    continue
                if "text" in part:
                    if part.get("thought") is True:
                        reasoning_text += part["text"]
                    else:
                        content_text += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    call_id = fc.get("id") or fc.get("tool_use_id") or str(uuid.uuid4())
                    tool_calls.append(
                        {
                            "index": part_idx,
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fc.get("name", ""),
                                "arguments": json.dumps(
                                    fc.get("args", {}),
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    )

        finish_reason = None
        if candidates and isinstance(candidates[0], dict):
            finish_reason = _GEMINI_FINISH_REASON_MAP.get(
                candidates[0].get("finishReason", "")
            )

        message = ChatMessage(
            role="assistant",
            content=content_text or None,
            reasoning_content=reasoning_text or None,
            tool_calls=tool_calls or None,
        )

        usage = None
        raw_usage = chunk.get("usageMetadata")
        if isinstance(raw_usage, dict):
            prompt_tokens = raw_usage.get("promptTokenCount", 0)
            candidates_tokens = raw_usage.get("candidatesTokenCount", 0)
            usage = UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=candidates_tokens,
                total_tokens=raw_usage.get("totalTokenCount", 0),
                cached_input_tokens=raw_usage.get("cachedContentTokenCount", 0),
            )

        return Response(
            id=chunk.get("id", str(uuid.uuid4())),
            choices=[Choice(index=0, message=message, finish_reason=finish_reason)],
            created=int(time.time()),
            model=self.model,
            usage=usage,
        )

    # ------------------------------------------------------------------
    # Non-streaming
    # ------------------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Response:
        try:
            url = self._build_generate_url()
            headers = self._build_headers()
            payload = self._build_payload(messages, **kwargs)

            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            return self._parse_response(resp.json())

        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            detail = self._http_error_detail(resp)
            logger.error(
                "Gemini request failed endpoint=%s model=%s status=%s detail=%s",
                self.endpoint,
                self.model,
                resp.status_code if resp is not None else "unknown",
                detail,
            )
            raise RuntimeError(
                f"Gemini API request failed for {self.endpoint}: "
                f"HTTP {resp.status_code if resp is not None else 'Unknown'} - {detail}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Gemini API request failed for {self.endpoint}: {e!s}"
            ) from e

    # ------------------------------------------------------------------
    # Error diagnostics
    # ------------------------------------------------------------------

    @staticmethod
    def _http_error_detail(response: requests.Response | None) -> str:
        if response is None:
            return "<no response>"

        detail = ""
        with contextlib.suppress(Exception):
            parsed = response.json()
            if isinstance(parsed, dict):
                error_obj = parsed.get("error", {})
                if isinstance(error_obj, dict):
                    detail = json.dumps(
                        {
                            k: error_obj[k]
                            for k in ("code", "message", "status")
                            if k in error_obj and error_obj[k] not in (None, "")
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                if not detail:
                    detail = json.dumps(
                        parsed, ensure_ascii=False, separators=(",", ":")
                    )
        if not detail:
            with contextlib.suppress(Exception):
                detail = (response.text or "").strip()
        if not detail:
            detail = "<empty response body>"
        if len(detail) > 1200:
            detail = f"{detail[:1200]}...(truncated)"
        return detail
