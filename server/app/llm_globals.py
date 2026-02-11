from app.llm.abstract_llm import AbstractLLM

# Global registry for LLM instances
# Key: model_name (e.g., "doubao", "glm-4"), Value: AbstractLLM instance
llm_registry: dict[str, AbstractLLM] = {}


def get_llm(model_name: str) -> AbstractLLM | None:
    """
    Retrieve an LLM instance by name.
    """
    return llm_registry.get(model_name)


def register_llm(model_name: str, llm_instance: AbstractLLM):
    """
    Register an LLM instance.
    """
    llm_registry[model_name] = llm_instance


def get_default_llm() -> AbstractLLM | None:
    """
    Get the first available LLM as default.
    """
    if not llm_registry:
        return None
    return next(iter(llm_registry.values()))


def get_all_names() -> list[str]:
    """
    Get all registered LLM names.
    """
    return list(llm_registry.keys())
