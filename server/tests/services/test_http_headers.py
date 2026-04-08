"""Regression tests for RFC 5987-safe inline filename headers."""

import sys
import unittest
from importlib import import_module
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

build_inline_content_disposition = import_module(
    "app.utils.http_headers"
).build_inline_content_disposition


class HttpHeadersTestCase(unittest.TestCase):
    """Ensure file responses survive non-ASCII user filenames."""

    def test_build_inline_content_disposition_uses_ascii_fallback_and_utf8(self):
        """Chinese filenames should produce a latin-1-safe fallback plus RFC 5987."""
        header = build_inline_content_disposition("(3)B券商换绑.png")

        self.assertIn('inline; filename="(3)B.png"', header)
        self.assertIn("filename*=UTF-8''%283%29B%E5%88%B8%E5%95%86%E6%8D%A2%E7%BB%91.png", header)


if __name__ == "__main__":
    unittest.main()
