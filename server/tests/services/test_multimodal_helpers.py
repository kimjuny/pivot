"""Unit tests for multimodal payload conversion helpers."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

multimodal = import_module("app.llm.multimodal")


class MultimodalHelpersTestCase(unittest.TestCase):
    """Ensure provider-specific payload conversions preserve image data."""

    def setUp(self) -> None:
        """Create a neutral multimodal block list used by all tests."""
        self.blocks = [
            {"type": "text", "text": "Describe this image."},
            {"type": "image", "media_type": "image/png", "data": "YWJj"},
        ]

    def test_openai_completion_conversion(self) -> None:
        """Chat Completions should emit text and image_url blocks."""
        converted = multimodal.to_openai_completion_content(self.blocks)
        self.assertIsInstance(converted, list)
        self.assertEqual(converted[0]["type"], "text")
        self.assertEqual(converted[1]["type"], "image_url")
        self.assertTrue(converted[1]["image_url"]["url"].startswith("data:image/png"))

    def test_openai_responses_conversion(self) -> None:
        """Responses API should emit input_text and input_image blocks."""
        converted = multimodal.to_openai_response_content(self.blocks, "user")
        self.assertIsInstance(converted, list)
        self.assertEqual(converted[0]["type"], "input_text")
        self.assertEqual(converted[1]["type"], "input_image")

    def test_anthropic_conversion(self) -> None:
        """Anthropic should emit base64 image source objects."""
        converted = multimodal.to_anthropic_content(self.blocks)
        self.assertIsInstance(converted, list)
        self.assertEqual(converted[0]["type"], "text")
        self.assertEqual(converted[1]["type"], "image")
        self.assertEqual(converted[1]["source"]["type"], "base64")

    def test_document_text_blocks_stay_as_text(self) -> None:
        """Document attachments should remain plain text across providers."""
        document_blocks = [
            {"type": "text", "text": 'Attached document: "spec.pdf"\nHello world'},
        ]

        completion_content = multimodal.to_openai_completion_content(document_blocks)
        response_content = multimodal.to_openai_response_content(
            document_blocks,
            "user",
        )
        anthropic_content = multimodal.to_anthropic_content(document_blocks)

        self.assertEqual(completion_content[0]["type"], "text")
        self.assertEqual(response_content[0]["type"], "input_text")
        self.assertEqual(anthropic_content[0]["type"], "text")


if __name__ == "__main__":
    unittest.main()
