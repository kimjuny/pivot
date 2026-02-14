"""Factory for creating LLM instances based on protocol."""

from app.models.llm import LLM

from .abstract_llm import AbstractLLM
from .openai_llm import OpenAILLM


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

    if protocol == "openai_compatible":
        # OpenAI-compatible APIs (OpenAI, GLM, DeepSeek, etc.)
        return OpenAILLM(
            endpoint=llm_config.endpoint,
            model=llm_config.model,
            api_key=llm_config.api_key,
        )
    elif protocol == "anthropic_compatible":
        # Anthropic-compatible APIs
        from .anthropic_llm import AnthropicLLM

        return AnthropicLLM(
            endpoint=llm_config.endpoint,
            model=llm_config.model,
            api_key=llm_config.api_key,
        )
    else:
        raise ValueError(
            f"Unsupported protocol: {llm_config.protocol}. "
            f"Supported protocols: openai_compatible, anthropic_compatible"
        )
