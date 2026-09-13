"""Fail deployment when generated Lore pages own presentation CSS."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PUBLIC_DESIGN_STYLESHEET = "design-system.css"
STYLESHEET_LINK_RX = re.compile(
    r"<link\b(?=[^>]*\brel=[\"']stylesheet[\"'])[^>]*>", re.IGNORECASE
)
LORE_HOME_BUTTON_RX = re.compile(
    r'<a\b[^>]*class=["\'][^"\']*\bhardware-button\b[^"\']*\bddd-focus\b[^"\']*["\'][^>]*href=["\']([^"\']+)["\'][^>]*>\s*Zur Lore-Startseite\s*</a>',
    re.IGNORECASE,
)
SHOWCASE_AMBIENCE = (
    'class="scanlines"',
    'class="vignette"',
    'class="rust-stain a"',
    'class="glitch-line"',
    'class="corner tl"',
)


def fail(path: Path, message: str) -> None:
    raise SystemExit(f"{path}: {message}")


def validate_page(path: Path, *, canonical_stylesheet: Path) -> None:
    html = path.read_text(encoding="utf-8")
    if "<style" in html.lower():
        fail(path, "inline CSS is forbidden")
    if re.search(r"\sstyle\s*=", html, re.IGNORECASE):
        fail(path, "inline presentation attributes are forbidden")
    if "fonts.googleapis.com" in html or "fonts.gstatic.com" in html:
        fail(path, "page-owned font loading is forbidden")
    stylesheet_links = STYLESHEET_LINK_RX.findall(html)
    if len(stylesheet_links) != 1:
        fail(path, "must load only the central design-system stylesheet")
    href_match = re.search(r'\bhref=["\']([^"\']+)["\']', stylesheet_links[0], re.IGNORECASE)
    if href_match is None:
        fail(path, "central design-system stylesheet has no href")
    stylesheet_path = (path.parent / href_match.group(1).split("?", 1)[0]).resolve()
    if stylesheet_path.name != PUBLIC_DESIGN_STYLESHEET or not stylesheet_path.is_file():
        fail(path, "must load the local central design-system stylesheet")
    if stylesheet_path.read_text(encoding="utf-8") != canonical_stylesheet.read_text(encoding="utf-8"):
        fail(path, "central design-system stylesheet differs from the Showcase export")
    if "lore-" in " ".join(stylesheet_links):
        fail(path, "Lore-owned stylesheet is forbidden")
    for required in SHOWCASE_AMBIENCE:
        if required not in html:
            fail(path, f"missing Showcase ambience: {required}")
    for required in ('class="specimen"', 'class="specimen-header"', 'class="wordmark"'):
        if required not in html:
            fail(path, f"missing Showcase component markup: {required}")
    if (
        'class="module-card' not in html
        and 'class="archive-detail' not in html
        and 'timeline-app' not in html
    ):
        fail(path, "missing Showcase content component markup")
    home_button = LORE_HOME_BUTTON_RX.search(html)
    if home_button:
        home_target = (path.parent / home_button.group(1)).resolve()
        if not home_target.is_file():
            fail(path, f"Lore home button target is missing: {home_button.group(1)}")
    if 'id="loreFilters"' in html:
        if 'class="hardware-button ddd-focus' not in html:
            fail(path, 'missing Showcase control markup: hardware-button ddd-focus')
        if (
            'class="module-card-header ddd-focus"' not in html
            and 'class="archive-section-summary ddd-focus"' not in html
        ):
            fail(path, 'missing Showcase control markup: focusable section summary')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-root", type=Path, required=True)
    parser.add_argument("--canonical-stylesheet", type=Path, required=True)
    args = parser.parse_args()
    root = args.docs_root
    canonical_stylesheet = args.canonical_stylesheet
    if not canonical_stylesheet.is_file():
        raise SystemExit(f"Showcase stylesheet is missing: {canonical_stylesheet}")
    pages = sorted(root.rglob("*.html"))
    if not pages:
        raise SystemExit("generated Lore output is incomplete")
    for page in pages:
        validate_page(page, canonical_stylesheet=canonical_stylesheet)
    print(f"public Lore shared-CSS contract valid: {len(pages)} pages")


if __name__ == "__main__":
    main()
