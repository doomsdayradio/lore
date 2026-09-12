from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


FENCE_RX = re.compile(r"^```")


def _strip_fenced_code(md_text: str) -> str:
    out: list[str] = []
    in_fence = False
    for raw in md_text.splitlines():
        line = raw.rstrip("\n")
        if FENCE_RX.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


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


def _safe_boundary_pattern(literal: str) -> re.Pattern[str]:
    # Avoid substring matches; keep Unicode-aware \w boundaries.
    # Note: This intentionally treats hyphen as non-word, which is fine for most titles.
    return re.compile(rf"(?<!\\w){re.escape(literal)}(?!\\w)", re.IGNORECASE)


REL_KEYWORDS: list[tuple[str, str]] = [
    # German-ish + a few English fallbacks; map to DB predicates.
    (r"\\bverb(ü|ue)ndet\\b|\\ballii?ert\\b", "ally"),
    (r"\\bfeind\\b|\\bgegner\\b|\\bhass(\\b|t|en)", "enemy"),
    (r"\\bhandel(n|t)\\b|\\btausch(en|t)\\b|\\bdeal(s)?\\b", "trades_with"),
    (r"\\bschuld(et|en)\\b|\\bschulden\\b|\\bowes?\\b|\\bdebt\\b", "owes_debt_to"),
    (r"\\bsch(ü|ue)tz(t|en)\\b|\\bbewach(t|en)\\b|\\bprotect(s)?\\b", "protects"),
    (r"\\bjagd\\b|\\bjagt\\b|\\bverfolgt\\b|\\bhunt(s)?\\b", "hunts"),
    (r"\\bkontroll(ier|iert|ieren)\\b|\\bdominier(t|en)\\b|\\bcontrol(s)?\\b", "controls"),
]


@dataclass(frozen=True)
class Group:
    group_id: str
    name: str
    aliases: list[str]
    story_file: str | None = None


@dataclass(frozen=True)
class Mention:
    src: str
    src_group_id: str | None
    target_group_id: str
    matched_alias: str
    rel_hints: list[str]


