from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


LINK_RX = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass(frozen=True)
class BrokenLink:
    source_file: str
    link: str


def _is_external_or_ignored(link: str) -> bool:
    if not link:
        return True
    if link.startswith("#"):
        return True
    if "://" in link:
        return True
    if link.startswith("mailto:"):
        return True
    return False


def _candidate_paths(source_file: Path, link: str) -> list[Path]:
    # Strip hash part, if present.
    base = link.split("#", 1)[0].strip()
    if not base:
        return []

    raw = Path(base)
    if raw.is_absolute():
        return [raw]

    p = source_file.parent / raw
    candidates = [p]

    # Allow links without extension to either .md or a folder index.
    if p.suffix == "":
        candidates.append(p.with_suffix(".md"))
        candidates.append(p / "index.md")

    return candidates


def _link_exists(source_file: Path, link: str) -> bool:
    for candidate in _candidate_paths(source_file, link):
        if candidate.exists():
            return True
    return False


def find_broken_links(story_root: Path) -> list[BrokenLink]:
    broken: list[BrokenLink] = []
    for md_file in sorted(story_root.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        for m in LINK_RX.finditer(text):
            link = m.group(1).strip()
            if _is_external_or_ignored(link):
                continue
            if not _link_exists(md_file, link):
                broken.append(
                    BrokenLink(
                        source_file=md_file.relative_to(story_root).as_posix(),
                        link=link,
                    )
                )
    return broken


def main() -> None:
    ap = argparse.ArgumentParser(description="Check markdown links under content/story.")
    ap.add_argument(
        "--story-root",
        default=None,
        help="Repo-relative or absolute path to story root (default: content/story).",
    )
    args = ap.parse_args()

    root = _repo_root()
    story_root = Path(args.story_root) if args.story_root else (root / "content" / "story")
    if not story_root.is_absolute():
        story_root = (root / story_root).resolve()

    if not story_root.exists():
        raise SystemExit(f"Missing story root: {story_root}")

    broken = find_broken_links(story_root)
    if not broken:
        print("TOTAL_BROKEN=0")
        return

    for item in broken:
        print(f"{item.source_file} -> {item.link}")
    print(f"TOTAL_BROKEN={len(broken)}")
    sys.exit(1)


if __name__ == "__main__":
    main()
