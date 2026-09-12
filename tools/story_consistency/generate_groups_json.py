from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


H1_RX = re.compile(r"^#\s+(.+?)\s*$")
FENCE_RX = re.compile(r"^```")


@dataclass(frozen=True)
class Group:
    group_id: str
    name: str
    story_file: str
    aliases: list[str]


def _read_markdown_title(md_text: str) -> str | None:
    """Return first H1 title (# ...), ignoring fenced code blocks."""
    in_fence = False
    for raw in md_text.splitlines():
        line = raw.rstrip("\n")
        if FENCE_RX.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = H1_RX.match(line.strip())
        if m:
            title = m.group(1).strip()
            return title if title else None
    return None


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        vv = v.strip()
        if not vv:
            continue
        key = vv.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(vv)
    return out


def _slugify(value: str) -> str:
    s = value.strip().casefold()
    s = (
        s.replace("ß", "ss")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )
    # Replace separators with hyphen
    s = re.sub(r"[\s_]+", "-", s)
    # Keep alnum + hyphen only
    s = re.sub(r"[^a-z0-9\-]", "-", s)
    # Collapse and trim
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "group"


def _aliases_from_slug(slug: str) -> list[str]:
    # Provide a few safe, mechanical variants (no content-specific guessing).
    spaced = slug.replace("-", " ")
    compact = slug.replace("-", "")
    return [slug, spaced, compact, slug.upper(), spaced.upper()]


def _iter_group_markdown_files(story_groups_dir: Path) -> list[Path]:
    """Return group markdown files in nested folders, skipping only the root navigation page."""
    paths: list[Path] = []
    for md_path in sorted(story_groups_dir.rglob("*.md")):
        # Root navigation page, not a canonical group entity.
        if md_path.parent == story_groups_dir and md_path.name == "index.md":
            continue
        paths.append(md_path)
    return paths


CUSTOM_ALIASES_BY_ID: dict[str, list[str]] = {
    # Furry bots were merged into the Hardliner elite line.
    "hardliner": ["Furries", "Furry Bots", "Furry-Bot-Elite", "Furry-Bot-Piloten"],
    "magier": ["Cyberpunks", "Cyberpunk", "Hacker-Mage", "Hacker-Mages"],
    "looper": ["Human in the Loop", "Human-in-the-Loop"],
    "zeros": ["Zero Percentler", "Zero Percentlers"],
}

def build_groups_from_story(story_groups_dir: Path, *, story_root: Path) -> list[Group]:
    groups: list[Group] = []
    for md_path in _iter_group_markdown_files(story_groups_dir):
        file_stem = md_path.stem
        # Kept as redirect/alias page in story, but not a canonical standalone group.
        if file_stem == "furries":
            continue

        md_text = md_path.read_text(encoding="utf-8")
        title = _read_markdown_title(md_text) or file_stem.replace("-", " ")

        # Stable ID based on canonical group title.
        group_id = _slugify(title)

        if md_path.name == "index.md":
            # Keep umbrella faction indexes like Maker/Orden/Roamer, but skip duplicate
            # landing pages when the same group already has a dedicated content file.
            concrete_siblings = [p for p in md_path.parent.glob("*.md") if p.name != "index.md"]
            has_dedicated_sibling = False
            for sibling in concrete_siblings:
                sibling_text = sibling.read_text(encoding="utf-8")
                sibling_title = _read_markdown_title(sibling_text) or sibling.stem.replace("-", " ")
                sibling_ids = {
                    _slugify(sibling.stem.replace("-", " ")),
                    _slugify(sibling_title),
                }
                if group_id in sibling_ids:
                    has_dedicated_sibling = True
                    break
            if has_dedicated_sibling:
                continue

        rel_story_path = md_path.relative_to(story_root).as_posix()

        stem_aliases: list[str] = []
        if file_stem != "index":
            stem_aliases = [file_stem, file_stem.replace("-", " ")]

        aliases = _dedupe_keep_order(
            [
                title,
                *stem_aliases,
                *(_aliases_from_slug(group_id)),
                *(CUSTOM_ALIASES_BY_ID.get(group_id, [])),
            ]
        )
        groups.append(
            Group(
                group_id=group_id,
                name=title,
                story_file=rel_story_path,
                aliases=aliases,
            )
        )

    return groups


def groups_to_json(groups: list[Group]) -> dict[str, Any]:
    return {
        "version": 1,
        "groups": [
            {
                "id": g.group_id,
                "name": g.name,
                "story_file": g.story_file,
                "aliases": g.aliases,
            }
            for g in groups
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate canonical group catalog JSON from story markdown.")
    ap.add_argument(
        "--story-root",
        default=None,
        help="Repo-relative or absolute path to story root (default: content/story).",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default: weltdesign/worldmodel/groups.json).",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if output differs from generated content.",
    )
    args = ap.parse_args()

    root = _repo_root()
    story_root = Path(args.story_root) if args.story_root else (root / "content" / "story")
    if not story_root.is_absolute():
        story_root = (root / story_root).resolve()

    story_groups_dir = story_root / "Gruppen"
    if not story_groups_dir.exists():
        raise SystemExit(f"Missing groups folder: {story_groups_dir}")

    out_path = Path(args.out) if args.out else (root / "weltdesign" / "worldmodel" / "groups.json")
    if not out_path.is_absolute():
        out_path = (root / out_path).resolve()

    groups = build_groups_from_story(story_groups_dir, story_root=story_root)
    payload = groups_to_json(groups)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.check and out_path.exists():
        current = out_path.read_text(encoding="utf-8")
        if current != rendered:
            raise SystemExit(f"Out of date: {out_path} (run without --check to update)")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote {out_path} ({len(groups)} groups)")


if __name__ == "__main__":
    main()
