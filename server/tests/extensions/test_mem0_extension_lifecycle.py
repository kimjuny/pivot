"""Tests for the Pivot Mem0 extension lifecycle hook helpers."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_PATH = (
    PROJECT_ROOT / "extensions" / "mem0" / "extension" / "hooks" / "lifecycle.py"
)


def _load_lifecycle_module():
    """Load the Mem0 lifecycle module directly from the repository path."""
    module_name = "test_mem0_extension_lifecycle_module"
    spec = importlib.util.spec_from_file_location(module_name, LIFECYCLE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Mem0 lifecycle module for tests.")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


mem0_lifecycle = _load_lifecycle_module()


class Mem0ExtensionLifecycleTestCase(unittest.TestCase):
    """Validate timeout resolution and recall hook effects."""

    def test_service_settings_use_configured_timeout(self) -> None:
        """Configured timeout should override the default request timeout."""
        base_url, timeout_seconds = mem0_lifecycle._service_settings(
            {
                "installation_config": {
                    "base_url": "http://localhost:8765",
                    "timeout_seconds": 45,
                }
            }
        )

        self.assertEqual(base_url, "http://localhost:8765")
        self.assertEqual(timeout_seconds, 45)

    def test_service_settings_ignore_invalid_timeout(self) -> None:
        """Non-positive timeout values should fall back to the default."""
        _, timeout_seconds = mem0_lifecycle._service_settings(
            {
                "installation_config": {
                    "base_url": "http://localhost:8765",
                    "timeout_seconds": 0,
                }
            }
        )

        self.assertEqual(timeout_seconds, mem0_lifecycle.DEFAULT_TIMEOUT_SECONDS)

    def test_inject_memory_uses_configured_timeout(self) -> None:
        """Recall hook should pass the configured timeout into HTTP requests."""
        context = {
            "agent_id": 2,
            "session_id": "session-1",
            "task_id": "task-1",
            "user": {"id": 1, "username": "default"},
            "task": {"user_message": "Who are you?"},
            "installation_config": {
                "base_url": "http://localhost:8765",
                "timeout_seconds": 42,
            },
        }
        with patch.object(
            mem0_lifecycle,
            "_request_json",
            return_value={"memories": [{"content": "Call me Smith Commissioner."}]},
        ) as request_json:
            effects = mem0_lifecycle.inject_memory(context)

        self.assertEqual(effects[0]["type"], "append_prompt_block")
        self.assertIn("Smith Commissioner", effects[0]["payload"]["content"])
        request_json.assert_called_once()
        self.assertEqual(request_json.call_args.kwargs["timeout_seconds"], 42)

    def test_persist_memory_emits_submit_event(self) -> None:
        """Persist hook should emit one submit event with the returned job id."""
        context = {
            "agent_id": 2,
            "session_id": "session-1",
            "task_id": "task-1",
            "execution_mode": "live",
            "user": {"id": 1, "username": "default"},
            "task": {
                "user_message": "Please remember your name.",
                "agent_answer": "I am Smith Commissioner.",
            },
            "installation_config": {
                "base_url": "http://localhost:8765",
                "timeout_seconds": 7,
            },
        }
        with patch.object(
            mem0_lifecycle,
            "_request_json",
            return_value={
                "accepted": True,
                "job_id": "job-123",
                "status": "queued",
                "duration_ms": 12,
            },
        ) as request_json:
            effects = mem0_lifecycle.persist_memory(context)

        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["type"], "emit_event")
        self.assertEqual(
            effects[0]["payload"]["data"]["type"],
            "memory_persist_submitted",
        )
        self.assertEqual(effects[0]["payload"]["data"]["job_id"], "job-123")
        self.assertEqual(effects[0]["payload"]["data"]["status"], "queued")
        request_json.assert_called_once()
        self.assertEqual(request_json.call_args.kwargs["timeout_seconds"], 7)


if __name__ == "__main__":
    unittest.main()
