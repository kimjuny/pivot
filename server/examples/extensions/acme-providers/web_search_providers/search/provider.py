"""Sample extension-backed web-search provider for local import testing."""

from __future__ import annotations

from app.orchestration.web_search.base import BaseWebSearchProvider
from app.orchestration.web_search.types import (
    WebSearchExecutionResult,
    WebSearchProviderBinding,
    WebSearchProviderManifest,
    WebSearchQueryRequest,
    WebSearchTestResult,
)


class AcmeSearchProvider(BaseWebSearchProvider):
    """Minimal provider used to validate local extension imports."""

    manifest = WebSearchProviderManifest(
        key="acme@search",
        name="ACME Search",
        description="Sample extension-backed web-search provider for local import flows.",
        docs_url="https://example.com/acme/providers/search",
        auth_schema=[],
        config_schema=[],
        setup_steps=[
            "Import this extension locally.",
            "Bind the provider to an agent from the Web Search dialog.",
        ],
        supported_parameters=["query", "max_results"],
    )

    def get_api_key(self, binding: WebSearchProviderBinding) -> str:
        """Skip secret management so the sample works out of the box."""
        del binding
        return "sample-local-import"

    def _search_with_binding(
        self,
        *,
        request: WebSearchQueryRequest,
        api_key: str,
        runtime_config: dict[str, object],
    ) -> WebSearchExecutionResult:
        """Return a deterministic synthetic result for local testing."""
        del api_key, runtime_config
        return WebSearchExecutionResult(
            query=request.query,
            provider={"key": self.manifest.key, "name": self.manifest.name},
            applied_parameters={"max_results": request.max_results},
            results=[],
        )

    def test_connection(
        self,
        *,
        auth_config: dict[str, object],
        runtime_config: dict[str, object],
    ) -> WebSearchTestResult:
        """Return a deterministic healthy response for local integration tests."""
        del auth_config, runtime_config
        return WebSearchTestResult(
            ok=True,
            status="healthy",
            message="ACME Search is available through the local extension package.",
        )


PROVIDER = AcmeSearchProvider()
