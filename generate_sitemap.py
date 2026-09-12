from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.sax.saxutils import escape


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for p in [current, *current.parents]:
        if (p / ".git").exists() or (p / "content" / "story").exists():
            return p
    return current


def _normalize_base_url(value: str) -> str:
    url = value.strip()
    if not url:
        raise ValueError("Base URL must not be empty.")
    if "://" not in url:
        url = f"https://{url}"
    return url.rstrip("/")


def _base_url_from_cname(docs_root: Path) -> str | None:
    cname = docs_root / "CNAME"
    if not cname.exists():
        return None

    domain = cname.read_text(encoding="utf-8", errors="ignore").strip()
    if not domain:
        return None
    return _normalize_base_url(domain)


def _to_public_path(rel_path: str) -> str:
    if rel_path == "index.html":
        return "/"
    if rel_path.endswith("/index.html"):
        return "/" + rel_path[: -len("index.html")]
    return "/" + rel_path


def _encode_public_path(public_path: str) -> str:
    if public_path == "/":
        return "/"

    has_trailing_slash = public_path.endswith("/")
    parts = [quote(part, safe="-._~") for part in public_path.strip("/").split("/")]
    encoded = "/" + "/".join(parts)
    if has_trailing_slash:
        encoded += "/"
    return encoded


def _iter_html_files(docs_root: Path) -> Iterable[Path]:
    for path in sorted(docs_root.rglob("*.html")):
        if path.is_file():
            yield path


def _is_excluded(rel_posix: str, exclude_patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel_posix, pattern) for pattern in exclude_patterns)


def build_sitemap_xml(
    docs_root: Path,
    base_url: str,
    exclude_patterns: list[str],
) -> tuple[str, int]:
    urls: list[str] = []

    for html_file in _iter_html_files(docs_root):
        rel_posix = html_file.relative_to(docs_root).as_posix()
        if _is_excluded(rel_posix, exclude_patterns):
            continue
        public_path = _to_public_path(rel_posix)
        encoded_public_path = _encode_public_path(public_path)
        urls.append(f"{base_url}{encoded_public_path}")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset xmlns="{SITEMAP_NS}">',
    ]
    for url in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url)}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    lines.append("")
    return "\n".join(lines), len(urls)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate sitemap.xml from static HTML files under docs/."
    )
    parser.add_argument(
        "--docs-root",
        default="docs",
        help="Repo-relative or absolute docs directory (default: docs).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: <docs-root>/sitemap.xml).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Base site URL, e.g. https://doomsday.radio. "
            "If omitted, value is read from <docs-root>/CNAME."
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern relative to docs root to exclude. Can be passed multiple times.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: exit with code 1 if sitemap would change.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()

    docs_root = Path(args.docs_root)
    if not docs_root.is_absolute():
        docs_root = (repo_root / docs_root).resolve()
    if not docs_root.exists():
        raise SystemExit(f"Missing docs root: {docs_root}")

    output_path = Path(args.output) if args.output else (docs_root / "sitemap.xml")
    if not output_path.is_absolute():
        output_path = (repo_root / output_path).resolve()

    if args.base_url:
        base_url = _normalize_base_url(args.base_url)
    else:
        inferred = _base_url_from_cname(docs_root)
        if not inferred:
            raise SystemExit(
                "Could not determine base URL. Pass --base-url or add docs/CNAME."
            )
        base_url = inferred

    exclude_patterns = ["404.html", "map.html", *args.exclude]
    xml_text, url_count = build_sitemap_xml(
        docs_root=docs_root,
        base_url=base_url,
        exclude_patterns=exclude_patterns,
    )

    previous = output_path.read_text(encoding="utf-8") if output_path.exists() else None

    if args.check:
        if previous != xml_text:
            print(f"Sitemap is outdated: {output_path}")
            sys.exit(1)
        print(f"Sitemap is up to date ({url_count} URLs).")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_text, encoding="utf-8")
    print(f"Wrote {url_count} URLs to {output_path}")


if __name__ == "__main__":
    main()
