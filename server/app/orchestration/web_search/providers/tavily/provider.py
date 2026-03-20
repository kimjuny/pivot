"""Tavily provider for the abstract web-search system."""

from __future__ import annotations

from typing import Any

import requests
from app.orchestration.web_search.base import BaseWebSearchProvider
from app.orchestration.web_search.types import (
    WebSearchConfigField,
    WebSearchExecutionResult,
    WebSearchProviderManifest,
    WebSearchQueryRequest,
    WebSearchResultItem,
    WebSearchTestResult,
)
from requests import Response

_DEFAULT_TEST_QUERY = "Pivot web search connection test"


def _read_error_detail(response: Response) -> str:
    """Extract the most helpful error detail from an HTTP response."""
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        for key in ("detail", "message", "error", "msg", "code"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return f"HTTP {response.status_code}"


class TavilyProvider(BaseWebSearchProvider):
    """Tavily Search API adapter using plain HTTP requests."""

    manifest = WebSearchProviderManifest(
        key="tavily",
        name="Tavily",
        description=(
            "General-purpose web search with strong real-time retrieval and rich "
            "content extraction controls."
        ),
        docs_url="https://docs.tavily.com/documentation/api-reference/endpoint/search",
        auth_schema=[
            WebSearchConfigField(
                key="api_key",
                label="API Key",
                type="secret",
                required=True,
                description="Tavily API key used for authenticated search requests.",
            )
        ],
        config_schema=[],
        setup_steps=[
            "Create a Tavily API key in the Tavily console.",
            "Paste the API key into this agent-specific provider binding.",
            "Save the provider so the agent can use the abstract web_search tool.",
        ],
        supported_parameters=[
            "query",
            "provider",
            "max_results",
            "search_depth",
            "topic",
            "time_range",
            "start_date",
            "end_date",
            "include_answer",
            "include_raw_content",
            "include_images",
            "include_image_descriptions",
            "include_favicon",
            "include_domains",
            "exclude_domains",
            "country",
            "auto_parameters",
            "exact_match",
            "include_usage",
            "safe_search",
        ],
    )

    def _search_with_binding(
        self,
        *,
        request: WebSearchQueryRequest,
        api_key: str,
        runtime_config: dict[str, Any],
    ) -> WebSearchExecutionResult:
        """Execute one Tavily request with already-resolved credentials."""
        del runtime_config
        payload: dict[str, Any] = {
            "query": request.query,
            "max_results": request.max_results,
            "include_answer": request.include_answer,
            "include_raw_content": request.include_raw_content,
            "include_images": request.include_images,
            "include_image_descriptions": request.include_image_descriptions,
            "include_favicon": request.include_favicon,
            "include_domains": request.include_domains,
            "exclude_domains": request.exclude_domains,
            "auto_parameters": request.auto_parameters,
            "exact_match": request.exact_match,
            "include_usage": request.include_usage,
        }
        applied_parameters: dict[str, Any] = {
            "max_results": request.max_results,
            "include_answer": request.include_answer,
            "include_raw_content": request.include_raw_content,
            "include_images": request.include_images,
            "include_favicon": request.include_favicon,
            "auto_parameters": request.auto_parameters,
            "exact_match": request.exact_match,
            "include_usage": request.include_usage,
        }
        ignored_parameters: dict[str, str] = {}

        if request.search_depth is not None:
            payload["search_depth"] = request.search_depth
            applied_parameters["search_depth"] = request.search_depth
            if request.search_depth == "advanced":
                payload["chunks_per_source"] = 3
        if request.topic is not None:
            payload["topic"] = request.topic
            applied_parameters["topic"] = request.topic
        if request.time_range is not None:
            payload["time_range"] = request.time_range
            applied_parameters["time_range"] = request.time_range
        if request.start_date is not None:
            payload["start_date"] = request.start_date
            applied_parameters["start_date"] = request.start_date
        if request.end_date is not None:
            payload["end_date"] = request.end_date
            applied_parameters["end_date"] = request.end_date
        if request.include_image_descriptions:
            if request.include_images:
                applied_parameters["include_image_descriptions"] = True
            else:
                ignored_parameters["include_image_descriptions"] = (
                    "Tavily only returns image descriptions when include_images is true."
                )
                payload["include_image_descriptions"] = False
        if request.include_domains:
            applied_parameters["include_domains"] = request.include_domains
        if request.exclude_domains:
            applied_parameters["exclude_domains"] = request.exclude_domains
        if request.country is not None:
            topic_value = request.topic or "general"
            if topic_value == "general":
                payload["country"] = request.country
                applied_parameters["country"] = request.country
                if request.topic is None:
                    payload["topic"] = "general"
                    applied_parameters["topic"] = "general"
            else:
                ignored_parameters["country"] = (
                    "Tavily only supports country boosting when topic is general."
                )
        if request.safe_search:
            depth_value = request.search_depth or "basic"
            if depth_value in {"fast", "ultra-fast"}:
                ignored_parameters["safe_search"] = (
                    "Tavily safe_search is not supported for fast or ultra-fast "
                    "search_depth values."
                )
            else:
                payload["safe_search"] = True
                applied_parameters["safe_search"] = True

        response = requests.post(
            "https://api.tavily.com/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if not response.ok:
            raise ValueError(
                f"Tavily search failed: {_read_error_detail(response)}"
            )

        response_payload = response.json()
        if not isinstance(response_payload, dict):
            raise ValueError("Tavily search returned an invalid response payload.")

        results: list[WebSearchResultItem] = []
        for item in response_payload.get("results", []):
            if not isinstance(item, dict):
                continue
            results.append(
                WebSearchResultItem(
                    title=str(item.get("title", "")).strip() or "(untitled)",
                    url=str(item.get("url", "")).strip(),
                    snippet=(
                        str(item.get("content")).strip()
                        if item.get("content") is not None
                        else None
                    ),
                    content=(
                        str(item.get("raw_content")).strip()
                        if item.get("raw_content") is not None
                        else None
                    ),
                    source=None,
                    published_at=None,
                    score=(
                        float(item["score"])
                        if isinstance(item.get("score"), int | float)
                        else None
                    ),
                    favicon_url=(
                        str(item.get("favicon")).strip()
                        if item.get("favicon") is not None
                        else None
                    ),
                    resource_type="web",
                    metadata={},
                )
            )

        images = [
            {
                "url": str(item.get("url", "")).strip(),
                "description": (
                    str(item.get("description")).strip()
                    if item.get("description") is not None
                    else None
                ),
            }
            for item in response_payload.get("images", [])
            if isinstance(item, dict)
        ]

        answer = None
        answer_value = response_payload.get("answer")
        if answer_value is not None:
            answer_text = str(answer_value).strip()
            answer = answer_text or None

        return WebSearchExecutionResult(
            query=request.query,
            provider={"key": self.manifest.key, "name": self.get_name()},
            applied_parameters=applied_parameters,
            ignored_parameters=ignored_parameters,
            provider_request=payload,
            provider_response_metadata={
                "request_id": response_payload.get("request_id"),
                "response_time": response_payload.get("response_time"),
                "usage": response_payload.get("usage"),
            },
            answer=answer,
            images=images,
            results=results,
        )

    def test_connection(
        self,
        *,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
    ) -> WebSearchTestResult:
        """Run one lightweight Tavily search to validate credentials."""
        binding_api_key = str(auth_config.get("api_key", "")).strip()
        if binding_api_key == "":
            raise ValueError("Missing required auth field: API Key")

        result = self._search_with_binding(
            request=WebSearchQueryRequest(
                query=_DEFAULT_TEST_QUERY,
                max_results=1,
            ),
            api_key=binding_api_key,
            runtime_config=runtime_config,
        )
        return WebSearchTestResult(
            ok=True,
            status="ok",
            message=(
                "Tavily connection succeeded. "
                f"Received {len(result.results)} result(s)."
            ),
        )


PROVIDER = TavilyProvider()
