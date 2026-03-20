"""Baidu provider for the abstract web-search system."""

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


class BaiduProvider(BaseWebSearchProvider):
    """Baidu Qianfan web-search adapter using plain HTTP requests."""

    manifest = WebSearchProviderManifest(
        key="baidu",
        name="Baidu",
        description=(
            "Baidu Qianfan real-time search over web, image, video, and Aladdin "
            "resources."
        ),
        docs_url="https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy",
        auth_schema=[
            WebSearchConfigField(
                key="api_key",
                label="API Key",
                type="secret",
                required=True,
                description=(
                    "Baidu Qianfan API Key. The official docs currently show both "
                    "Authorization and X-Appbuilder-Authorization examples, so "
                    "Pivot sends both headers for compatibility."
                ),
            )
        ],
        config_schema=[],
        setup_steps=[
            "Create a Baidu Qianfan API key for the web search capability.",
            "Paste the API key into this agent-specific provider binding.",
            "Save the provider so the agent can use the abstract web_search tool.",
        ],
        supported_parameters=[
            "query",
            "provider",
            "max_results",
            "time_range",
            "start_date",
            "end_date",
            "include_images",
            "include_domains",
            "exclude_domains",
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
        """Execute one Baidu request with already-resolved credentials."""
        edition = str(runtime_config.get("edition", "standard")).strip() or "standard"
        payload: dict[str, Any] = {
            "messages": [{"content": request.query, "role": "user"}],
            "edition": edition,
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": request.max_results}],
        }
        applied_parameters: dict[str, Any] = {
            "max_results": request.max_results,
        }
        ignored_parameters: dict[str, str] = {}

        if edition != "standard":
            payload["edition"] = edition

        if request.include_images:
            payload["resource_type_filter"].append(
                {"type": "image", "top_k": min(request.max_results, 30)}
            )
            applied_parameters["include_images"] = True

        if request.safe_search:
            payload["safe_search"] = True
            applied_parameters["safe_search"] = True

        search_filter: dict[str, Any] = {}
        if request.include_domains:
            limited_domains = request.include_domains[:100]
            search_filter.setdefault("match", {})["site"] = limited_domains
            applied_parameters["include_domains"] = limited_domains
            if len(request.include_domains) > len(limited_domains):
                ignored_parameters["include_domains"] = (
                    "Baidu only applies the first 100 include_domains entries."
                )

        if request.start_date is not None or request.end_date is not None:
            if request.start_date is not None and request.end_date is not None:
                search_filter.setdefault("range", {})["page_time"] = {
                    "gte": request.start_date,
                    "lte": request.end_date,
                }
                applied_parameters["start_date"] = request.start_date
                applied_parameters["end_date"] = request.end_date
            else:
                ignored_parameters["start_date/end_date"] = (
                    "Baidu only applies date range filtering when both start_date "
                    "and end_date are provided."
                )

        if search_filter:
            payload["search_filter"] = search_filter

        if request.exclude_domains:
            limited_blocks = request.exclude_domains[:20]
            payload["block_websites"] = limited_blocks
            applied_parameters["exclude_domains"] = limited_blocks
            if len(request.exclude_domains) > len(limited_blocks):
                ignored_parameters["exclude_domains"] = (
                    "Baidu only applies the first 20 exclude_domains entries."
                )

        if request.time_range is not None:
            baidu_time_range_map = {
                "week": "week",
                "month": "month",
                "year": "year",
            }
            mapped_time_range = baidu_time_range_map.get(request.time_range)
            if mapped_time_range is None:
                ignored_parameters["time_range"] = (
                    "Baidu only supports week, month, or year recency filters."
                )
            else:
                payload["search_recency_filter"] = mapped_time_range
                applied_parameters["time_range"] = request.time_range

        unsupported_flags = {
            "search_depth": request.search_depth is not None,
            "topic": request.topic is not None,
            "include_answer": request.include_answer,
            "include_raw_content": request.include_raw_content,
            "include_image_descriptions": request.include_image_descriptions,
            "include_favicon": request.include_favicon,
            "country": request.country is not None,
            "auto_parameters": request.auto_parameters,
            "exact_match": request.exact_match,
            "include_usage": request.include_usage,
        }
        for parameter_name, enabled in unsupported_flags.items():
            if enabled:
                ignored_parameters[parameter_name] = (
                    f"Baidu provider does not support the abstract parameter "
                    f"'{parameter_name}'."
                )

        # Why: the current Baidu docs show both Authorization and
        # X-Appbuilder-Authorization examples on the same page, so we send both
        # headers to stay compatible across doc revisions and console variants.
        response = requests.post(
            "https://qianfan.baidubce.com/v2/ai_search/web_search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "X-Appbuilder-Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if not response.ok:
            raise ValueError(f"Baidu search failed: {_read_error_detail(response)}")

        response_payload = response.json()
        if not isinstance(response_payload, dict):
            raise ValueError("Baidu search returned an invalid response payload.")
        if response_payload.get("code") not in (None, "", 0, "0"):
            raise ValueError(
                f"Baidu search failed: {response_payload.get('message') or response_payload.get('code')}"
            )

        results: list[WebSearchResultItem] = []
        for item in response_payload.get("references", []):
            if not isinstance(item, dict):
                continue
            resource_type = str(item.get("type", "web")).strip() or "web"
            result_metadata: dict[str, Any] = {}
            for key in (
                "web_anchor",
                "website",
                "authority_score",
                "rerank_score",
                "icon",
                "summary",
                "page_baijiahao",
            ):
                if item.get(key) is not None:
                    result_metadata[key] = item.get(key)

            favicon_url = None
            icon_value = item.get("icon")
            if icon_value is not None:
                favicon_url = str(icon_value).strip() or None

            title_value = str(item.get("title", "")).strip() or "(untitled)"
            url_value = str(item.get("url", "")).strip()
            snippet_value = None
            summary_value = item.get("summary")
            if summary_value is not None:
                summary_text = str(summary_value).strip()
                snippet_value = summary_text or None
            content_value = None
            page_content = item.get("page_content")
            if page_content is not None:
                page_content_text = str(page_content).strip()
                content_value = page_content_text or None

            published_at = None
            time_value = item.get("time")
            if time_value is not None:
                published_text = str(time_value).strip()
                published_at = published_text or None

            score_value = None
            rerank_score = item.get("rerank_score")
            if isinstance(rerank_score, int | float):
                score_value = float(rerank_score)

            results.append(
                WebSearchResultItem(
                    title=title_value,
                    url=url_value,
                    snippet=snippet_value,
                    content=content_value,
                    source=(
                        str(item.get("website")).strip()
                        if item.get("website") is not None
                        else None
                    ),
                    published_at=published_at,
                    score=score_value,
                    favicon_url=favicon_url,
                    resource_type=resource_type,
                    metadata=result_metadata,
                )
            )

        images = [
            {
                "url": str(item.get("url", "")).strip(),
                "description": (
                    str(item.get("summary")).strip()
                    if item.get("summary") is not None
                    else None
                ),
                "title": str(item.get("title", "")).strip() or None,
            }
            for item in response_payload.get("references", [])
            if isinstance(item, dict) and str(item.get("type", "")).strip() == "image"
        ]

        answer = None
        choices = response_payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict) and message.get("content") is not None:
                    answer_text = str(message.get("content")).strip()
                    answer = answer_text or None

        return WebSearchExecutionResult(
            query=request.query,
            provider={"key": self.manifest.key, "name": self.get_name()},
            applied_parameters=applied_parameters,
            ignored_parameters=ignored_parameters,
            provider_request=payload,
            provider_response_metadata={
                "id": response_payload.get("id"),
                "edition": response_payload.get("edition") or edition,
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
        """Run one lightweight Baidu search to validate credentials."""
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
                "Baidu connection succeeded. "
                f"Received {len(result.results)} result(s)."
            ),
        )


PROVIDER = BaiduProvider()
