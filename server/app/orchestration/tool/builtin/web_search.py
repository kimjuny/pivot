"""Built-in tool: search the web through one configured provider binding."""

from __future__ import annotations

from typing import Any, cast

from app.db.session import managed_session
from app.orchestration.tool import get_current_tool_execution_context, tool
from app.orchestration.web_search.normalization import (
    normalize_web_search_request_payload,
)
from app.orchestration.web_search.types import (
    SearchDepth,
    SearchTimeRange,
    SearchTopic,
    WebSearchQueryRequest,
)
from app.services.web_search_service import WebSearchService
from pydantic import ValidationError


@tool
def web_search(
    query: str,
    provider: str | None = None,
    max_results: int = 5,
    search_depth: SearchDepth | None = None,
    topic: SearchTopic | None = None,
    time_range: SearchTimeRange | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    include_answer: bool = False,
    include_raw_content: bool = False,
    include_images: bool = False,
    include_image_descriptions: bool = False,
    include_favicon: bool = False,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    country: str | None = None,
    auto_parameters: bool = False,
    exact_match: bool = False,
    include_usage: bool = False,
    safe_search: bool = False,
) -> dict[str, Any]:
    """Search the web through the provider selected for the current turn.

    This is an abstract network-search tool. Provider bindings are configured
    outside the tool itself. In the chat UI, the active provider comes from the
    user's current composer selection. If no turn-scoped selection exists, the
    tool falls back to the agent's only enabled web-search binding.

    Do not guess or hard-code provider keys in model tool calls. The runtime is
    responsible for resolving which concrete provider binding is available.

    Use this tool when you need fresh web data. The tool returns:
    - normalized search results
    - the provider that actually served the request
    - which abstract parameters took effect
    - which requested parameters were ignored by the chosen provider
    - provider request/response metadata useful for debugging

    Args:
        query: Search query to execute.
        max_results: Maximum number of normalized search results to return.
        search_depth: Optional search depth hint. Supported today by Tavily only.
        topic: Optional search topic hint such as ``general`` or ``news``.
        time_range: Optional recency filter such as ``day``, ``week``, ``month``,
            or ``year``.
        start_date: Optional lower date bound in ``YYYY-MM-DD`` format.
        end_date: Optional upper date bound in ``YYYY-MM-DD`` format.
        include_answer: Whether the provider should attempt to generate a short answer.
        include_raw_content: Whether to include richer raw page content when available.
        include_images: Whether to search for related images in addition to web pages.
        include_image_descriptions: Whether image descriptions should be returned.
        include_favicon: Whether favicon URLs should be returned when supported.
        include_domains: Optional allowlist of domains to include.
        exclude_domains: Optional denylist of domains to exclude.
        country: Optional country boost hint.
        auto_parameters: Whether the provider may infer better search parameters.
        exact_match: Whether exact quoted phrases should be preserved when supported.
        include_usage: Whether provider usage metadata should be returned.
        safe_search: Whether unsafe content should be filtered when supported.

    Returns:
        A structured dict describing the chosen provider, effective parameters,
        normalized results, and provider metadata.

    Raises:
        RuntimeError: If the tool is executed without an active agent context.
        ValueError: If parameters are invalid or no suitable provider binding exists.
    """
    context = get_current_tool_execution_context()
    if context is None:
        raise RuntimeError("web_search requires an active tool execution context.")

    try:
        selected_provider = getattr(context, "web_search_provider", None)
        normalized_payload = normalize_web_search_request_payload(
            {
                "query": query,
                "provider": selected_provider or provider,
                "max_results": max_results,
                "search_depth": search_depth,
                "topic": topic,
                "time_range": time_range,
                "start_date": start_date,
                "end_date": end_date,
                "include_answer": include_answer,
                "include_raw_content": include_raw_content,
                "include_images": include_images,
                "include_image_descriptions": include_image_descriptions,
                "include_favicon": include_favicon,
                "include_domains": include_domains,
                "exclude_domains": exclude_domains,
                "country": country,
                "auto_parameters": auto_parameters,
                "exact_match": exact_match,
                "include_usage": include_usage,
                "safe_search": safe_search,
            }
        )
        request = WebSearchQueryRequest(
            query=normalized_payload["query"],
            provider=normalized_payload["provider"],
            max_results=(
                normalized_payload["max_results"]
                if normalized_payload["max_results"] is not None
                else max_results
            ),
            search_depth=normalized_payload["search_depth"],
            topic=normalized_payload["topic"],
            time_range=normalized_payload["time_range"],
            start_date=normalized_payload["start_date"],
            end_date=normalized_payload["end_date"],
            include_answer=normalized_payload["include_answer"],
            include_raw_content=normalized_payload["include_raw_content"],
            include_images=normalized_payload["include_images"],
            include_image_descriptions=normalized_payload["include_image_descriptions"],
            include_favicon=normalized_payload["include_favicon"],
            include_domains=normalized_payload["include_domains"],
            exclude_domains=normalized_payload["exclude_domains"],
            country=normalized_payload["country"],
            auto_parameters=normalized_payload["auto_parameters"],
            exact_match=normalized_payload["exact_match"],
            include_usage=normalized_payload["include_usage"],
            safe_search=normalized_payload["safe_search"],
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    with managed_session() as db:
        result = WebSearchService(db).execute_search(
            agent_id=context.agent_id,
            request=request,
        )
    return result.model_dump()


cast(Any, web_search).__tool_metadata__.parameters = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
        "search_depth": {
            "type": "string",
            "enum": ["basic", "advanced", "fast", "ultra-fast"],
        },
        "topic": {"type": "string", "enum": ["general", "news", "finance"]},
        "time_range": {
            "type": "string",
            "enum": ["day", "week", "month", "year"],
        },
        "start_date": {"type": "string"},
        "end_date": {"type": "string"},
        "include_answer": {"type": "boolean"},
        "include_raw_content": {"type": "boolean"},
        "include_images": {"type": "boolean"},
        "include_image_descriptions": {"type": "boolean"},
        "include_favicon": {"type": "boolean"},
        "include_domains": {"type": "array", "items": {"type": "string"}},
        "exclude_domains": {"type": "array", "items": {"type": "string"}},
        "country": {"type": "string"},
        "auto_parameters": {"type": "boolean"},
        "exact_match": {"type": "boolean"},
        "include_usage": {"type": "boolean"},
        "safe_search": {"type": "boolean"},
    },
    "required": ["query"],
    "additionalProperties": False,
}
