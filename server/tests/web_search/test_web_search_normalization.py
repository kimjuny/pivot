"""Tests for LLM-facing web-search argument normalization."""

from __future__ import annotations

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

normalization_module = import_module("app.orchestration.web_search.normalization")
types_module = import_module("app.orchestration.web_search.types")


class WebSearchNormalizationTestCase(unittest.TestCase):
    """Validate canonical cleanup for noisy LLM tool arguments."""

    def test_normalize_payload_trims_newlines_and_aliases(self) -> None:
        """The normalizer should absorb common whitespace and alias drift."""
        payload = normalization_module.normalize_web_search_request_payload(
            {
                "query": "2026 deep learning breakthrough research papers\n",
                "provider": "TAVILY\n",
                "max_results": "15\n",
                "topic": "general\n",
                "time_range": "m\n",
                "start_date": "2026-01-01\n",
                "include_images": "true\n",
                "include_domains": [
                    " https://Example.com/path ",
                    "example.com",
                    " ",
                ],
                "exclude_domains": "https://Ignore.example/foo",
            }
        )

        self.assertEqual(
            payload["query"],
            "2026 deep learning breakthrough research papers",
        )
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(payload["max_results"], 15)
        self.assertEqual(payload["topic"], "general")
        self.assertEqual(payload["time_range"], "month")
        self.assertEqual(payload["start_date"], "2026-01-01")
        self.assertTrue(payload["include_images"])
        self.assertEqual(payload["include_domains"], ["example.com"])
        self.assertEqual(payload["exclude_domains"], ["ignore.example"])

    def test_query_request_accepts_cleaned_llm_noise(self) -> None:
        """The request model should also normalize noisy direct construction."""
        request = types_module.WebSearchQueryRequest(
            query=" 2026 papers\n",
            provider="TAVILY\n",
            topic="GENERAL\n",
            time_range="w\n",
            start_date="2026-02-03 00:00:00\n",
            include_domains=[" https://arxiv.org/abs/123 ", "arxiv.org"],
            exclude_domains=" https://example.com/foo ",
        )

        self.assertEqual(request.query, "2026 papers")
        self.assertEqual(request.provider, "tavily")
        self.assertEqual(request.topic, "general")
        self.assertEqual(request.time_range, "week")
        self.assertEqual(request.start_date, "2026-02-03")
        self.assertEqual(request.include_domains, ["arxiv.org"])
        self.assertEqual(request.exclude_domains, ["example.com"])

    def test_invalid_date_fails_before_provider_execution(self) -> None:
        """Bad dates should fail in normalization before reaching any provider."""
        with self.assertRaisesRegex(ValueError, "valid YYYY-MM-DD date"):
            normalization_module.normalize_web_search_request_payload(
                {
                    "query": "test",
                    "start_date": "2026-13-99\n",
                }
            )


if __name__ == "__main__":
    unittest.main()
