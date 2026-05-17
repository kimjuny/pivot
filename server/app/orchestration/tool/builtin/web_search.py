"""Built-in tool: search the web through one configured provider binding."""

from __future__ import annotations

from typing import Annotated, Any

from app.db.session import managed_session
from app.orchestration.tool import Param, get_current_tool_execution_context, tool
from app.orchestration.web_search.normalization import (
    normalize_web_search_request_payload,
)
from app.orchestration.web_search.types import (
    SearchTimeRange,
    SearchTopic,
    WebSearchQueryRequest,
)
from app.services.web_search_service import WebSearchService
from pydantic import ValidationError


@tool(
    description="Search the web and return normalized results with optional topic, recency, and domain filters.",
)
def web_search(
    query: Annotated[str, Param("Search query to execute.")],
    max_results: Annotated[
        int, Param("Maximum number of normalized search results to return.")
    ] = 5,
    topic: Annotated[
        SearchTopic | None,
        Param("Search topic hint: general, news, or finance."),
    ] = None,
    time_range: Annotated[
        SearchTimeRange | None,
        Param("Recency filter: day, week, month, or year."),
    ] = None,
    include_domains: Annotated[
        list[str] | None,
        Param("Allowlist of domains to include in results."),
    ] = None,
    exclude_domains: Annotated[
        list[str] | None,
        Param("Denylist of domains to exclude from results."),
    ] = None,
) -> dict[str, Any]:
    """Search the web through the provider selected for the current turn.

    Args:
        query: Search query string.
        max_results: Max results to return (1-20).
        topic: Topic hint.
        time_range: Recency filter.
        include_domains: Domain allowlist.
        exclude_domains: Domain denylist.

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
        normalized_payload = normalize_web_search_request_payload(
            {
                "query": query,
                "provider": context.web_search_provider,
                "max_results": max_results,
                "topic": topic,
                "time_range": time_range,
                "include_domains": include_domains or [],
                "exclude_domains": exclude_domains or [],
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
            topic=normalized_payload["topic"],
            time_range=normalized_payload["time_range"],
            include_domains=normalized_payload["include_domains"],
            exclude_domains=normalized_payload["exclude_domains"],
        )
    except ValidationError as e:
        raise ValueError(str(e)) from e

    with managed_session() as db:
        result = WebSearchService(db).execute_search(
            agent_id=context.agent_id,
            request=request,
        )

    return result.model_dump()
