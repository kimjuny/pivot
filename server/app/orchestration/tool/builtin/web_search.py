"""Built-in tool: search the web through one configured provider binding."""

from __future__ import annotations

from typing import Annotated, Any

from app.db.session import managed_session
from app.orchestration.tool import Param, get_current_tool_execution_context, tool
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


@tool(
    description=(
        "Search the web through the provider selected for the current turn. "
        "Provider bindings are configured outside the tool. Do not guess or "
        "hard-code provider keys in tool calls. Returns normalized search results, "
        "the provider that served the request, and provider metadata."
    ),
)
def web_search(
    query: Annotated[str, Param("Search query to execute.")],
    provider: Annotated[
        str | None,
        Param(
            "Explicit provider override. Usually leave unset and let the "
            "runtime resolve the binding.",
            hidden=True,
        ),
    ] = None,
    max_results: Annotated[
        int, Param("Maximum number of normalized search results to return.")
    ] = 5,
    search_depth: Annotated[
        SearchDepth | None, Param("Search depth hint. Supported by some providers.")
    ] = None,
    topic: Annotated[
        SearchTopic | None,
        Param("Search topic hint such as general or news."),
    ] = None,
    time_range: Annotated[
        SearchTimeRange | None,
        Param("Recency filter: day, week, month, or year."),
    ] = None,
    start_date: Annotated[
        str | None, Param("Lower date bound in YYYY-MM-DD format.")
    ] = None,
    end_date: Annotated[
        str | None, Param("Upper date bound in YYYY-MM-DD format.")
    ] = None,
    include_answer: Annotated[
        bool,
        Param("Whether the provider should attempt to generate a short answer."),
    ] = False,
    include_raw_content: Annotated[
        bool,
        Param("Whether to include richer raw page content when available."),
    ] = False,
    include_images: Annotated[
        bool,
        Param("Whether to search for related images in addition to web pages."),
    ] = False,
    include_image_descriptions: Annotated[
        bool,
        Param("Whether image descriptions should be returned."),
    ] = False,
    include_favicon: Annotated[
        bool,
        Param("Whether favicon URLs should be returned when supported."),
    ] = False,
    include_domains: Annotated[
        list[str] | None,
        Param("Allowlist of domains to include in results."),
    ] = None,
    exclude_domains: Annotated[
        list[str] | None,
        Param("Denylist of domains to exclude from results."),
    ] = None,
    country: Annotated[
        str | None, Param("Country boost hint for result ranking.")
    ] = None,
    auto_parameters: Annotated[
        bool,
        Param("Whether the provider may infer better search parameters."),
    ] = False,
    exact_match: Annotated[
        bool,
        Param("Whether exact quoted phrases should be preserved when supported."),
    ] = False,
    include_usage: Annotated[
        bool,
        Param("Whether provider usage metadata should be returned."),
    ] = False,
    safe_search: Annotated[
        bool,
        Param("Whether unsafe content should be filtered when supported."),
    ] = False,
) -> dict[str, Any]:
    """Search the web through the provider selected for the current turn.

    Args:
        query: Search query string.
        provider: Provider override.
        max_results: Max results.
        search_depth: Depth hint.
        topic: Topic hint.
        time_range: Recency filter.
        start_date: Start date.
        end_date: End date.
        include_answer: Generate short answer.
        include_raw_content: Include raw page content.
        include_images: Include images.
        include_image_descriptions: Include image descriptions.
        include_favicon: Include favicons.
        include_domains: Domain allowlist.
        exclude_domains: Domain denylist.
        country: Country boost.
        auto_parameters: Let provider infer parameters.
        exact_match: Preserve exact phrases.
        include_usage: Include usage metadata.
        safe_search: Filter unsafe content.

    Returns:
        Structured dict with provider info, results, and metadata.

    Raises:
        RuntimeError: If the tool is executed without an active agent context.
        ValueError: If parameters are invalid or no suitable provider exists.
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
    except ValidationError as e:
        raise ValueError(str(e)) from e

    with managed_session() as db:
        result = WebSearchService(db).execute_search(
            agent_id=context.agent_id,
            request=request,
        )

    return result.model_dump()
