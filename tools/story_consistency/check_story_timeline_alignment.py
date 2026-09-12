from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MissingTimelineStory:
    story_file: str


def _story_files(story_root: Path) -> list[Path]:
    stories_dir = story_root / "Kanon" / "Geschichten"
    return [
        path
        for path in sorted(stories_dir.glob("*.md"))
        if path.name.lower() != "index.md"
    ]


def _timeline_files(story_root: Path) -> list[Path]:
    timeline_dir = story_root / "Kanon" / "Timeline"
    return [
        path
        for path in sorted(timeline_dir.glob("*.md"))
        if path.name.lower() not in {"index.md", "vorlage.md"}
    ]


def find_missing_timeline_alignment(story_root: Path) -> list[MissingTimelineStory]:
    timeline_texts = [
        path.read_text(encoding="utf-8", errors="ignore")
        for path in _timeline_files(story_root)
    ]
    missing: list[MissingTimelineStory] = []
    for story_file in _story_files(story_root):
        filename = story_file.name
        if not any(filename in text for text in timeline_texts):
            missing.append(
                MissingTimelineStory(
                    story_file=story_file.relative_to(story_root).as_posix()
                )
            )
    return missing


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check that each canon story is represented in the timeline."
    )
    ap.add_argument(
        "--story-root",
        default=None,
        help="Repo-relative or absolute path to story root (default: content/story).",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when stories without timeline alignment are found.",
    )
    args = ap.parse_args()

    root = _repo_root()
    story_root = Path(args.story_root) if args.story_root else (root / "content" / "story")
    if not story_root.is_absolute():
        story_root = (root / story_root).resolve()

    if not story_root.exists():
        raise SystemExit(f"Missing story root: {story_root}")

    missing = find_missing_timeline_alignment(story_root)
    if not missing:
        print("TOTAL_MISSING_TIMELINE_ALIGNMENT=0")
        return

    for item in missing:
        print(item.story_file)
    print(f"TOTAL_MISSING_TIMELINE_ALIGNMENT={len(missing)}")
    if args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
