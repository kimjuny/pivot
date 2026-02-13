"""Factory for creating LLM instances based on protocol."""

from app.models.llm import LLM

from .abstract_llm import AbstractLLM
from .openai_chat_v1 import OpenAIChatV1


def create_llm_from_config(llm_config: LLM) -> AbstractLLM:
    """Create an LLM instance from database configuration.

    This factory function creates the appropriate LLM implementation based
    on the protocol specified in the LLM configuration.

    Args:
        llm_config: The LLM configuration from database

    Returns:
        AbstractLLM: An instance of the appropriate LLM implementation

    Raises:
        ValueError: If the protocol is not supported
    """
    protocol = llm_config.protocol.lower()

    if protocol in ["openai_chat_v1", "openai_responses_v1"]:
        # Both OpenAI Chat v1 and Responses v1 use the same implementation
        # (Responses v1 is essentially the same as Chat v1 in practice)
        return OpenAIChatV1(
            endpoint=llm_config.endpoint,
            model=llm_config.model,
            api_key=llm_config.api_key,
        )
    elif protocol == "anthropic_messages_v1":
        # TODO: Implement Anthropic Messages v1 protocol
        raise NotImplementedError(
            "Anthropic Messages v1 protocol is not yet implemented"
        )
    elif protocol == "custom_completion_v1":
        # TODO: Implement custom completion protocol
        raise NotImplementedError("Custom Completion v1 protocol is not yet implemented")
    else:
        raise ValueError(
            f"Unsupported protocol: {llm_config.protocol}. "
            f"Supported protocols: openai_chat_v1, openai_responses_v1"
        )
