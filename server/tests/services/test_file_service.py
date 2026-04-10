"""Unit tests for uploaded file lifecycle helpers."""

from __future__ import annotations

import base64
import io
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from PIL import Image
from sqlmodel import Session, SQLModel, create_engine

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

file_service_module = import_module("app.services.file_service")
workspace_service_module = import_module("app.services.workspace_service")
FileService = file_service_module.FileService
PdfTextLayerProbe = file_service_module.PdfTextLayerProbe
SessionModel = import_module("app.models.session").Session
WorkspaceService = import_module("app.services.workspace_service").WorkspaceService
LocalFilesystemObjectStorageProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemObjectStorageProvider
LocalFilesystemPOSIXWorkspaceProvider = import_module(
    "app.storage.providers.local_fs"
).LocalFilesystemPOSIXWorkspaceProvider


class FileServiceTestCase(unittest.TestCase):
    """Validate file verification, attachment, and pruning behavior."""

    def setUp(self) -> None:
        """Create isolated database and storage fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.object_root = Path(self.temp_dir.name) / "storage"
        self.workspace_root = Path(self.temp_dir.name) / "workspace"
        resolved_profile = type(
            "ResolvedProfile",
            (),
            {
                "object_storage": LocalFilesystemObjectStorageProvider(
                    self.object_root
                ),
                "posix_workspace": LocalFilesystemPOSIXWorkspaceProvider(
                    self.workspace_root
                ),
            },
        )()
        self.profile_patch = patch.object(
            cast(Any, file_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.workspace_profile_patch = patch.object(
            cast(Any, workspace_service_module),
            "get_resolved_storage_profile",
            return_value=resolved_profile,
        )
        self.profile_patch.start()
        self.workspace_profile_patch.start()

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(engine)
        self.db = Session(engine)
        self.service = FileService(self.db)

    def tearDown(self) -> None:
        """Clean up temporary resources after each test."""
        self.db.close()
        self.profile_patch.stop()
        self.workspace_profile_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def _build_png_bytes(color: str = "#3b82f6") -> bytes:
        """Create a small in-memory PNG test image."""
        image = Image.new("RGB", (16, 12), color=color)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def test_store_attach_and_preprocess_image(self) -> None:
        """Stored images should round-trip through object-backed prompt blocks."""
        asset = self.service.store_uploaded_image(
            username="alice",
            filename="diagram.png",
            source="local",
            file_bytes=self._build_png_bytes(),
        )

        self.assertEqual(asset.kind, "image")
        self.assertEqual(asset.format, "PNG")
        self.assertEqual(asset.mime_type, "image/png")
        self.assertEqual(asset.storage_backend, "local_fs")
        self.assertIsNotNone(asset.object_key)
        resolved_path = self.service.resolve_file_content_path(asset)
        self.assertTrue(resolved_path.exists())

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-1",
            task_id="task-1",
        )
        prepared = self.service.preprocess_files(attached)

        self.assertEqual(attached[0].session_id, "session-1")
        self.assertEqual(attached[0].task_id, "task-1")
        self.assertEqual(len(prepared[0].content_blocks), 2)
        self.assertEqual(prepared[0].content_blocks[0]["type"], "text")
        self.assertIn("Attached image", prepared[0].content_blocks[0]["text"])
        self.assertEqual(prepared[0].content_blocks[1]["type"], "image")
        decoded = base64.b64decode(prepared[0].content_blocks[1]["data"])
        self.assertEqual(decoded, resolved_path.read_bytes())

    def test_uploaded_files_remain_unbound_until_a_session_is_known(self) -> None:
        """Uploads should stay reusable until a send operation binds them."""
        asset = self.service.store_uploaded_image(
            username="alice",
            filename="draft.png",
            source="clipboard",
            file_bytes=self._build_png_bytes("#14b8a6"),
        )

        self.assertIsNone(asset.session_id)
        self.assertIsNone(asset.task_id)

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-draft",
            task_id="task-draft",
        )

        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].session_id, "session-draft")
        self.assertEqual(attached[0].task_id, "task-draft")

    def test_attaching_file_projects_it_into_workspace_uploads(self) -> None:
        """Binding an upload should project it into the active workspace `.uploads` tree."""
        workspace = WorkspaceService(self.db).create_workspace(
            agent_id=7,
            username="alice",
            scope="session_private",
            session_id="session-uploads",
        )
        self.db.add(
            SessionModel(
                session_id="session-uploads",
                agent_id=7,
                user="alice",
                workspace_id=workspace.workspace_id,
                chat_history='{"version": 1, "messages": []}',
                react_llm_messages="[]",
                react_llm_cache_state="{}",
            )
        )
        self.db.commit()

        asset = self.service.store_uploaded_image(
            username="alice",
            filename="diagram.png",
            source="local",
            file_bytes=self._build_png_bytes("#ef4444"),
        )
        self.assertIsNone(asset.workspace_relative_path)

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-uploads",
            task_id="task-uploads",
        )

        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].workspace_relative_path, ".uploads/diagram.png")
        projected_path = (
            WorkspaceService(self.db).get_workspace_path(workspace)
            / (attached[0].workspace_relative_path or "")
        )
        self.assertTrue(projected_path.is_file())
        self.assertEqual(projected_path.read_bytes(), self._build_png_bytes("#ef4444"))

    def test_store_and_preprocess_document(self) -> None:
        """Document uploads should persist extracted markdown as object data."""
        original_converter = self.service._convert_document_with_docling
        original_probe = self.service._probe_pdf_text_layer

        def fake_convert_document(_path: Path) -> tuple[str, int | None]:
            return "# Spec\n\nHello from docling.", 3

        def fake_probe(_path: Path):
            return PdfTextLayerProbe(
                page_count=3,
                sampled_pages=3,
                extracted_char_count=1200,
                non_empty_pages=3,
                printable_ratio=0.95,
            )

        self.service._convert_document_with_docling = fake_convert_document
        self.service._probe_pdf_text_layer = fake_probe
        self.addCleanup(
            setattr,
            self.service,
            "_convert_document_with_docling",
            original_converter,
        )
        self.addCleanup(
            setattr,
            self.service,
            "_probe_pdf_text_layer",
            original_probe,
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
        self.assertEqual(asset.storage_backend, "local_fs")
        self.assertIsNotNone(asset.object_key)
        self.assertIsNotNone(asset.markdown_object_key)
        self.assertTrue(self.service.resolve_file_content_path(asset).exists())
        markdown_bytes = self.service._object_storage().get_bytes(
            asset.markdown_object_key or ""
        )
        self.assertIn("Hello from docling.", markdown_bytes.decode("utf-8"))

        attached = self.service.attach_files_to_task(
            [asset.file_id],
            username="alice",
            session_id="session-2",
            task_id="task-2",
        )
        prepared = self.service.preprocess_files(attached)

        self.assertEqual(len(prepared[0].content_blocks), 1)
        self.assertEqual(prepared[0].content_blocks[0]["type"], "text")
        self.assertIn("Attached document", prepared[0].content_blocks[0]["text"])
        self.assertIn("Hello from docling.", prepared[0].content_blocks[0]["text"])

    def test_pdf_probe_flags_ocr_dependent_documents(self) -> None:
        """OCR-only PDFs should be rejected before Docling conversion starts."""
        original_probe = self.service._probe_pdf_text_layer
        original_converter = self.service._convert_document_with_docling

        def fake_probe(_path: Path):
            return PdfTextLayerProbe(
                page_count=4,
                sampled_pages=4,
                extracted_char_count=12,
                non_empty_pages=0,
                printable_ratio=0.0,
            )

        def fail_convert(_path: Path) -> tuple[str, int | None]:
            raise AssertionError("Docling conversion should not run for OCR-only PDFs")

        self.service._probe_pdf_text_layer = fake_probe
        self.service._convert_document_with_docling = fail_convert
        self.addCleanup(setattr, self.service, "_probe_pdf_text_layer", original_probe)
        self.addCleanup(
            setattr,
            self.service,
            "_convert_document_with_docling",
            original_converter,
        )

        with self.assertRaisesRegex(ValueError, "require OCR are not supported"):
            self.service.store_uploaded_file(
                username="alice",
                filename="scan.pdf",
                source="local",
                file_bytes=b"%PDF-1.7 fake scanned document bytes",
            )

    def test_pdf_probe_accepts_text_based_documents(self) -> None:
        """Text PDFs should continue through the normal Docling conversion flow."""
        original_probe = self.service._probe_pdf_text_layer
        original_converter = self.service._convert_document_with_docling

        def fake_probe(_path: Path):
            return PdfTextLayerProbe(
                page_count=2,
                sampled_pages=2,
                extracted_char_count=900,
                non_empty_pages=2,
                printable_ratio=0.98,
            )

        def fake_convert(_path: Path) -> tuple[str, int | None]:
            return "Hello from text PDF.", 2

        self.service._probe_pdf_text_layer = fake_probe
        self.service._convert_document_with_docling = fake_convert
        self.addCleanup(setattr, self.service, "_probe_pdf_text_layer", original_probe)
        self.addCleanup(
            setattr,
            self.service,
            "_convert_document_with_docling",
            original_converter,
        )

        asset = self.service.store_uploaded_file(
            username="alice",
            filename="text.pdf",
            source="local",
            file_bytes=b"%PDF-1.7 fake text document bytes",
        )

        self.assertTrue(asset.can_extract_text)
        self.assertFalse(asset.suspected_scanned)

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
        self.assertFalse(
            self.service._object_storage().exists(expired_asset.object_key or "")
        )
        self.assertTrue(self.service._object_storage().exists(used_asset.object_key or ""))


if __name__ == "__main__":
    unittest.main()
