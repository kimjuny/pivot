from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.utils.logging_config import get_logger

# Get logger for this module
logger = get_logger("llm")


class FinishReason(Enum):
    """Reason why the model finished generating."""

    STOP = "stop"  # Natural completion or encountered stop sequence
    LENGTH = "length"  # Reached max_tokens or context length limit
    TOOL_CALLS = "tool_calls"  # Model decided to call one or more tools
    CONTENT_FILTER = "content_filter"  # Content was filtered due to safety policies
    NULL = "null"  # Generation was not finished, or reason is unknown


@dataclass
class UsageInfo:
    """Token usage information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatMessage:
    """A single message in a chat."""

    role: str  # "system", "user", "assistant", "tool", etc.
    content: str | None = None  # The message content (optional for tool_calls)
    reasoning_content: str | None = None  # The reasoning content for CoT models
    tool_calls: list[dict[str, Any]] | None = None  # Tool calls from assistant
    tool_call_id: str | None = None  # Tool call ID for tool role messages


@dataclass
class Choice:
    """A single choice in a chat completion response.

    The 'choices' field in LLM API responses represents different possible completions
    for the same prompt. While many models typically return only one choice (with n=1),
    the API design allows for multiple completions to be returned, which can be useful
    for diversity in responses or when the model is uncertain about the best answer.

    Attributes:
        index (int): The index of this choice in the choices array
        message (ChatMessage): The actual message content with role and content
        finish_reason (Optional[FinishReason]): Reason why the model stopped generating
    """

    index: int
    message: ChatMessage
    finish_reason: FinishReason | None = None


@dataclass
class Response:
    """Structured response from a chat completion API.

    The Response follows a standardized format that aligns with major LLM providers
    like OpenAI, Anthropic, and Google. The 'choices' field is designed as a list to accommodate
    multiple possible responses, though in practice most models return a single choice.

    Design rationale:
    1. API Consistency: Aligns with OpenAI's Chat Completions API format for compatibility
    2. Future Extensibility: Supports features like N-best responses or diverse sampling
    3. Standardization: Provides a uniform interface across different LLM providers

    Attributes:
        id (str): Unique identifier for the completion
        choices (List[Choice]): List of completion choices (typically 1)
        created (int): Unix timestamp of when the completion was created
        model (str): The model used for the completion
        usage (Optional[UsageInfo]): Token usage information
        object (str): Object type, typically "chat.completion"
    """

    id: str  # Unique identifier for the completion
    choices: list[Choice]  # List of completion choices
    created: int  # Unix timestamp of when the completion was created
    model: str  # The model used for the completion
    usage: UsageInfo | None = None  # Token usage information
    object: str = "chat.completion"  # Object type, typically "chat.completion"

    def pretty_print(self) -> None:
        """Print the core information of the response in a formatted way."""
        logger.info("Response from LLM:")
        logger.info(f"  ID: {self.id}")
        logger.info(f"  Model: {self.model}")
        logger.info(f"  Created: {self.created}")
        logger.info("  Choices:")
        for choice in self.choices:
            logger.info(f"    Choice {choice.index}:")
            logger.info(f"      Role: {choice.message.role}")
            logger.info(f"      Content: {choice.message.content}")
            if choice.message.reasoning_content:
                logger.info(f"      Reasoning: {choice.message.reasoning_content}")
        if self.usage:
            logger.info("  Usage:")
            logger.info(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            logger.info(f"    Completion Tokens: {self.usage.completion_tokens}")
            logger.info(f"    Total Tokens: {self.usage.total_tokens}")

    def pretty_print_full(self) -> None:
        """Print all information of the response in a formatted way."""
        logger.info("Response from LLM (Full):")
        logger.info(f"  ID: {self.id}")
        logger.info(f"  Model: {self.model}")
        logger.info(f"  Created: {self.created}")
        logger.info(f"  Object: {self.object}")
        logger.info("  Choices:")
        for choice in self.choices:
            logger.info(f"    Choice {choice.index}:")
            logger.info(f"      Role: {choice.message.role}")
            logger.info(f"      Content: {choice.message.content}")
            if choice.message.reasoning_content:
                logger.info(f"      Reasoning: {choice.message.reasoning_content}")
            logger.info(
                f"      Finish Reason: {choice.finish_reason.value if choice.finish_reason else None}"
            )
        if self.usage:
            logger.info("  Usage:")
            logger.info(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            logger.info(f"    Completion Tokens: {self.usage.completion_tokens}")
            logger.info(f"    Total Tokens: {self.usage.total_tokens}")

    def first(self) -> Choice:
        """Return the first choice in the response.

        This method provides convenient access to the first (and typically only)
        choice in the response, following the convention established by OpenAI
        and other major LLM providers.

        Returns:
            Choice: The first choice in the response

        Raises:
            IndexError: If the choices list is empty
        """
        if not self.choices:
            raise IndexError("No choices available in response")
        return self.choices[0]


class AbstractLLM(ABC):
    """
    Abstract base class for Large Language Models.
    Defines the interface for initializing a model and processing conversations.
    """

    @abstractmethod
    def __init__(self, model: str | None = None, api_key: str | None = None):
        """
        Initialize the LLM with the given model and optional API key.

        Args:
            model (str): The model identifier to use
            api_key (str, optional): API key for authentication
        """
        pass

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> Response:
        """
        Process a conversation with the LLM.

        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion

        Returns:
            Response: The structured response from the LLM
        """
        pass

    @abstractmethod
    def chat_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> Iterator[Response]:
        """
        Process a conversation with the LLM in streaming mode.

        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion

        Yields:
            Response: A chunk of the structured response from the LLM
        """
        pass

    def _convert_response(self, raw_response: Any, model: str) -> Response:
        """
        Convert an OpenAI-compatible API response to our structured Response format.

        This is a helper method that can be used by LLM implementations that use
        OpenAI-compatible APIs (via the OpenAI client library).

        Args:
            raw_response: Response from the OpenAI client (ChatCompletion or stream chunk)
            model: The model name to use as fallback if not present in response

        Returns:
            Response: Structured response in our standard format
        """
        import contextlib
        import time
        import uuid

        # Extract basic information
        response_id = getattr(raw_response, "id", str(uuid.uuid4()))
        created = getattr(raw_response, "created", int(time.time()))
        response_model = getattr(raw_response, "model", model)

        # Extract choices
        choices = []
        raw_choices = getattr(raw_response, "choices", [])
        for i, raw_choice in enumerate(raw_choices):
            # Extract message or delta (for streaming)
            raw_message = getattr(raw_choice, "message", None) or getattr(
                raw_choice, "delta", None
            )

            if raw_message:
                role = getattr(raw_message, "role", "assistant")
                content = getattr(raw_message, "content", "") or ""
                reasoning_content = getattr(raw_message, "reasoning_content", None)

                # Extract tool_calls if present
                tool_calls = None
                raw_tool_calls = getattr(raw_message, "tool_calls", None)
                if raw_tool_calls:
                    tool_calls = []
                    for tc in raw_tool_calls:
                        tool_call_dict = {
                            "id": getattr(tc, "id", ""),
                            "type": getattr(tc, "type", "function"),
                        }
                        # Extract function info
                        func = getattr(tc, "function", None)
                        if func:
                            tool_call_dict["function"] = {
                                "name": getattr(func, "name", ""),
                                "arguments": getattr(func, "arguments", ""),
                            }
                        tool_calls.append(tool_call_dict)

                # Extract tool_call_id for tool role messages
                tool_call_id = getattr(raw_message, "tool_call_id", None)

                message = ChatMessage(
                    role=role,
                    content=content,
                    reasoning_content=reasoning_content,
                    tool_calls=tool_calls,
                    tool_call_id=tool_call_id,
                )
            else:
                # Fallback for empty delta
                message = ChatMessage(role="assistant", content="")

            # Extract finish reason
            finish_reason = None
            raw_finish_reason = getattr(raw_choice, "finish_reason", None)
            if raw_finish_reason:
                with contextlib.suppress(ValueError):
                    finish_reason = FinishReason(raw_finish_reason)

            choice = Choice(index=i, message=message, finish_reason=finish_reason)
            choices.append(choice)

        # Extract usage information
        usage = None
        raw_usage = getattr(raw_response, "usage", None)
        if raw_usage:
            usage = UsageInfo(
                prompt_tokens=getattr(raw_usage, "prompt_tokens", 0),
                completion_tokens=getattr(raw_usage, "completion_tokens", 0),
                total_tokens=getattr(raw_usage, "total_tokens", 0),
            )

        return Response(
            id=response_id,
            choices=choices,
            created=created,
            model=response_model,
            usage=usage,
        )
