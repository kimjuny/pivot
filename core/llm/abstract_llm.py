from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


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
    role: str  # "system", "user", "assistant", etc.
    content: str  # The message content


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
    finish_reason: Optional[FinishReason] = None


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
    choices: List[Choice]  # List of completion choices
    created: int  # Unix timestamp of when the completion was created
    model: str  # The model used for the completion
    usage: Optional[UsageInfo] = None  # Token usage information
    object: str = "chat.completion"  # Object type, typically "chat.completion"
    
    def pretty_print(self) -> None:
        """Print the core information of the response in a formatted way."""
        print("Response from LLM:")
        print(f"  ID: {self.id}")
        print(f"  Model: {self.model}")
        print(f"  Created: {self.created}")
        print("  Choices:")
        for choice in self.choices:
            print(f"    Choice {choice.index}:")
            print(f"      Role: {choice.message.role}")
            print(f"      Content: {choice.message.content}")
        if self.usage:
            print("  Usage:")
            print(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            print(f"    Completion Tokens: {self.usage.completion_tokens}")
            print(f"    Total Tokens: {self.usage.total_tokens}")
    
    def pretty_print_full(self) -> None:
        """Print all information of the response in a formatted way."""
        print("Response from LLM (Full):")
        print(f"  ID: {self.id}")
        print(f"  Model: {self.model}")
        print(f"  Created: {self.created}")
        print(f"  Object: {self.object}")
        print("  Choices:")
        for choice in self.choices:
            print(f"    Choice {choice.index}:")
            print(f"      Role: {choice.message.role}")
            print(f"      Content: {choice.message.content}")
            print(f"      Finish Reason: {choice.finish_reason.value if choice.finish_reason else None}")
        if self.usage:
            print("  Usage:")
            print(f"    Prompt Tokens: {self.usage.prompt_tokens}")
            print(f"    Completion Tokens: {self.usage.completion_tokens}")
            print(f"    Total Tokens: {self.usage.total_tokens}")
    
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
    def __init__(self, model: str = None, api_key: str = None):
        """
        Initialize the LLM with the given model and optional API key.
        
        Args:
            model (str): The model identifier to use
            api_key (str, optional): API key for authentication
        """
        pass

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> Response:
        """
        Process a conversation with the LLM.
        
        Args:
            messages (List[Dict[str, str]]): List of message dictionaries with 'role' and 'content'
            **kwargs: Additional arguments for the chat completion
            
        Returns:
            Response: The structured response from the LLM
        """
        pass