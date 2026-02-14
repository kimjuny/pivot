"""Anthropic-compatible LLM implementation.

This implementation works with Anthropic's Messages API (Claude models).
"""

import contextlib
import time
import uuid
from collections.abc import Iterator
from typing import Any

from anthropic import Anthropic

from .abstract_llm import (
    AbstractLLM,
    ChatMessage,
    Choice,
    FinishReason,
    Response,
    UsageInfo,
)


class AnthropicLLM(AbstractLLM):
    """Generic implementation for Anthropic Messages API.

    This implementation works with Anthropic's Claude models and any
    compatible APIs that follow the same protocol.
    """

    DEFAULT_TIMEOUT = 60  # Request timeout in seconds
    MAX_RETRIES = 3  # Maximum number of retry attempts
    DEFAULT_MAX_TOKENS = 4096  # Default max tokens for response

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: int | None = None,
    ):
        """Initialize the Anthropic-compatible LLM implementation.

        Args:
            endpoint: The base URL for the API (e.g., "https://api.anthropic.com")
            model: The model identifier to use (e.g., "claude-3-5-sonnet-20241022")
            api_key: API key for authentication
            timeout: Request timeout in seconds. Defaults to 60 seconds.

        Raises:
            ValueError: If any required parameter is missing
        """
        if not endpoint:
            raise ValueError("Endpoint is required")
        if not model:
            raise ValueError("Model is required")
        if not api_key:
            raise ValueError("API key is required")

        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout or self.DEFAULT_TIMEOUT

        # Initialize Anthropic client
        self.client = Anthropic(
            api_key=self.api_key,
            base_url=self.endpoint,
            timeout=self.timeout,
            max_retries=self.MAX_RETRIES,
        )

    def _convert_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Convert messages format to Anthropic's expected format.

        Anthropic requires system message to be separate from the messages array.

        Args:
            messages: List of message dictionaries with 'role' and 'content'

        Returns:
            Tuple of (system_message, formatted_messages)
        """
        system_message = ""
        formatted_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                # Extract system message separately
                system_message = content
            elif role in ["user", "assistant"]:
                # Keep user and assistant messages
                formatted_messages.append({"role": role, "content": content})
            # Note: Anthropic doesn't use "tool" role the same way as OpenAI
            # Tool results are formatted differently in Anthropic's API

        return system_message, formatted_messages

    def _convert_tools_to_anthropic(
        self, openai_tools: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        """Convert OpenAI-format tools to Anthropic format.

        Anthropic tools format is slightly different from OpenAI's.

        Args:
            openai_tools: Tools in OpenAI format

        Returns:
            Tools in Anthropic format, or None if no tools provided
        """
        if not openai_tools:
            return None

        anthropic_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                # Anthropic format
                anthropic_tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
                anthropic_tools.append(anthropic_tool)

        return anthropic_tools if anthropic_tools else None

    def _convert_anthropic_response(
        self, raw_response: Any, is_stream_chunk: bool = False
    ) -> Response:
        """Convert Anthropic API response to our structured Response format.

        Args:
            raw_response: Response from the Anthropic client
            is_stream_chunk: Whether this is a streaming chunk

        Returns:
            Response: Structured response in our standard format
        """
        # Extract basic information
        response_id = getattr(raw_response, "id", str(uuid.uuid4()))
        response_model = getattr(raw_response, "model", self.model)

        # For streaming chunks
        if is_stream_chunk:
            # Handle different chunk types
            chunk_type = getattr(raw_response, "type", "")

            if chunk_type == "content_block_start":
                # Starting a new content block
                content_block = getattr(raw_response, "content_block", None)
                if content_block:
                    block_type = getattr(content_block, "type", "")
                    if block_type == "tool_use":
                        # Tool use started - we'll get the details in subsequent deltas
                        # Return empty response for now
                        pass
            elif chunk_type == "content_block_delta":
                delta = getattr(raw_response, "delta", None)
                if delta:
                    delta_type = getattr(delta, "type", "")
                    if delta_type == "text_delta":
                        # Text content delta
                        text = getattr(delta, "text", "")
                        message = ChatMessage(role="assistant", content=text)
                        choice = Choice(index=0, message=message)
                        return Response(
                            id=response_id,
                            choices=[choice],
                            created=int(time.time()),
                            model=response_model,
                        )
                    elif delta_type == "input_json_delta":
                        # Tool use input delta - could accumulate and return later if needed
                        # For now, we'll handle complete tool use in message_stop
                        pass

            # Return empty response for other chunk types
            return Response(
                id=response_id,
                choices=[],
                created=int(time.time()),
                model=response_model,
            )

        # For non-streaming responses
        # Extract content blocks (Anthropic returns array of content blocks)
        content_blocks = getattr(raw_response, "content", [])
        content_text = ""
        tool_calls = []

        for block in content_blocks:
            block_type = getattr(block, "type", "")

            if block_type == "text":
                # Text content
                if hasattr(block, "text"):
                    content_text += block.text
            elif block_type == "tool_use":
                # Tool use block - convert to OpenAI format
                tool_id = getattr(block, "id", "")
                tool_name = getattr(block, "name", "")
                tool_input = getattr(block, "input", {})

                # Convert to OpenAI tool call format
                import json

                tool_call = {
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(tool_input, ensure_ascii=False),
                    },
                }
                tool_calls.append(tool_call)

        # Extract finish reason
        finish_reason = None
        raw_stop_reason = getattr(raw_response, "stop_reason", None)
        if raw_stop_reason:
            # Map Anthropic stop reasons to our FinishReason enum
            if raw_stop_reason == "end_turn":
                finish_reason = FinishReason.STOP
            elif raw_stop_reason == "max_tokens":
                finish_reason = FinishReason.LENGTH
            elif raw_stop_reason == "tool_use":
                finish_reason = FinishReason.TOOL_CALLS
            else:
                with contextlib.suppress(ValueError):
                    finish_reason = FinishReason(raw_stop_reason)

        # Create message with tool calls if present
        message = ChatMessage(
            role="assistant",
            content=content_text if content_text else None,
            tool_calls=tool_calls if tool_calls else None,
        )

        # Create choice
        choice = Choice(index=0, message=message, finish_reason=finish_reason)

        # Extract usage information
        usage = None
        raw_usage = getattr(raw_response, "usage", None)
        if raw_usage:
            usage = UsageInfo(
                prompt_tokens=getattr(raw_usage, "input_tokens", 0),
                completion_tokens=getattr(raw_usage, "output_tokens", 0),
                total_tokens=getattr(raw_usage, "input_tokens", 0)
                + getattr(raw_usage, "output_tokens", 0),
            )

        return Response(
            id=response_id,
            choices=[choice],
            created=int(time.time()),
            model=response_model,
            usage=usage,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> Response:
        """Process a conversation with the LLM.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
                     (e.g., temperature, max_tokens, tools, etc.)

        Returns:
            Response: The structured response from the LLM

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            # Convert messages to Anthropic format
            system_message, formatted_messages = self._convert_messages(messages)

            # Convert tools from OpenAI format to Anthropic format if present
            tools = kwargs.pop("tools", None)
            anthropic_tools = self._convert_tools_to_anthropic(tools)

            # Set default max_tokens if not provided (required by Anthropic)
            if "max_tokens" not in kwargs:
                kwargs["max_tokens"] = self.DEFAULT_MAX_TOKENS

            # Build API call parameters
            api_params: dict[str, Any] = {
                "model": self.model,
                "messages": formatted_messages,
                **kwargs,
            }

            # Add system message if present
            if system_message:
                api_params["system"] = system_message

            # Add tools if present
            if anthropic_tools:
                api_params["tools"] = anthropic_tools

            # Call Anthropic API
            response = self.client.messages.create(**api_params)

            # Convert to our structured response format
            return self._convert_anthropic_response(response, is_stream_chunk=False)

        except Exception as e:
            raise RuntimeError(
                f"Anthropic API request failed for {self.endpoint}: {e!s}"
            ) from e

    def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> Iterator[Response]:
        """Process a conversation with the LLM in streaming mode.

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
                     (e.g., temperature, max_tokens, tools, etc.)

        Yields:
            Response: A chunk of the structured response from the LLM

        Raises:
            RuntimeError: If the API request fails
        """
        try:
            # Convert messages to Anthropic format
            system_message, formatted_messages = self._convert_messages(messages)

            # Convert tools from OpenAI format to Anthropic format if present
            tools = kwargs.pop("tools", None)
            anthropic_tools = self._convert_tools_to_anthropic(tools)

            # Set default max_tokens if not provided (required by Anthropic)
            if "max_tokens" not in kwargs:
                kwargs["max_tokens"] = self.DEFAULT_MAX_TOKENS

            # Build API call parameters
            api_params: dict[str, Any] = {
                "model": self.model,
                "messages": formatted_messages,
                **kwargs,
            }

            # Add system message if present
            if system_message:
                api_params["system"] = system_message

            # Add tools if present
            if anthropic_tools:
                api_params["tools"] = anthropic_tools

            # Call Anthropic API with streaming
            with self.client.messages.stream(**api_params) as stream:
                for event in stream:
                    # Convert each event to our Response format
                    yield self._convert_anthropic_response(event, is_stream_chunk=True)

        except Exception as e:
            raise RuntimeError(
                f"Anthropic streaming failed for {self.endpoint}: {e!s}"
            ) from e
