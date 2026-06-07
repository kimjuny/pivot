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
    cached_input_tokens: int = 0


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
        logger.debug("Response from LLM:")
        logger.debug(f"  ID: {self.id}")
        logger.debug(f"  Model: {self.model}")
        logger.debug(f"  Created: {self.created}")
        logger.debug("  Choices:")
        for choice in self.choices:
            logger.debug(f"    Choice {choice.index}:")
            logger.debug(f"      Role: {choice.message.role}")
            logger.debug(f"      Content: {choice.message.content}")
            if choice.message.reasoning_content:
                logger.debug(f"      Reasoning: {choice.message.reasoning_content}")
        if self.usage:
            logger.debug("  Usage:")
            logger.debug(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            logger.debug(f"    Completion Tokens: {self.usage.completion_tokens}")
            logger.debug(f"    Total Tokens: {self.usage.total_tokens}")
            logger.debug(f"    Cached Input Tokens: {self.usage.cached_input_tokens}")

    def pretty_print_full(self) -> None:
        """Print all information of the response in a formatted way."""
        logger.debug("Response from LLM (Full):")
        logger.debug(f"  ID: {self.id}")
        logger.debug(f"  Model: {self.model}")
        logger.debug(f"  Created: {self.created}")
        logger.debug(f"  Object: {self.object}")
        logger.debug("  Choices:")
        for choice in self.choices:
            logger.debug(f"    Choice {choice.index}:")
            logger.debug(f"      Role: {choice.message.role}")
            logger.debug(f"      Content: {choice.message.content}")
            if choice.message.reasoning_content:
                logger.debug(f"      Reasoning: {choice.message.reasoning_content}")
            logger.debug(
                f"      Finish Reason: {choice.finish_reason.value if choice.finish_reason else None}"
            )
        if self.usage:
            logger.debug("  Usage:")
            logger.debug(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            logger.debug(f"    Completion Tokens: {self.usage.completion_tokens}")
            logger.debug(f"    Total Tokens: {self.usage.total_tokens}")
            logger.debug(f"    Cached Input Tokens: {self.usage.cached_input_tokens}")

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

    def to_dict(self) -> dict[str, Any]:
        """Converts response object into a plain dictionary.

        This method is useful when persisting/transmitting the response as JSON,
        because dataclass instances and enum objects are converted to primitive
        serializable values.

        Returns:
            A JSON-serializable dictionary representation of the response.
        """
        return {
            "id": self.id,
            "choices": [
                {
                    "index": choice.index,
                    "message": {
                        "role": choice.message.role,
                        "content": choice.message.content,
                        "reasoning_content": choice.message.reasoning_content,
                        "tool_calls": choice.message.tool_calls,
                        "tool_call_id": choice.message.tool_call_id,
                    },
                    "finish_reason": (
                        choice.finish_reason.value if choice.finish_reason else None
                    ),
                }
                for choice in self.choices
            ],
            "created": self.created,
            "model": self.model,
            "usage": (
                {
                    "prompt_tokens": self.usage.prompt_tokens,
                    "completion_tokens": self.usage.completion_tokens,
                    "total_tokens": self.usage.total_tokens,
                    "cached_input_tokens": self.usage.cached_input_tokens,
                }
                if self.usage
                else None
            ),
            "object": self.object,
        }


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
    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Response:
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
        self, messages: list[dict[str, Any]], **kwargs: Any
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

    def uses_incremental_request_messages(self) -> bool:
        """Whether this LLM should receive only incremental messages.

        Returns:
            True when transport protocol expects incremental input chunks instead
            of full conversation history.
        """
        return False

    def _extract_cached_input_tokens(self, raw_usage: Any) -> int:
        """Extract cached input token count across provider-specific usage formats.

        Args:
            raw_usage: Usage payload as either dict-like or object-like structure.

        Returns:
            Number of input tokens served from cache. Returns 0 when unavailable.
        """

        def _read(source: Any, key: str) -> Any:
            if source is None:
                return None
            if isinstance(source, dict):
                return source.get(key)
            return getattr(source, key, None)

        def _to_int(value: Any) -> int | None:
            if value is None:
                return None
            try:
                return max(int(value), 0)
            except (TypeError, ValueError):
                return None

        direct_keys = (
            # OpenAI/Groq compatible variants
            "cached_input_tokens",
            "cache_hit_tokens",
            "cached_prompt_tokens",
            # Anthropic cache usage variants
            "cache_read_input_tokens",
            "cache_read_prompt_tokens",
            # Some vendors may use this generic name
            "cached_tokens",
        )
        for key in direct_keys:
            parsed = _to_int(_read(raw_usage, key))
            if parsed is not None:
                return parsed

        nested_detail_keys = (
            "prompt_tokens_details",
            "prompt_token_details",
            "input_tokens_details",
            "input_token_details",
            "token_details",
        )
        nested_cached_keys = (
            "cached_tokens",
            "cached_input_tokens",
            "cache_hit_tokens",
            "cached_prompt_tokens",
            "cache_read_input_tokens",
        )
        for detail_key in nested_detail_keys:
            details = _read(raw_usage, detail_key)
            if details is None:
                continue
            for cached_key in nested_cached_keys:
                parsed = _to_int(_read(details, cached_key))
                if parsed is not None:
                    return parsed

        return 0
