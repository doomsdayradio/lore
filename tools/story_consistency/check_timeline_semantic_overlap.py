from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


MILESTONE_RE = re.compile(
    r"^\s*-\s+\*\*(?P<stamp>\d{4}(?:-\d{2})?(?:-\d{2})?(?:[ T]\d{2}(?::\d{2})?)?)\s*\|\s*(?P<title>.+?)(?::)?\*\*\s*:?\s*(?P<summary>.+?)\s*$"
)
TOKEN_RE = re.compile(r"[a-z0-9äöüß]+", re.IGNORECASE)
STOPWORDS = {
    "der",
    "die",
    "das",
    "und",
    "oder",
    "mit",
    "von",
    "im",
    "in",
    "am",
    "an",
    "zu",
    "zum",
    "zur",
    "des",
    "dem",
    "den",
    "ein",
    "eine",
    "einer",
    "eines",
    "als",
    "auf",
    "aus",
    "nach",
    "für",
    "durch",
    "gegen",
    "wird",
    "werden",
    "bleibt",
    "früh",
    "spät",
    "erste",
    "erster",
    "erstes",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TimelineMilestone:
    timeline_file: str
    line_number: int
    stamp: str
    timestamp: datetime
    title: str
    summary: str
    normalized_title: str
    tokens: frozenset[str]


@dataclass(frozen=True)
class TimelineOverlap:
    left: TimelineMilestone
    right: TimelineMilestone
    title_similarity: float
    token_overlap: float
    day_distance: int


def _timeline_files(story_root: Path) -> list[Path]:
    timeline_dir = story_root / "Kanon" / "Timeline"
    return [
        path
        for path in sorted(timeline_dir.glob("*.md"))
        if path.name.lower() not in {"index.md", "vorlage.md"}
    ]


def _parse_stamp(stamp: str) -> datetime | None:
    formats = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H", "%Y-%m-%d", "%Y-%m", "%Y")
    normalized = stamp.replace("T", " ")
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _normalize_text(text: str) -> str:
    lowered = text.casefold()
    return " ".join(TOKEN_RE.findall(lowered))


def _tokenize(text: str) -> frozenset[str]:
    tokens = [
        token
        for token in TOKEN_RE.findall(text.casefold())
        if token not in STOPWORDS and len(token) > 2
    ]
    return frozenset(tokens)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _read_milestones(story_root: Path) -> list[TimelineMilestone]:
    milestones: list[TimelineMilestone] = []
    for path in _timeline_files(story_root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = MILESTONE_RE.match(line)
            if not match:
                continue
            stamp = match.group("stamp").strip()
            timestamp = _parse_stamp(stamp)
            if timestamp is None:
                continue
            title = match.group("title").strip()
            summary = match.group("summary").strip()
            milestones.append(
                TimelineMilestone(
                    timeline_file=path.relative_to(story_root).as_posix(),
                    line_number=line_number,
                    stamp=stamp,
                    timestamp=timestamp,
                    title=title,
                    summary=summary,
                    normalized_title=_normalize_text(title),
                    tokens=_tokenize(f"{title} {summary}"),
                )
            )
    return milestones


def find_semantic_overlaps(
    story_root: Path,
    *,
    min_title_similarity: float = 0.72,
    min_token_overlap: float = 0.46,
    max_day_distance: int = 420,
) -> list[TimelineOverlap]:
    milestones = _read_milestones(story_root)
    overlaps: list[TimelineOverlap] = []
    for index, left in enumerate(milestones):
        for right in milestones[index + 1 :]:
            if left.timeline_file == right.timeline_file:
                continue
            day_distance = abs((left.timestamp - right.timestamp).days)
            if day_distance > max_day_distance:
                continue
            title_similarity = SequenceMatcher(
                None, left.normalized_title, right.normalized_title
            ).ratio()
            token_overlap = _jaccard(left.tokens, right.tokens)
            exact_stamp = left.stamp == right.stamp
            exact_title = left.normalized_title == right.normalized_title
            if exact_title and exact_stamp:
                overlaps.append(
                    TimelineOverlap(
                        left=left,
                        right=right,
                        title_similarity=1.0,
                        token_overlap=token_overlap,
                        day_distance=day_distance,
                    )
                )
                continue
            if title_similarity >= min_title_similarity and token_overlap >= min_token_overlap:
                overlaps.append(
                    TimelineOverlap(
                        left=left,
                        right=right,
                        title_similarity=title_similarity,
                        token_overlap=token_overlap,
                        day_distance=day_distance,
                    )
                )
    overlaps.sort(
        key=lambda item: (
            -item.title_similarity,
            -item.token_overlap,
            item.day_distance,
            item.left.timeline_file,
            item.left.line_number,
        )
    )
    return overlaps


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check timeline milestones for suspicious semantic overlaps across different timeline files."
    )
    ap.add_argument(
        "--story-root",
        default=None,
        help="Repo-relative or absolute path to story root (default: content/story).",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when suspicious overlaps are found.",
    )
    ap.add_argument(
        "--title-threshold",
        type=float,
        default=0.72,
        help="Minimum normalized title similarity to report (default: 0.72).",
    )
    ap.add_argument(
        "--token-threshold",
        type=float,
        default=0.46,
        help="Minimum token overlap to report (default: 0.46).",
    )
    ap.add_argument(
        "--max-day-distance",
        type=int,
        default=420,
        help="Maximum day distance between milestones to compare (default: 420).",
    )
    args = ap.parse_args()

    root = _repo_root()
    story_root = Path(args.story_root) if args.story_root else (root / "content" / "story")
    if not story_root.is_absolute():
        story_root = (root / story_root).resolve()

    if not story_root.exists():
        raise SystemExit(f"Missing story root: {story_root}")

    overlaps = find_semantic_overlaps(
        story_root,
        min_title_similarity=args.title_threshold,
        min_token_overlap=args.token_threshold,
        max_day_distance=args.max_day_distance,
    )
    if not overlaps:
        print("TOTAL_TIMELINE_SEMANTIC_OVERLAPS=0")
        return

    for item in overlaps:
        print(
            " | ".join(
                [
                    f"{item.left.timeline_file}:{item.left.line_number}",
                    f"{item.left.stamp}",
                    item.left.title,
                    f"{item.right.timeline_file}:{item.right.line_number}",
                    f"{item.right.stamp}",
                    item.right.title,
                    f"title_similarity={item.title_similarity:.2f}",
                    f"token_overlap={item.token_overlap:.2f}",
                    f"day_distance={item.day_distance}",
                ]
            )
        )
    print(f"TOTAL_TIMELINE_SEMANTIC_OVERLAPS={len(overlaps)}")
    if args.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
