"""Sample extension-backed channel provider for local import testing."""

from __future__ import annotations

from typing import Any

from app.channels.providers import BaseBuiltinProvider
from app.channels.types import ChannelManifest, ChannelTestResult


class AcmeChatProvider(BaseBuiltinProvider):
    """Minimal provider used to validate local extension imports."""

    manifest = ChannelManifest(
        key="acme@chat",
        name="ACME Chat",
        description="Sample extension-backed chat provider for local import flows.",
        icon="message-square",
        docs_url="https://example.com/acme/providers/chat",
        transport_mode="webhook",
        capabilities=["receive_text", "send_text"],
        auth_schema=[],
        config_schema=[],
        setup_steps=[
            "Import this extension locally.",
            "Bind the provider to an agent from the Channels dialog.",
        ],
    )

    def test_connection(
        self,
        auth_config: dict[str, Any],
        runtime_config: dict[str, Any],
        binding_id: int,
    ) -> ChannelTestResult:
        """Return a deterministic healthy response for local integration tests."""
        del auth_config, runtime_config
        return ChannelTestResult(
            ok=True,
            status="healthy",
            message="ACME Chat is available through the local extension package.",
            endpoint_infos=self.build_endpoint_infos(binding_id),
        )


PROVIDER = AcmeChatProvider()
