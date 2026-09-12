from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path, PurePosixPath


LOADER_FILENAME = "analytics-loader.js"
UMAMI_TAG_RX = re.compile(
    r"<script\b[^>]*\bsrc=[\"']https://umami\.0xfab1\.net/script\.js[\"'][^>]*>\s*</script>\s*",
    re.IGNORECASE,
)
LOADER_TAG_RX = re.compile(
    r"<script\b[^>]*\bsrc=[\"'](?P<src>[^\"']*analytics-loader\.js(?:[?#][^\"']*)?)[\"'][^>]*>\s*</script>\s*",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    current = Path(__file__).resolve().parent
    for p in [current, *current.parents]:
        if (p / ".git").exists() or (p / "content" / "story").exists():
            return p
    return current


def _strip_query_and_fragment(src: str) -> str:
    return src.split("?", 1)[0].split("#", 1)[0]


def _expected_loader_src(html_path: Path, docs_root: Path) -> str:
    target = docs_root / LOADER_FILENAME
    relative = os.path.relpath(target, html_path.parent)
    return relative.replace("\\", "/")


def _loader_tag(html_path: Path, docs_root: Path) -> str:
    return f'<script defer src="{_expected_loader_src(html_path, docs_root)}"></script>'


def _resolves_to_loader(src: str, html_path: Path, docs_root: Path) -> bool:
    loader_path = (docs_root / LOADER_FILENAME).resolve()
    normalized_src = _strip_query_and_fragment(src)
    posix_path = PurePosixPath(normalized_src)

    if posix_path.is_absolute():
        candidate = docs_root.joinpath(*posix_path.parts[1:])
    else:
        candidate = html_path.parent.joinpath(*posix_path.parts)

    return candidate.resolve() == loader_path


def _dedupe_loader_tags(html_text: str, html_path: Path, docs_root: Path) -> tuple[str, bool, bool]:
    changed = False
    found_valid_loader = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal changed, found_valid_loader
        src = match.group("src")
        if not _resolves_to_loader(src, html_path, docs_root):
            changed = True
            return ""
        if found_valid_loader:
            changed = True
            return ""
        found_valid_loader = True
        return match.group(0)

    updated = LOADER_TAG_RX.sub(_replace, html_text)
    return updated, changed, found_valid_loader


def _inject_loader(html_text: str, html_path: Path, docs_root: Path) -> tuple[str, bool]:
    updated = UMAMI_TAG_RX.sub("", html_text)
    changed = updated != html_text

    updated, loader_changed, has_loader = _dedupe_loader_tags(updated, html_path, docs_root)
    changed = changed or loader_changed

    if has_loader:
        return updated, changed

    body_close = re.search(r"</body>", updated, flags=re.IGNORECASE)
    if body_close:
        updated = (
            updated[: body_close.start()]
            + f"  {_loader_tag(html_path, docs_root)}\n"
            + updated[body_close.start() :]
        )
        return updated, True

    head_close = re.search(r"</head>", updated, flags=re.IGNORECASE)
    if head_close:
        updated = (
            updated[: head_close.start()]
            + f"  {_loader_tag(html_path, docs_root)}\n"
            + updated[head_close.start() :]
        )
        return updated, True

    return updated, changed


def _iter_html_files(docs_root: Path) -> list[Path]:
    return sorted(p for p in docs_root.rglob("*.html") if p.is_file())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace direct Umami tags with analytics-loader.js in docs HTML files."
    )
    parser.add_argument(
        "--docs-root",
        default="docs",
        help="Repo-relative or absolute docs directory (default: docs).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check mode: exit with code 1 if changes would be required.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    docs_root = Path(args.docs_root)
    if not docs_root.is_absolute():
        docs_root = (repo_root / docs_root).resolve()
    if not docs_root.exists():
        raise SystemExit(f"Missing docs root: {docs_root}")

    changed_files: list[Path] = []
    total = 0
    for html_path in _iter_html_files(docs_root):
        total += 1
        original = html_path.read_text(encoding="utf-8")
        updated, changed = _inject_loader(original, html_path, docs_root)
        if not changed:
            continue
        changed_files.append(html_path)
        if not args.check:
            html_path.write_text(updated, encoding="utf-8")

    if args.check:
        if changed_files:
            print(f"Analytics loader not fully integrated ({len(changed_files)} files need updates).")
            for path in changed_files[:20]:
                print(path)
            if len(changed_files) > 20:
                print(f"... and {len(changed_files) - 20} more.")
            sys.exit(1)
        print(f"Analytics loader is integrated for all {total} HTML files.")
        return

    print(f"Updated {len(changed_files)} of {total} HTML files.")


if __name__ == "__main__":
    main()
