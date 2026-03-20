"""Tests for built-in web-search provider request mapping."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock, patch

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

tavily_module = import_module("app.orchestration.web_search.providers.tavily")
baidu_module = import_module("app.orchestration.web_search.providers.baidu")
providers_module = import_module("app.orchestration.web_search.providers")
types_module = import_module("app.orchestration.web_search.types")


class WebSearchProviderTestCase(unittest.TestCase):
    """Validate parameter mapping for built-in web-search providers."""

    def test_tavily_reports_ignored_safe_search_for_fast_depth(self) -> None:
        """Tavily should explain why unsupported fast-depth safe search is ignored."""
        provider = providers_module.TavilyProvider()
        captured_json: dict[str, object] = {}
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "query": "latest GDP data",
            "results": [],
            "images": [],
            "response_time": "0.9",
            "request_id": "req-1",
        }

        def fake_post(*args: object, **kwargs: object) -> Mock:
            del args
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                captured_json.update(payload)
            return response

        with patch.object(tavily_module.requests, "post", side_effect=fake_post):
            result = provider._search_with_binding(  # type: ignore[attr-defined]
                request=types_module.WebSearchQueryRequest(
                    query="latest GDP data",
                    max_results=3,
                    search_depth="fast",
                    safe_search=True,
                ),
                api_key="tvly-key",
                runtime_config={},
            )

        self.assertEqual(captured_json["search_depth"], "fast")
        self.assertNotIn("safe_search", captured_json)
        self.assertIn("safe_search", result.ignored_parameters)
        self.assertEqual(result.provider["key"], "tavily")

    def test_baidu_maps_domain_and_date_filters(self) -> None:
        """Baidu should translate abstract filters into its native payload shape."""
        provider = providers_module.BaiduProvider()
        captured_json: dict[str, object] = {}
        response = Mock()
        response.ok = True
        response.json.return_value = {
            "request_id": "req-2",
            "references": [
                {
                    "title": "Pivot",
                    "url": "https://pivot.example",
                    "content": "search result snippet",
                    "type": "web",
                    "website": "pivot.example",
                    "date": "2026-03-11 10:00:00",
                    "rerank_score": 0.91,
                }
            ],
        }

        def fake_post(*args: object, **kwargs: object) -> Mock:
            del args
            payload = kwargs.get("json")
            if isinstance(payload, dict):
                captured_json.update(payload)
            return response

        with patch.object(baidu_module.requests, "post", side_effect=fake_post):
            result = provider._search_with_binding(  # type: ignore[attr-defined]
                request=types_module.WebSearchQueryRequest(
                    query="Pivot latest update",
                    max_results=4,
                    include_domains=["example.com"],
                    exclude_domains=["ignore.example"],
                    start_date="2026-03-01",
                    end_date="2026-03-10",
                    time_range="month",
                    include_answer=True,
                ),
                api_key="bce-key",
                runtime_config={},
            )

        self.assertEqual(captured_json["search_source"], "baidu_search_v2")
        search_filter = cast(dict[str, Any], captured_json["search_filter"])
        self.assertEqual(
            cast(dict[str, Any], search_filter["match"])["site"],
            ["example.com"],
        )
        self.assertEqual(
            cast(dict[str, Any], search_filter["range"])["page_time"],
            {"gte": "2026-03-01", "lte": "2026-03-10"},
        )
        self.assertEqual(captured_json["block_websites"], ["ignore.example"])
        self.assertEqual(captured_json["search_recency_filter"], "month")
        self.assertIn("include_answer", result.ignored_parameters)
        self.assertEqual(result.results[0].source, "pivot.example")


if __name__ == "__main__":
    unittest.main()
