"""Unit tests for canonical user tool storage and lazy materialization."""

import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from typing import Any, cast

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

binary_storage_service = import_module("app.services.binary_storage_service")
local_data_paths_service = import_module("app.services.local_data_paths_service")
user_tool_storage_service = import_module("app.services.user_tool_storage_service")

LocalFilesystemBinaryStorageBackend = (
    binary_storage_service.LocalFilesystemBinaryStorageBackend
)
UserToolStorageService = user_tool_storage_service.UserToolStorageService


class UserToolStorageServiceTestCase(unittest.TestCase):
    """Validate canonical user tool persistence plus local runtime cache behavior."""

    def setUp(self) -> None:
        """Isolate workspace-root state for each test."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.local_data_root = Path(self.temp_dir.name) / "data"
        self.local_cache_root = Path(self.temp_dir.name) / "cache"
        local_data_module = cast(Any, local_data_paths_service)
        self.original_local_data_root = local_data_module._LOCAL_DATA_ROOT_OVERRIDE
        self.original_local_cache_root = local_data_module._LOCAL_CACHE_ROOT_OVERRIDE
        local_data_module._LOCAL_DATA_ROOT_OVERRIDE = self.local_data_root
        local_data_module._LOCAL_CACHE_ROOT_OVERRIDE = self.local_cache_root
        self.service = UserToolStorageService(
            storage_backend=LocalFilesystemBinaryStorageBackend()
        )

    def tearDown(self) -> None:
        """Restore workspace-root state after each test."""
        local_data_module = cast(Any, local_data_paths_service)
        local_data_module._LOCAL_DATA_ROOT_OVERRIDE = self.original_local_data_root
        local_data_module._LOCAL_CACHE_ROOT_OVERRIDE = self.original_local_cache_root
        self.temp_dir.cleanup()

    @staticmethod
    def _tool_source(*, tool_name: str) -> str:
        """Return one decorated tool module for metadata loading tests."""
        return (
            "from app.orchestration.tool import tool\n\n"
            "@tool\n"
            f"def {tool_name}(query: str) -> str:\n"
            '    """Return the provided query for smoke testing."""\n'
            "    return query\n"
        )

    def test_write_user_tool_persists_canonical_and_local_cache(self) -> None:
        """Writes should update canonical storage and the local runtime cache."""
        source = self._tool_source(tool_name="echo_query")

        self.service.write_user_tool("alice", "echo_query", source)

        canonical_path = (
            self.local_data_root
            / "storage"
            / "users"
            / "alice"
            / "tools"
            / "echo_query"
            / "tool.py"
        )
        cache_path = (
            self.local_cache_root
            / "users"
            / "alice"
            / "tools"
            / "echo_query"
            / "tool.py"
        )
        self.assertTrue(canonical_path.is_file())
        self.assertEqual(canonical_path.read_text(encoding="utf-8"), source)
        self.assertTrue(cache_path.is_file())
        self.assertEqual(cache_path.read_text(encoding="utf-8"), source)

    def test_read_user_tool_lazy_materializes_from_canonical_storage(self) -> None:
        """Reads should recreate the local cache when only canonical bytes remain."""
        source = self._tool_source(tool_name="summarize_notes")
        self.service.write_user_tool("alice", "summarize_notes", source)
        cache_path = self.service.local_cache_path(
            username="alice",
            tool_name="summarize_notes",
        )
        cache_path.unlink()
        cache_path.parent.rmdir()

        restored = self.service.read_user_tool("alice", "summarize_notes")

        self.assertEqual(restored, source)
        self.assertTrue(cache_path.is_file())
        self.assertEqual(cache_path.read_text(encoding="utf-8"), source)

    def test_load_metadata_and_list_user_tools_from_canonical_storage(self) -> None:
        """Metadata listing should inspect lazily materialized canonical tool files."""
        self.service.write_user_tool(
            "alice",
            "search_customers",
            self._tool_source(tool_name="search_customers"),
        )

        metadata = self.service.load_user_tool_metadata("alice", "search_customers")
        tools = self.service.list_user_tools("alice")

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.name, "search_customers")
        self.assertEqual(metadata.tool_type, "normal")
        self.assertEqual(
            tools,
            [
                {
                    "name": "search_customers",
                    "filename": "tool.py",
                    "tool_type": "normal",
                }
            ],
        )

    def test_delete_user_tool_removes_canonical_and_cache(self) -> None:
        """Deletes should clear both canonical storage and local materialized cache."""
        self.service.write_user_tool(
            "alice",
            "archive_ticket",
            self._tool_source(tool_name="archive_ticket"),
        )

        self.service.delete_user_tool("alice", "archive_ticket")

        canonical_path = (
            self.local_data_root
            / "storage"
            / "users"
            / "alice"
            / "tools"
            / "archive_ticket"
            / "tool.py"
        )
        cache_dir = (
            self.local_cache_root
            / "users"
            / "alice"
            / "tools"
            / "archive_ticket"
        )
        self.assertFalse(canonical_path.exists())
        self.assertFalse(cache_dir.exists())
        with self.assertRaises(FileNotFoundError):
            self.service.read_user_tool("alice", "archive_ticket")


if __name__ == "__main__":
    unittest.main()
