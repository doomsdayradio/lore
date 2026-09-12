"""
Zusammenfassung:
- baut `weltdesign/worldmodel/kanon.json` direkt aus `content/story/Kanon/`
- sammelt Kanon-Seiten, Gesetze, Konflikte, Timeline-Eintraege und Glossar in einem kleinen, kompatiblen JSON
- ersetzt damit das bisherige, veraltete Handpflege-Artefakt

Liest:
- `content/story/Kanon/**/*.md`

Schreibt:
- standardmaessig `weltdesign/worldmodel/kanon.json`

Nutzungsbeispiele:
- `python tools/worldmodel/generate_kanon_json.py`
- `python tools/worldmodel/generate_kanon_json.py --check`
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HEADING_RX = re.compile(r"^#\s+(.+?)\s*$")
EXCLUDED_FILES = {"Kanon/Timeline/vorlage.md"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    normalized = (
        value.strip()
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "item"


def _first_heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RX.match(line.strip())
        if match:
            return match.group(1).strip()
    return path.stem


def _category_for_path(relative_story_path: str) -> tuple[str, str | None, str]:
    parts = relative_story_path.split("/")
    if relative_story_path == "Kanon/index.md":
        return "kanon", None, "index"
    if relative_story_path == "Kanon/glossar.md":
        return "glossar", None, "glossary"
    section = parts[1] if len(parts) > 2 else None
    if section is None:
        return "kanon", None, "entry"
    return _slugify(section), section, "index" if parts[-1] == "index.md" else "entry"


def _entry_id(relative_story_path: str, category: str, kind: str) -> str:
    path = Path(relative_story_path)
    if relative_story_path == "Kanon/index.md":
        return "kanon"
    if relative_story_path == "Kanon/glossar.md":
        return "glossar"
    if kind == "index":
        return category
    stem = _slugify(path.stem)
    if stem == category:
        return f"{category}-eintrag"
    return stem


def build_kanon_payload(story_root: Path) -> dict[str, Any]:
    kanon_root = story_root / "Kanon"
    entries: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for path in sorted(kanon_root.rglob("*.md")):
        relative_story_path = path.relative_to(story_root).as_posix()
        if relative_story_path in EXCLUDED_FILES:
            continue
        category, section, kind = _category_for_path(relative_story_path)
        entry_id = _entry_id(relative_story_path, category, kind)
        if entry_id in used_ids:
            entry_id = _slugify(relative_story_path.removesuffix(".md"))
        used_ids.add(entry_id)
        entries.append(
            {
                "id": entry_id,
                "name": _first_heading(path),
                "story_file": relative_story_path,
                "category": category,
                "section": section,
                "kind": kind,
            }
        )

    return {
        "version": 2,
        "generated_at": _utc_now(),
        "source_story_root": "content/story/Kanon",
        "kanon": entries,
    }


def _render_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stable = dict(payload)
    stable.pop("generated_at", None)
    return stable


def parse_args() -> argparse.Namespace:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(description="Generate weltdesign/worldmodel/kanon.json from content/story/Kanon.")
    parser.add_argument(
        "--story-root",
        type=Path,
        default=repo_root / "content" / "story",
        help="Story root (default: content/story).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=repo_root / "weltdesign" / "worldmodel" / "kanon.json",
        help="Output JSON path (default: weltdesign/worldmodel/kanon.json).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether the committed kanon.json is up to date.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_kanon_payload(args.story_root.resolve())
    rendered = _render_payload(payload)

    if args.check:
        if not args.out.exists():
            raise SystemExit("kanon.json is out of date. Run: python tools/worldmodel/generate_kanon_json.py")
        try:
            existing_payload = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"kanon.json is invalid JSON: {exc}") from exc
        if _stable_payload(existing_payload) != _stable_payload(payload):
            raise SystemExit("kanon.json is out of date. Run: python tools/worldmodel/generate_kanon_json.py")
        print("kanon.json is up to date")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.out} ({len(payload['kanon'])} kanon entries)")


if __name__ == "__main__":
    main()
