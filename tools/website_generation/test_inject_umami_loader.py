from __future__ import annotations

import unittest
from pathlib import Path

from tools.website_generation.inject_umami_loader import _inject_loader


class InjectUmamiLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2] / ".tmp" / "inject-loader-tests"
        self.docs_root = self.repo_root / "docs"

    def test_accepts_existing_relative_loader(self) -> None:
        html_path = self.docs_root / "dns" / "index.html"
        original = "<html><body><script defer src=\"../analytics-loader.js\"></script></body></html>"

        updated, changed = _inject_loader(original, html_path, self.docs_root)

        self.assertFalse(changed)
        self.assertEqual(updated, original)

    def test_accepts_existing_root_relative_loader(self) -> None:
        html_path = self.docs_root / "index.html"
        original = "<html><body><script defer src=\"/analytics-loader.js\"></script></body></html>"

        updated, changed = _inject_loader(original, html_path, self.docs_root)

        self.assertFalse(changed)
        self.assertEqual(updated, original)

    def test_replaces_direct_umami_tag_with_page_relative_loader(self) -> None:
        html_path = self.docs_root / "dns" / "index.html"
        original = (
            "<html><body>"
            "<script src=\"https://umami.0xfab1.net/script.js\" data-website-id=\"abc\"></script>"
            "</body></html>"
        )

        updated, changed = _inject_loader(original, html_path, self.docs_root)

        self.assertTrue(changed)
        self.assertNotIn("https://umami.0xfab1.net/script.js", updated)
        self.assertIn('<script defer src="../analytics-loader.js"></script>', updated)

    def test_replaces_invalid_loader_path(self) -> None:
        html_path = self.docs_root / "dns" / "index.html"
        original = "<html><body><script defer src=\"/assets/analytics-loader.js\"></script></body></html>"

        updated, changed = _inject_loader(original, html_path, self.docs_root)

        self.assertTrue(changed)
        self.assertEqual(updated.count("analytics-loader.js"), 1)
        self.assertIn('<script defer src="../analytics-loader.js"></script>', updated)


if __name__ == "__main__":
    unittest.main()
