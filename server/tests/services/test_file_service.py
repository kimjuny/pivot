"""Unit tests for uploaded file lifecycle helpers."""

import base64
import io
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

from PIL import Image
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

FileService = import_module("app.services.file_service").FileService
workspace_service = import_module("app.services.workspace_service")


class FileServiceTestCase(unittest.TestCase):
    """Validate file verification, attachment, and pruning behavior."""

    def setUp(self) -> None:
        """Create isolated database and workspace fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_workspace_root = workspace_service._WORKSPACE_ROOT
        workspace_service._WORKSPACE_ROOT = Path(self.temp_dir.name)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        self.db = Session(engine)
        self.service = FileService(self.db)

    def tearDown(self) -> None:
        """Clean up temporary resources after each test."""
        self.db.close()
        workspace_service._WORKSPACE_ROOT = self.original_workspace_root
        self.temp_dir.cleanup()

    @staticmethod
    def _build_png_bytes(color: str = "#3b82f6") -> bytes:
        """Create a small in-memory PNG test image."""
        image = Image.new("RGB", (16, 12), color=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_store_attach_and_preprocess_image(self) -> None:
        """Stored images should round-trip into prepared multimodal blocks."""
        asset = self.service.store_uploaded_image(
            username="alice",
            filename="diagram.png",
            source="local",
            file_bytes=self._build_png_bytes(),
        )

        self.assertEqual(asset.kind, "image")
        self.assertEqual(asset.format, "PNG")
        self.assertEqual(asset.mime_type, "image/png")
        self.assertTrue(Path(asset.storage_path).exists())

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-1",
            task_id="task-1",
        )
        prepared = self.service.preprocess_files(attached)

        self.assertEqual(attached[0].session_id, "session-1")
        self.assertEqual(attached[0].task_id, "task-1")
        self.assertEqual(prepared[0].content_block["type"], "image")
        decoded = base64.b64decode(prepared[0].content_block["data"])
        self.assertEqual(decoded, Path(asset.storage_path).read_bytes())

    def test_store_and_preprocess_document(self) -> None:
        """Document uploads should persist extracted markdown for prompting."""
        original_converter = self.service._convert_document_with_docling

        def fake_convert_document(_path: Path) -> tuple[str, int | None]:
            return "# Spec\n\nHello from docling.", 3

        self.service._convert_document_with_docling = fake_convert_document
        self.addCleanup(
            setattr,
            self.service,
            "_convert_document_with_docling",
            original_converter,
        )

        asset = self.service.store_uploaded_file(
            username="alice",
            filename="spec.pdf",
            source="local",
            file_bytes=b"%PDF-1.7 fake document bytes",
        )

        self.assertEqual(asset.kind, "document")
        self.assertEqual(asset.format, "PDF")
        self.assertEqual(asset.page_count, 3)
        self.assertTrue(asset.can_extract_text)
        self.assertTrue(Path(asset.storage_path).exists())
        self.assertIsNotNone(asset.markdown_path)
        self.assertTrue(Path(asset.markdown_path or "").exists())

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-2",
            task_id="task-2",
        )
        prepared = self.service.preprocess_files(attached)

        self.assertEqual(prepared[0].content_block["type"], "text")
        self.assertIn("Attached document", prepared[0].content_block["text"])
        self.assertIn("Hello from docling.", prepared[0].content_block["text"])

    def test_prune_expired_unused_files_only(self) -> None:
        """Pruning should remove only expired files that were never attached."""
        expired_asset = self.service.store_uploaded_image(
            username="alice",
            filename="expired.png",
            source="clipboard",
            file_bytes=self._build_png_bytes("#ef4444"),
        )
        used_asset = self.service.store_uploaded_image(
            username="alice",
            filename="used.png",
            source="local",
            file_bytes=self._build_png_bytes("#22c55e"),
        )

        expired_asset.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        used_asset.session_id = "session-1"
        used_asset.task_id = "task-1"
        used_asset.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        self.db.add(expired_asset)
        self.db.add(used_asset)
        self.db.commit()

        deleted_count = self.service.prune_expired_unused_files()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(Path(expired_asset.storage_path).exists())
        self.assertTrue(Path(used_asset.storage_path).exists())


if __name__ == "__main__":
    unittest.main()