def _load_groups(groups_json_path: Path) -> list[Group]:
    payload = json.loads(groups_json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "groups" not in payload:
        raise SystemExit(f"Invalid groups json: {groups_json_path}")

    groups: list[Group] = []
    for g in payload["groups"]:
        groups.append(
            Group(
                group_id=str(g.get("id", "")).strip(),
                name=str(g.get("name", "")).strip(),
                aliases=_dedupe_keep_order([str(x) for x in (g.get("aliases") or [])]),
                story_file=str(g.get("story_file", "")).strip() or None,
            )
        )

    groups = [g for g in groups if g.group_id and g.name]
    return groups


def _story_file_index(groups: list[Group]) -> dict[str, str]:
    """Map story_file (posix relative) -> group_id."""
    idx: dict[str, str] = {}
    for g in groups:
        if g.story_file:
            idx[g.story_file] = g.group_id
    return idx


def _alias_collisions(groups: list[Group]) -> dict[str, list[str]]:
    seen: dict[str, str] = {}
    collisions: dict[str, list[str]] = {}
    for g in groups:
        for a in g.aliases:
            k = a.casefold()
            prev = seen.get(k)
            if prev and prev != g.group_id:
                collisions.setdefault(a, sorted({prev, g.group_id}))
            else:
                seen[k] = g.group_id
    return collisions


def _ambiguous_alias_keys(groups: list[Group]) -> set[str]:
    """Return casefolded aliases that map to more than one group."""
    owners: dict[str, set[str]] = {}
    for g in groups:
        for a in g.aliases:
            owners.setdefault(a.casefold(), set()).add(g.group_id)
    return {k for k, ids in owners.items() if len(ids) > 1}


def _classify_relationship_hints(text: str) -> list[str]:
    hints: list[str] = []
    for rx, pred in REL_KEYWORDS:
        if re.search(rx, text, flags=re.IGNORECASE):
            hints.append(pred)
    return sorted(set(hints))


def _iter_mentions_in_text(
    *,
    src_label: str,
    src_group_id: str | None,
    text: str,
    groups: list[Group],
    ambiguous_alias_keys: set[str] | None = None,
    ignore_self: bool = True,
) -> Iterable[Mention]:
    clean = _strip_fenced_code(text)
    rel_hints = _classify_relationship_hints(clean)

    for g in groups:
        if ignore_self and src_group_id and g.group_id == src_group_id:
            continue

        # Prefer longer aliases first to reduce partial overlaps.
        for alias in sorted(g.aliases, key=len, reverse=True):
            if ambiguous_alias_keys and alias.casefold() in ambiguous_alias_keys:
                continue
            if len(alias) < 3:
                continue
            if _safe_boundary_pattern(alias).search(clean):
                yield Mention(
                    src=src_label,
                    src_group_id=src_group_id,
                    target_group_id=g.group_id,
                    matched_alias=alias,
                    rel_hints=rel_hints,
                )
                break


MERMAID_NODE_RX = re.compile(r"\[([^\]]{2,80})\]")


def _extract_mermaid_blocks(md_text: str) -> list[str]:
    """Return contents of ```mermaid fenced blocks (without the fences)."""
    blocks: list[str] = []
    in_mermaid = False
    buf: list[str] = []
    for raw in md_text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not in_mermaid and stripped.lower().startswith("```mermaid"):
            in_mermaid = True
            buf = []
            continue

        if in_mermaid and stripped.startswith("```"):
            in_mermaid = False
            blocks.append("\n".join(buf))
            buf = []
            continue

        if in_mermaid:
            buf.append(line)
    return blocks


def _extract_mermaid_node_labels(md_text: str) -> list[str]:
    # Capture bracket labels like [ZEROS] *only* from Mermaid diagrams.
    labels: list[str] = []
    for block in _extract_mermaid_blocks(md_text):
        labels.extend([m.group(1).strip() for m in MERMAID_NODE_RX.finditer(block)])
    return _dedupe_keep_order(labels)


def main() -> None:
    ap = argparse.ArgumentParser(description="Check worlddesign group relationship consistency against story markdown.")
    ap.add_argument(
        "--groups-json",
        default=None,
        help="Path to groups.json (default: weltdesign/worldmodel/groups.json).",
    )
    ap.add_argument(
        "--story-root",
        default=None,
        help="Repo-relative or absolute path to story root (default: content/story).",
    )
    ap.add_argument("--dot", action="store_true", help="Print GraphViz DOT graph of detected mentions.")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Fail with exit code 1 on collisions, unknown mermaid labels, or asymmetries.",
    )
    ap.add_argument("--fail-on-collisions", action="store_true", help="Fail if alias collisions are found.")
    ap.add_argument(
        "--fail-on-unknown-labels",
        action="store_true",
        help="Fail if mermaid labels in main.md are not mapped by any alias.",
    )
    ap.add_argument("--fail-on-asymmetry", action="store_true", help="Fail if asymmetric mentions are found.")
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary/warnings and skip per-file mention listing.",
    )
    args = ap.parse_args()

    root = _repo_root()

    groups_json_path = Path(args.groups_json) if args.groups_json else (root / "weltdesign" / "worldmodel" / "groups.json")
    if not groups_json_path.is_absolute():
        groups_json_path = (root / groups_json_path).resolve()

    story_root = Path(args.story_root) if args.story_root else (root / "content" / "story")
    if not story_root.is_absolute():
        story_root = (root / story_root).resolve()

    story_groups_dir = story_root / "Gruppen"
    main_md = story_root / "main.md"

    if not groups_json_path.exists():
        raise SystemExit(
            f"Missing: {groups_json_path} "
            "(run tools/story_consistency/generate_groups_json.py first)"
        )
    if not story_groups_dir.exists():
        raise SystemExit(f"Missing: {story_groups_dir}")

    groups = _load_groups(groups_json_path)
    by_id = {g.group_id: g for g in groups}
    story_idx = _story_file_index(groups)

    collisions = _alias_collisions(groups)
    ambiguous_alias_keys = _ambiguous_alias_keys(groups)

    # Scan group pages + main.md for mentions
    mentions: dict[tuple[str, str, str | None], Mention] = {}

    for md_path in sorted(story_groups_dir.glob("*.md")):
        src_label = md_path.relative_to(root).as_posix()
        src_id = story_idx.get(md_path.relative_to(story_root).as_posix())
        text = md_path.read_text(encoding="utf-8")
        for m in _iter_mentions_in_text(
            src_label=src_label,
            src_group_id=src_id,
            text=text,
            groups=groups,
            ambiguous_alias_keys=ambiguous_alias_keys,
        ):
            key = (m.src, m.target_group_id, m.src_group_id)
            mentions[key] = m

    if main_md.exists():
        src_label = main_md.relative_to(root).as_posix()
        text = main_md.read_text(encoding="utf-8")
        for m in _iter_mentions_in_text(
            src_label=src_label,
            src_group_id=None,
            text=text,
            groups=groups,
            ambiguous_alias_keys=ambiguous_alias_keys,
            ignore_self=False,
        ):
            key = (m.src, m.target_group_id, m.src_group_id)
            mentions[key] = m

        # Consistency hint: Mermaid node labels not matching any alias.
        labels = _extract_mermaid_node_labels(text)
        alias_set = {a.casefold() for g in groups for a in g.aliases}
        unknown_labels = [lbl for lbl in labels if lbl.casefold() not in alias_set]
    else:
        unknown_labels = []

    # Output
    if args.dot:
        print("digraph groups {")
        print('  rankdir="LR";')
        for g in groups:
            label = g.name.replace('"', '\\"')
            print(f'  "{g.group_id}" [label="{label}"];')
        for m in sorted(mentions.values(), key=lambda x: (x.src, x.src_group_id or "", x.target_group_id)):
            # If we can infer src_group_id from file stem, draw edge; otherwise skip.
            if not m.src_group_id:
                continue
            edge_label = ",".join(m.rel_hints) if m.rel_hints else ""
            edge_label = edge_label.replace('"', '\\"')
            print(f'  "{m.src_group_id}" -> "{m.target_group_id}" [label="{edge_label}"];')
        print("}")
        return

    fail_on_collisions = args.fail_on_collisions or args.strict
    fail_on_unknown_labels = args.fail_on_unknown_labels or args.strict
    fail_on_asymmetry = args.fail_on_asymmetry or args.strict

    print(f"Groups: {len(groups)}")
    print(f"Mentions (edges): {len(mentions)}\n")

    if collisions:
        print("Alias collisions (same alias maps to multiple groups):")
        for alias, ids in sorted(collisions.items(), key=lambda x: x[0].casefold()):
            print(f"- {alias}: {', '.join(ids)}")
        print("")

    if unknown_labels:
        print("Unmapped labels in story/main.md (appear as [LABEL] but not in groups.json aliases):")
        for lbl in unknown_labels:
            print(f"- {lbl}")
        print("")

    if not args.summary_only:
        # Print mention list, grouped by source file
        by_src: dict[str, list[Mention]] = {}
        for m in mentions.values():
            by_src.setdefault(m.src, []).append(m)

        for src, ms in sorted(by_src.items(), key=lambda x: x[0]):
            print(f"{src}:")
            for m in sorted(ms, key=lambda x: x.target_group_id):
                target_name = by_id.get(m.target_group_id).name if m.target_group_id in by_id else m.target_group_id
                hints = ",".join(m.rel_hints) if m.rel_hints else "—"
                print(f"  -> {m.target_group_id} ({target_name})  matched={m.matched_alias!r}  hints={hints}")
            print("")

    # Asymmetry hint (only within group pages)
    group_edges = {(m.src_group_id, m.target_group_id) for m in mentions.values() if m.src_group_id}
    asym = sorted(
        [(a, b) for (a, b) in group_edges if a and (b, a) not in group_edges],
        key=lambda x: (x[0], x[1]),
    )
    if asym:
        print("Potential asymmetries (A mentions B, but B doesn't mention A):")
        for a, b in asym:
            print(f"- {a} -> {b}")

    failed_reasons: list[str] = []
    if fail_on_collisions and collisions:
        failed_reasons.append("alias collisions")
    if fail_on_unknown_labels and unknown_labels:
        failed_reasons.append("unknown mermaid labels")
    if fail_on_asymmetry and asym:
        failed_reasons.append("asymmetric mentions")

    if failed_reasons:
        print("")
        print("CHECK FAILED: " + ", ".join(failed_reasons))
        sys.exit(1)


if __name__ == "__main__":
    main()
