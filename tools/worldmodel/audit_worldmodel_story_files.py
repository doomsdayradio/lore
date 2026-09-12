"""
Zusammenfassung:
- prueft `story_file`-Verweise in den Worldmodel-JSONs gegen `content/story/`
- meldet fehlende oder umbenannte Dateien
- kann bei eindeutigen Treffern Reparaturvorschlaege direkt uebernehmen

Liest:
- `weltdesign/worldmodel/assets.json`
- `weltdesign/worldmodel/groups.json`
- `content/story/**/*.md`

Schreibt:
- `weltdesign/worldmodel/story_file_audit.json`
- optional aktualisierte `assets.json` und `groups.json`

Standard:
- liest assets.json und groups.json
- prueft, ob story_file unter content/story existiert
- erstellt Vorschlaege fuer fehlende Dateien
- schreibt Report als JSON

Optional:
- --apply-best: uebernimmt eindeutige, ausreichend gute Treffer direkt

Nutzungsbeispiele:
- `python tools/worldmodel/audit_worldmodel_story_files.py`
- `python tools/worldmodel/audit_worldmodel_story_files.py --apply-best`
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


KNOWN_RENAMES: dict[str, str] = {
    "Assets/Handelsposten/Schrauberkapelle.md": "Assets/Handelsposten/Chaos-Kapelle.md",
    "Radiostation/programm.md": "Radiostation/Programm/programm.md",
    "Gruppen/DerStack/StackCast.md": "Radiostation/StackCast.md",
    "Assets/Zonen/Verseuchte-Zonen.md": "Assets/Zonen/index.md",
}


@dataclass(frozen=True)
class EntryRef:
    source: str  # "assets" | "groups"
    index: int
    item_id: str
    name: str
    story_file: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = s.replace("\\", "/")
    s = re.sub(r"[^a-z0-9/]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _collect_entries(payload: dict[str, Any], source_key: str) -> list[EntryRef]:
    arr = payload.get(source_key, [])
    refs: list[EntryRef] = []
    if not isinstance(arr, list):
        return refs
    for i, obj in enumerate(arr):
        if not isinstance(obj, dict):
            continue
        refs.append(
            EntryRef(
                source=source_key,
                index=i,
                item_id=str(obj.get("id", "")).strip(),
                name=str(obj.get("name", "")).strip(),
                story_file=str(obj.get("story_file", "")).strip(),
            )
        )
    return refs


def _scope_candidates(all_md_rel: list[str], entry: EntryRef) -> list[str]:
    # Bevorzugt passende Hauptkategorie.
    # assets -> Assets/, groups -> Gruppen/
    prefix = "Assets/" if entry.source == "assets" else "Gruppen/"
    scoped = [p for p in all_md_rel if p.startswith(prefix)]
    return scoped if scoped else all_md_rel


def _score_candidate(entry: EntryRef, cand: str) -> float:
    wanted = entry.story_file
    wanted_stem = Path(wanted).stem
    cand_stem = Path(cand).stem

    score = 0.0
    score += SequenceMatcher(None, _norm(wanted), _norm(cand)).ratio() * 50.0

    if _norm(wanted_stem) == _norm(cand_stem):
        score += 90.0

    if entry.item_id and _norm(entry.item_id) == _norm(cand_stem):
        score += 60.0

    if entry.name and _norm(entry.name) == _norm(cand_stem):
        score += 45.0

    if entry.item_id and _norm(entry.item_id) in _norm(cand):
        score += 10.0

    if entry.name and _norm(entry.name) in _norm(cand):
        score += 10.0

    wanted_parts = [p for p in Path(wanted).parts[:-1] if p]
    cand_parts = [p for p in Path(cand).parts[:-1] if p]
    shared = sum(1 for a, b in zip(wanted_parts, cand_parts) if _norm(a) == _norm(b))
    score += min(shared * 5.0, 20.0)

    # Wenn ein konkreter Seitenpfad auf ein Unterverzeichnis migriert wurde,
    # ist ein index.md im gleichen Verzeichnis ein starker Kandidat.
    wanted_parent = Path(wanted).parent.as_posix()
    cand_parent = Path(cand).parent.as_posix()
    if Path(cand).name.lower() == "index.md" and _norm(wanted_parent) == _norm(cand_parent):
        score += 25.0

    return score


def _best_candidates(entry: EntryRef, candidates: list[str], top_n: int = 5) -> list[tuple[str, float]]:
    ranked = [(c, _score_candidate(entry, c)) for c in candidates]
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:top_n]


def _set_story_file(payload: dict[str, Any], source_key: str, index: int, new_value: str) -> None:
    payload[source_key][index]["story_file"] = new_value


def run(args: argparse.Namespace) -> int:
    root = _repo_root()
    story_root = (root / args.story_root).resolve()
    assets_path = (root / args.assets_json).resolve()
    groups_path = (root / args.groups_json).resolve()
    report_path = (root / args.report).resolve()

    assets = _load_json(assets_path)
    groups = _load_json(groups_path)

    all_md_rel = sorted(
        p.relative_to(story_root).as_posix()
        for p in story_root.rglob("*.md")
        if p.is_file()
    )
    md_set = set(all_md_rel)

    entries = _collect_entries(assets, "assets") + _collect_entries(groups, "groups")
    missing: list[EntryRef] = [e for e in entries if e.story_file and e.story_file not in md_set]

    applied = 0
    unresolved = 0
    results: list[dict[str, Any]] = []

    for entry in missing:
        direct_target = KNOWN_RENAMES.get(entry.story_file, "")
        if direct_target and direct_target in md_set:
            if args.apply_best:
                if entry.source == "assets":
                    _set_story_file(assets, "assets", entry.index, direct_target)
                else:
                    _set_story_file(groups, "groups", entry.index, direct_target)
                applied += 1
                status = "applied_known_rename"
            else:
                unresolved += 1
                status = "suggested_known_rename"
            results.append(
                {
                    "source": entry.source,
                    "id": entry.item_id,
                    "name": entry.name,
                    "story_file_old": entry.story_file,
                    "status": status,
                    "best_match": direct_target,
                    "best_score": 999.0,
                    "candidates": [{"path": direct_target, "score": 999.0}],
                }
            )
            continue

        scoped = _scope_candidates(all_md_rel, entry)
        ranked = _best_candidates(entry, scoped, top_n=args.top_n)

        # Falls im Scope nichts Plausibles liegt, globalen Suchraum dazunehmen
        # (z. B. wenn ein Thema in einen anderen Bereich verschoben wurde).
        if not ranked or ranked[0][1] < args.cross_scope_threshold:
            ranked = _best_candidates(entry, all_md_rel, top_n=args.top_n)

        best_path = ranked[0][0] if ranked else None
        best_score = ranked[0][1] if ranked else 0.0
        unique_best = len(ranked) == 1 or (len(ranked) > 1 and ranked[0][1] > ranked[1][1] + 5.0)

        can_apply = (
            bool(best_path)
            and best_score >= args.min_score
            and unique_best
            and args.apply_best
        )

        if can_apply and best_path is not None:
            if entry.source == "assets":
                _set_story_file(assets, "assets", entry.index, best_path)
            else:
                _set_story_file(groups, "groups", entry.index, best_path)
            applied += 1
            status = "applied"
        else:
            unresolved += 1
            status = "suggested"

        results.append(
            {
                "source": entry.source,
                "id": entry.item_id,
                "name": entry.name,
                "story_file_old": entry.story_file,
                "status": status,
                "best_match": best_path,
                "best_score": round(best_score, 2),
                "candidates": [
                    {"path": c, "score": round(s, 2)}
                    for c, s in ranked
                ],
            }
        )

    if args.apply_best and applied > 0:
        _save_json(assets_path, assets)
        _save_json(groups_path, groups)

    report = {
        "total_entries": len(entries),
        "missing_story_files": len(missing),
        "applied": applied,
        "unresolved": unresolved,
        "min_score": args.min_score,
        "top_n": args.top_n,
        "results": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Total entries: {len(entries)}")
    print(f"Missing story_file: {len(missing)}")
    print(f"Applied fixes: {applied}")
    print(f"Unresolved: {unresolved}")
    print(f"Report: {report_path}")

    return 1 if unresolved > 0 and args.fail_on_unresolved else 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Audit/Cleanup fuer worldmodel story_file-Verweise."
    )
    ap.add_argument(
        "--story-root",
        default="content/story",
        help="Story-Root relativ zum Repo-Root (default: content/story).",
    )
    ap.add_argument(
        "--assets-json",
        default="weltdesign/worldmodel/assets.json",
        help="Pfad zu assets.json relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--groups-json",
        default="weltdesign/worldmodel/groups.json",
        help="Pfad zu groups.json relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Anzahl Kandidaten pro fehlendem Eintrag (default: 5).",
    )
    ap.add_argument(
        "--min-score",
        type=float,
        default=75.0,
        help="Mindestscore fuer Auto-Apply (default: 75).",
    )
    ap.add_argument(
        "--apply-best",
        action="store_true",
        help="Eindeutige, gute Treffer direkt in JSON schreiben.",
    )
    ap.add_argument(
        "--cross-scope-threshold",
        type=float,
        default=65.0,
        help="Unterhalb dieses Scores wird zusätzlich global gesucht (default: 65).",
    )
    ap.add_argument(
        "--fail-on-unresolved",
        action="store_true",
        help="Exit-Code 1, falls unresolved > 0.",
    )
    return ap.parse_args()


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()

