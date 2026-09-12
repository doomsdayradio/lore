"""
Zusammenfassung:
- fuehrt `doomsday.json` mit `assets.json`, `groups.json`, `kanon.json` und dem Bild-Manifest zusammen
- erzeugt daraus `worldbundle.json` als DB-freundliches Import-Bundle
- funktioniert sowohl mit dem alten als auch mit dem neuen, vereinfachten `doomsday.json`

Liest:
- `weltdesign/worldmodel/doomsday.json`
- `weltdesign/worldmodel/assets.json`
- `weltdesign/worldmodel/groups.json`
- `weltdesign/worldmodel/kanon.json`
- `weltdesign/worldmodel/generated-images/manifest.json`

Schreibt:
- standardmaessig `weltdesign/worldmodel/worldbundle.json`

Nutzungsbeispiele:
- `python tools/worldmodel/build_worldbundle.py`
- `python tools/worldmodel/build_worldbundle.py --out .tmp/worldbundle.json`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any


ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://doomsday.radio/worldbundle")
DEFAULT_WORLD_KEY = "doomsday-radio"
IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
FENCE_RX = re.compile(r"^```")
HEADING_RX = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MARKDOWN_LINK_RX = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
MARKDOWN_IMAGE_RX = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _split_target(raw_target: str) -> tuple[str, str | None, str | None]:
    target = raw_target.strip()
    query: str | None = None
    fragment: str | None = None

    hash_index = target.find("#")
    if hash_index != -1:
        fragment = target[hash_index + 1 :] or None
        target = target[:hash_index]

    query_index = target.find("?")
    if query_index != -1:
        query = target[query_index + 1 :] or None
        target = target[:query_index]

    return target, query, fragment


def _is_external_target(raw_target: str) -> bool:
    target = raw_target.strip().lower()
    if not target:
        return False
    if target.startswith(("http://", "https://", "mailto:", "data:", "tel:")):
        return True
    return "://" in target


def _candidate_paths(story_root: Path, docs_root: Path, source_file: Path, raw_target_path: str) -> list[Path]:
    target_path = raw_target_path.strip()
    if not target_path:
        return []

    if target_path.startswith("/"):
        base_path = story_root / target_path.lstrip("/")
    elif target_path.startswith("content/story/"):
        base_path = story_root / target_path[len("content/story/") :]
    elif target_path.startswith("docs/"):
        base_path = docs_root / target_path[len("docs/") :]
    else:
        base_path = source_file.parent / Path(target_path)

    candidates = [base_path]
    if not base_path.suffix:
        candidates.append(base_path.with_suffix(".md"))
        candidates.append(base_path / "index.md")
    return candidates


def _resolved_kind(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return "markdown"
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return "image"
    return "asset"


def _resolve_reference(
    *,
    story_root: Path,
    docs_root: Path,
    source_file: Path,
    raw_target: str,
) -> dict[str, Any]:
    target_path, query, fragment = _split_target(raw_target)
    is_external = _is_external_target(raw_target)
    is_anchor_only = raw_target.strip().startswith("#")

    metadata: dict[str, Any] = {
        "raw_target": raw_target,
        "target_path": target_path or None,
        "query": query,
        "fragment": fragment,
        "is_external": is_external,
        "is_anchor_only": is_anchor_only,
        "points_outside_story_root": False,
        "candidate_paths": [],
        "resolved_path": None,
        "resolved_exists": False,
        "resolved_kind": None,
    }

    if is_external or is_anchor_only or not target_path:
        return metadata

    candidates: list[str] = []
    for candidate in _candidate_paths(story_root, docs_root, source_file, target_path):
        resolved_candidate = candidate.resolve()
        try:
            relative_candidate = resolved_candidate.relative_to(story_root.resolve())
            candidate_path = relative_candidate.as_posix()
        except ValueError:
            try:
                relative_docs_candidate = resolved_candidate.relative_to(docs_root.resolve())
                candidate_path = (Path("docs") / relative_docs_candidate).as_posix()
            except ValueError:
                metadata["points_outside_story_root"] = True
                continue
        candidates.append(candidate_path)
        if metadata["resolved_path"] is None and candidate.exists():
            metadata["resolved_path"] = candidate_path
            metadata["resolved_exists"] = True
            metadata["resolved_kind"] = _resolved_kind(candidate)

    metadata["candidate_paths"] = candidates
    return metadata


def _extract_headings(markdown_text: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    in_fence = False
    for line_number, raw_line in enumerate(markdown_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if FENCE_RX.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RX.match(stripped)
        if not match:
            continue
        headings.append({"level": len(match.group(1)), "text": match.group(2).strip(), "line": line_number})
    return headings


def _extract_references(
    *,
    markdown_text: str,
    story_root: Path,
    docs_root: Path,
    source_file: Path,
    pattern: re.Pattern[str],
    label_key: str,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for match in pattern.finditer(markdown_text):
        reference = _resolve_reference(
            story_root=story_root,
            docs_root=docs_root,
            source_file=source_file,
            raw_target=match.group(2).strip(),
        )
        references.append({label_key: match.group(1), "line": _line_number(markdown_text, match.start()), **reference})
    return references


def _story_assets(story_root: Path) -> list[Path]:
    return [path for path in sorted(story_root.rglob("*")) if path.is_file() and path.suffix.lower() != ".md"]


def _stable_id(kind: str, key: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, f"{kind}:{key}"))


def _slugify(value: str) -> str:
    s = value.strip().casefold()
    s = (
        s.replace("ß", "ss")
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
    )
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "item"


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _iter_new_doomsday_articles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []

    def add(article: dict[str, Any] | None) -> None:
        if article is not None:
            articles.append(article)

    add(payload.get("startseite"))
    add(payload.get("assets", {}).get("startseite"))
    for collection in payload.get("assets", {}).get("kategorien", {}).values():
        add(collection.get("startseite"))
        articles.extend(collection.get("eintraege", []))

    add(payload.get("gruppen", {}).get("startseite"))
    for collection in payload.get("gruppen", {}).get("linien", {}).values():
        add(collection.get("startseite"))
        articles.extend(collection.get("eintraege", []))

    kanon = payload.get("kanon", {})
    add(kanon.get("startseite"))
    add(kanon.get("glossar"))
    for collection in kanon.get("bereiche", {}).values():
        add(collection.get("startseite"))
        articles.extend(collection.get("eintraege", []))

    radio = payload.get("doomsday_radio", {})
    add(radio.get("startseite"))
    articles.extend(radio.get("sender_dokumente", []))
    for collection in radio.get("bereiche", {}).values():
        add(collection.get("startseite"))
        articles.extend(collection.get("eintraege", []))

    articles.extend(payload.get("sonstige_dokumente", []))
    return sorted((article for article in articles if article is not None), key=lambda item: item["pfad"])


def _markdown_documents_from_doomsday(doomsday: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    if "markdown_files" in doomsday:
        return doomsday["markdown_files"]

    story_root = (repo_root / doomsday.get("story_root", "content/story")).resolve()
    docs_root = (repo_root / "docs").resolve()
    documents: list[dict[str, Any]] = []
    for article in _iter_new_doomsday_articles(doomsday):
        path = article["pfad"]
        content = article.get("markdown") or article.get("quelle_markdown") or ""
        raw_bytes = content.encode("utf-8")
        source_path = story_root / path
        headings = _extract_headings(content)
        links = _extract_references(
            markdown_text=content,
            story_root=story_root,
            docs_root=docs_root,
            source_file=source_path,
            pattern=MARKDOWN_LINK_RX,
            label_key="label",
        )
        images = _extract_references(
            markdown_text=content,
            story_root=story_root,
            docs_root=docs_root,
            source_file=source_path,
            pattern=MARKDOWN_IMAGE_RX,
            label_key="alt_text",
        )
        local_assets = sorted(
            {
                ref["resolved_path"]
                for ref in [*links, *images]
                if ref.get("resolved_path") and ref.get("resolved_kind") in {"image", "asset"}
            }
        )
        documents.append(
            {
                "path": path,
                "directory": source_path.parent.relative_to(story_root).as_posix(),
                "file_name": source_path.name,
                "stem": source_path.stem,
                "sha256": _sha256_bytes(raw_bytes),
                "byte_length": len(raw_bytes),
                "line_count": len(content.splitlines()),
                "title": article.get("titel"),
                "headings": headings,
                "references": {
                    "links": links,
                    "images": images,
                    "local_asset_paths": local_assets,
                },
                "content": content,
            }
        )
    return documents


def _media_assets_from_story_root(doomsday: dict[str, Any], repo_root: Path) -> list[dict[str, Any]]:
    if isinstance(doomsday.get("assets"), list):
        return doomsday["assets"]

    story_root = (repo_root / doomsday.get("story_root", "content/story")).resolve()
    asset_usage: dict[str, set[str]] = {}
    for document in _markdown_documents_from_doomsday(doomsday, repo_root):
        for asset_path in document["references"].get("local_asset_paths", []):
            asset_usage.setdefault(asset_path, set()).add(document["path"])

    assets: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    def add_asset(asset_path: Path, relative_path: str) -> None:
        if relative_path in seen_paths:
            return
        raw_bytes = asset_path.read_bytes()
        mime_type, _ = mimetypes.guess_type(asset_path.name)
        assets.append(
            {
                "path": relative_path,
                "directory": Path(relative_path).parent.as_posix() if Path(relative_path).parent.as_posix() != "." else "",
                "file_name": asset_path.name,
                "extension": asset_path.suffix.lower(),
                "kind": "image" if asset_path.suffix.lower() in IMAGE_EXTENSIONS else "asset",
                "mime_type": mime_type,
                "byte_length": len(raw_bytes),
                "sha256": _sha256_bytes(raw_bytes),
                "referenced_from_markdown": sorted(asset_usage.get(relative_path, set())),
            }
        )
        seen_paths.add(relative_path)

    for asset_path in _story_assets(story_root):
        relative_path = asset_path.relative_to(story_root).as_posix()
        add_asset(asset_path, relative_path)

    for relative_path in sorted(asset_usage):
        if relative_path in seen_paths:
            continue
        asset_path = repo_root / relative_path
        if not asset_path.is_file():
            continue
        add_asset(asset_path, relative_path)

    return assets


def _document_kind(path: str) -> str:
    parts = path.split("/")
    if path == "index.md":
        return "world_root"
    if parts[0] == "Gruppen":
        return "group_index" if parts[-1] == "index.md" else "faction"
    if parts[0] == "Kanon":
        if len(parts) > 1 and parts[1] == "Timeline":
            return "timeline_index" if parts[-1] == "index.md" else "timeline_event"
        if len(parts) > 1 and parts[1] == "Konflikte":
            return "conflict_index" if parts[-1] == "index.md" else "conflict"
        if len(parts) > 1 and parts[1] == "Gesetze":
            return "law_index" if parts[-1] == "index.md" else "law"
        if parts[-1] == "glossar.md":
            return "glossary"
        return "kanon_index" if parts[-1] == "index.md" else "kanon_topic"
    if parts[0] == "Radiostation":
        if len(parts) > 1 and parts[1] == "dispatcher":
            return "character_index" if parts[-1] == "index.md" else "character"
        if len(parts) > 1 and parts[1] == "Radio-Bots":
            return "radio_bot_index" if parts[-1] == "index.md" else "radio_bot"
        if len(parts) > 1 and parts[1] == "Musik":
            return "music_index" if parts[-1] == "index.md" else "music_act"
        if len(parts) > 1 and parts[1] == "Programm":
            return "radio_program_index" if parts[-1] == "index.md" else "radio_program"
        return "radio_station"
    if parts[0] == "Assets":
        if len(parts) == 2 and parts[-1] == "index.md":
            return "asset_root"
        if parts[-1] == "index.md":
            return "asset_category"
        section = parts[1] if len(parts) > 1 else ""
        mapping = {
            "Handelsposten": "location",
            "Zonen": "location",
            "Gegenstaende": "item",
            "Medizin": "item",
            "Rezepte": "recipe",
            "Pflanzen": "flora",
            "Tiere": "creature",
            "Sateliten": "system",
            "Alltag": "asset_detail",
            "Arbeit": "asset_detail",
        }
        return mapping.get(section, "asset_detail")
    return "document"


def _entity_type_from_story_file(path: str) -> str:
    kind = _document_kind(path)
    mapping = {
        "faction": "faction",
        "character": "character",
        "radio_bot": "bot",
        "location": "location",
        "item": "item",
        "recipe": "item",
        "flora": "flora",
        "creature": "creature",
        "system": "system",
        "law": "rule",
        "timeline_event": "event",
        "conflict": "event",
        "radio_program": "radio_program",
        "music_act": "music_act",
        "kanon_topic": "kanon_topic",
        "glossary": "glossary_term",
    }
    return mapping.get(kind, "document")


def _anchor_slug(text: str) -> str:
    return _slugify(text)


def _split_sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    lines = document["content"].splitlines()
    headings = document.get("headings", [])
    if not headings:
        return [
            {
                "ordinal": 0,
                "heading": None,
                "level": None,
                "anchor_slug": None,
                "start_line": 1 if lines else None,
                "end_line": len(lines) if lines else None,
                "markdown": document["content"],
                "plaintext": "\n".join(line.strip() for line in lines if line.strip()) or None,
            }
        ]

    sections: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        start_line = heading["line"]
        end_line = headings[index + 1]["line"] - 1 if index + 1 < len(headings) else len(lines)
        markdown = "\r\n".join(lines[start_line - 1 : end_line])
        if document["content"].endswith("\n") and end_line == len(lines):
            markdown += "\r\n"
        sections.append(
            {
                "ordinal": index,
                "heading": heading["text"],
                "level": heading["level"],
                "anchor_slug": _anchor_slug(heading["text"]),
                "start_line": start_line,
                "end_line": end_line,
                "markdown": markdown,
                "plaintext": "\n".join(
                    line.strip() for line in lines[start_line - 1 : end_line] if line.strip()
                )
                or None,
            }
        )
    return sections


def _section_id_for_line(section_ranges: list[tuple[int, int, str]], line_number: int | None) -> str | None:
    if line_number is None:
        return None
    for start_line, end_line, section_id in section_ranges:
        if start_line <= line_number <= end_line:
            return section_id
    return None


class BundleBuilder:
    def __init__(
        self,
        *,
        repo_root: Path,
        doomsday: dict[str, Any],
        assets: dict[str, Any],
        groups: dict[str, Any],
        kanon: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        self.repo_root = repo_root
        self.doomsday = doomsday
        self.assets_json = assets
        self.groups_json = groups
        self.kanon_json = kanon
        self.manifest_json = manifest
        self.world_id = _stable_id("world", DEFAULT_WORLD_KEY)
        self.markdown_documents = _markdown_documents_from_doomsday(doomsday, repo_root)
        self.story_assets = _media_assets_from_story_root(doomsday, repo_root)
        self.documents_by_path: dict[str, dict[str, Any]] = {}
        self.media_by_path: dict[str, dict[str, Any]] = {}
        self.entity_by_story_file: dict[str, dict[str, Any]] = {}
        self.entity_by_source_key: dict[tuple[str, str], dict[str, Any]] = {}
        self.bundle: dict[str, Any] = {}

    def build(self) -> dict[str, Any]:
        documents, sections = self._build_documents_and_sections()
        self.bundle["sections"] = sections
        media_assets = self._build_media_assets()
        links, media_usages, validation_issues = self._build_links_and_media_usages()
        entities, entity_aliases, entity_sources, entity_prompts = self._build_entities()
        entity_media, media_generations, extra_issues = self._build_media_generation_data()
        entity_relations = self._build_entity_relations()
        validation_issues.extend(extra_issues)

        source_inputs = self._build_source_inputs()
        bundle_id = _stable_id(
            "bundle",
            "|".join(item["sha256"] or item["path"] for item in source_inputs),
        )
        stats = {
            "documents": len(documents),
            "sections": len(sections),
            "links": len(links),
            "media_assets": len(media_assets),
            "entities": len(entities),
            "entity_prompts": len(entity_prompts),
            "media_generations": len(media_generations),
            "validation_issues": len(validation_issues),
        }

        self.bundle = {
            "schema_version": "1.0.0",
            "bundle_id": bundle_id,
            "generated_at": self.doomsday.get("generated_at"),
            "world": {
                "world_id": self.world_id,
                "world_key": DEFAULT_WORLD_KEY,
                "name": "Doomsday Radio",
                "primary_language": "de-DE",
                "source_story_root": self.doomsday.get("story_root", "content/story"),
                "description": "Merged story/worldmodel import bundle for Doomsday Radio.",
                "metadata": {"stats": stats},
            },
            "source_inputs": source_inputs,
            "import_hints": {"replace_world_on_import": True, "stats": stats},
            "documents": documents,
            "sections": sections,
            "links": links,
            "media_assets": media_assets,
            "media_usages": media_usages,
            "entities": entities,
            "entity_aliases": entity_aliases,
            "entity_sources": entity_sources,
            "entity_relations": entity_relations,
            "entity_prompts": entity_prompts,
            "entity_media": entity_media,
            "media_generations": media_generations,
            "validation_issues": validation_issues,
        }
        return self.bundle

    def _build_source_inputs(self) -> list[dict[str, Any]]:
        inputs = [
            ("doomsday_json", self.repo_root / "weltdesign" / "worldmodel" / "doomsday.json"),
            ("assets_json", self.repo_root / "weltdesign" / "worldmodel" / "assets.json"),
            ("groups_json", self.repo_root / "weltdesign" / "worldmodel" / "groups.json"),
            ("kanon_json", self.repo_root / "weltdesign" / "worldmodel" / "kanon.json"),
            (
                "generated_images_manifest",
                self.repo_root / "weltdesign" / "worldmodel" / "generated-images" / "manifest.json",
            ),
        ]
        out: list[dict[str, Any]] = []
        for source_name, path in inputs:
            payload = _load_json(path)
            out.append(
                {
                    "source_name": source_name,
                    "path": path.relative_to(self.repo_root).as_posix(),
                    "sha256": _sha256_file(path),
                    "generated_at": payload.get("generated_at"),
                    "metadata": {"top_level_keys": sorted(payload.keys())},
                }
            )
        return out

    def _build_documents_and_sections(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        documents: list[dict[str, Any]] = []
        sections: list[dict[str, Any]] = []
        for document in self.markdown_documents:
            path = document["path"]
            document_id = _stable_id("document", path)
            primary_media_asset_id = None
            if document["references"]["images"]:
                resolved = document["references"]["images"][0].get("resolved_path")
                if resolved:
                    primary_media_asset_id = _stable_id("media", resolved)
            bundle_document = {
                "document_id": document_id,
                "path": path,
                "file_name": document["file_name"],
                "stem": document["stem"],
                "title": document.get("title"),
                "document_kind": _document_kind(path),
                "path_parts": path.split("/"),
                "directory": document.get("directory"),
                "story_file": path,
                "sha256": document["sha256"],
                "byte_length": document["byte_length"],
                "line_count": document["line_count"],
                "primary_media_asset_id": primary_media_asset_id,
                "raw_markdown": document["content"],
                "metadata": {
                    "headings": document.get("headings", []),
                    "local_asset_paths": document["references"].get("local_asset_paths", []),
                },
            }
            self.documents_by_path[path] = bundle_document
            documents.append(bundle_document)

            for section in _split_sections(document):
                section_id = _stable_id("section", f"{path}:{section['ordinal']}")
                sections.append(
                    {
                        "section_id": section_id,
                        "document_id": document_id,
                        **section,
                        "metadata": {},
                    }
                )
        return documents, sections

    def _build_media_assets(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for asset in self.story_assets:
            media_id = _stable_id("media", asset["path"])
            bundle_asset = {
                "media_id": media_id,
                "path": asset["path"],
                "story_file": None,
                "file_name": asset["file_name"],
                "extension": asset.get("extension"),
                "mime_type": asset.get("mime_type"),
                "media_kind": asset["kind"],
                "sha256": asset.get("sha256"),
                "byte_length": asset.get("byte_length"),
                "metadata": {
                    "directory": asset.get("directory"),
                    "referenced_from_markdown": asset.get("referenced_from_markdown", []),
                },
            }
            self.media_by_path[asset["path"]] = bundle_asset
            out.append(bundle_asset)
        return out

    def _build_links_and_media_usages(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        section_ranges_by_document: dict[str, list[tuple[int, int, str]]] = {}
        for section in self.bundle.get("sections", []):
            start_line = section.get("start_line")
            end_line = section.get("end_line")
            if start_line is None or end_line is None:
                continue
            section_ranges_by_document.setdefault(section["document_id"], []).append(
                (start_line, end_line, section["section_id"])
            )

        links: list[dict[str, Any]] = []
        media_usages: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for document in self.markdown_documents:
            document_id = _stable_id("document", document["path"])
            section_ranges = section_ranges_by_document.get(document_id, [])

            all_refs = [
                ("link", index, ref)
                for index, ref in enumerate(document["references"]["links"])
            ] + [
                ("image", index, ref)
                for index, ref in enumerate(document["references"]["images"])
            ]

            embedded_image_count = 0
            linked_asset_count = 0
            for ref_kind, index, ref in all_refs:
                raw_target = ref["raw_target"]
                resolved_path = ref.get("resolved_path")
                resolved_kind = ref.get("resolved_kind")
                link_kind = "unknown"
                if ref.get("is_external"):
                    link_kind = "external"
                elif ref.get("is_anchor_only"):
                    link_kind = "anchor"
                elif resolved_kind == "markdown":
                    link_kind = "document"
                elif resolved_kind == "image":
                    link_kind = "image"
                elif resolved_kind == "asset":
                    link_kind = "asset"

                link_id = _stable_id("link", f"{document['path']}:{ref_kind}:{index}:{raw_target}")
                target_document_id = (
                    _stable_id("document", resolved_path) if resolved_kind == "markdown" and resolved_path else None
                )
                target_media_id = (
                    _stable_id("media", resolved_path)
                    if resolved_kind in {"image", "asset"} and resolved_path
                    else None
                )
                section_id = _section_id_for_line(section_ranges, ref.get("line"))
                links.append(
                    {
                        "link_id": link_id,
                        "document_id": document_id,
                        "section_id": section_id,
                        "line_number": ref.get("line"),
                        "link_kind": link_kind,
                        "label": ref.get("label"),
                        "alt_text": ref.get("alt_text"),
                        "raw_target": raw_target,
                        "target_document_id": target_document_id,
                        "target_media_id": target_media_id,
                        "target_url": raw_target if ref.get("is_external") else None,
                        "target_fragment": ref.get("fragment"),
                        "resolved_path": resolved_path,
                        "resolved_kind": resolved_kind,
                        "metadata": {
                            "candidate_paths": ref.get("candidate_paths", []),
                            "points_outside_story_root": ref.get("points_outside_story_root", False),
                        },
                    }
                )

                if target_media_id and ref_kind == "image":
                    media_usages.append(
                        {
                            "usage_id": _stable_id("usage", f"{document['path']}:embedded:{embedded_image_count}:{resolved_path}"),
                            "document_id": document_id,
                            "media_id": target_media_id,
                            "link_id": link_id,
                            "usage_kind": "embedded",
                            "ordinal": embedded_image_count,
                            "line_number": ref.get("line"),
                            "alt_text": ref.get("alt_text"),
                            "caption": None,
                            "metadata": {},
                        }
                    )
                    embedded_image_count += 1
                elif target_media_id and ref_kind == "link":
                    media_usages.append(
                        {
                            "usage_id": _stable_id("usage", f"{document['path']}:linked:{linked_asset_count}:{resolved_path}"),
                            "document_id": document_id,
                            "media_id": target_media_id,
                            "link_id": link_id,
                            "usage_kind": "linked_file",
                            "ordinal": linked_asset_count,
                            "line_number": ref.get("line"),
                            "alt_text": None,
                            "caption": ref.get("label"),
                            "metadata": {},
                        }
                    )
                    linked_asset_count += 1

                if not ref.get("resolved_exists") and not ref.get("is_external") and not ref.get("is_anchor_only"):
                    issues.append(
                        {
                            "issue_id": _stable_id("issue", f"unresolved:{document['path']}:{index}:{raw_target}"),
                            "document_id": document_id,
                            "section_id": section_id,
                            "entity_id": None,
                            "media_id": target_media_id,
                            "issue_type": "unresolved_reference",
                            "severity": "warning",
                            "message": f"Reference could not be resolved: {raw_target}",
                            "metadata": {"link_id": link_id, "resolved_path": resolved_path},
                        }
                    )

        for media in self.story_assets:
            if media.get("referenced_from_markdown"):
                continue
            issues.append(
                {
                    "issue_id": _stable_id("issue", f"unreferenced-media:{media['path']}"),
                    "document_id": None,
                    "section_id": None,
                    "entity_id": None,
                    "media_id": _stable_id("media", media["path"]),
                    "issue_type": "unreferenced_media_asset",
                    "severity": "info",
                    "message": f"Media asset is currently not referenced from markdown: {media['path']}",
                    "metadata": {},
                }
            )

        return links, media_usages, issues

    def _ensure_entity(
        self,
        *,
        source_name: str,
        source_key: str,
        story_file: str | None,
        canonical_name: str,
        entity_type: str,
        origin: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.entity_by_story_file.get(story_file) if story_file else None
        if existing is None:
            existing = self.entity_by_source_key.get((source_name, source_key))
        if existing is not None:
            existing["metadata"].update(metadata or {})
            return existing

        entity_key = source_key if origin != "inferred_from_document" else f"doc:{source_key}"
        entity = {
            "entity_id": _stable_id("entity", entity_key),
            "entity_key": entity_key,
            "entity_type": entity_type,
            "canonical_name": canonical_name,
            "display_name": canonical_name,
            "status": "active",
            "summary": None,
            "description_markdown": None,
            "origin": origin,
            "metadata": metadata or {},
        }
        if story_file:
            self.entity_by_story_file[story_file] = entity
        self.entity_by_source_key[(source_name, source_key)] = entity
        return entity

    @staticmethod
    def _dedupe_records(records: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            marker = _dump_json([record.get(key) for key in keys])
            if marker in seen:
                continue
            seen.add(marker)
            out.append(record)
        return out

    def _build_entities(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        aliases: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        prompts: list[dict[str, Any]] = []

        for item in self.assets_json.get("assets", []):
            story_file = item["story_file"]
            entity = self._ensure_entity(
                source_name="assets_json",
                source_key=item["id"],
                story_file=story_file,
                canonical_name=item["name"],
                entity_type=_entity_type_from_story_file(story_file),
                origin="assets_json",
                metadata={"category": item.get("category")},
            )
            doc = self.documents_by_path.get(story_file)
            if doc:
                entity["description_markdown"] = doc["raw_markdown"]
                entity["summary"] = doc.get("title")
            sources.append(
                {
                    "entity_source_id": _stable_id("entity-source", f"assets_json:{item['id']}"),
                    "entity_id": entity["entity_id"],
                    "document_id": doc["document_id"] if doc else None,
                    "source_name": "assets_json",
                    "source_record_key": item["id"],
                    "story_file": story_file,
                    "is_primary": True,
                    "confidence": 1.0,
                    "metadata": {"category": item.get("category")},
                }
            )
            aliases.append(
                {
                    "alias_id": _stable_id("entity-alias", f"{entity['entity_id']}:{item['id']}"),
                    "entity_id": entity["entity_id"],
                    "alias": item["id"],
                    "normalized_alias": _slugify(item["id"]),
                    "alias_type": "source_id",
                    "source_name": "assets_json",
                    "metadata": {},
                }
            )
            if item.get("image_description"):
                prompts.append(
                    {
                        "prompt_id": _stable_id("entity-prompt", f"{entity['entity_id']}:image_description:{item['id']}"),
                        "entity_id": entity["entity_id"],
                        "prompt_type": "image_description",
                        "prompt_text": item["image_description"],
                        "source_name": "assets_json",
                        "source_record_key": item["id"],
                        "story_file": story_file,
                        "is_current": True,
                        "metadata": {"category": item.get("category")},
                    }
                )

        for item in self.groups_json.get("groups", []):
            story_file = item["story_file"]
            entity = self._ensure_entity(
                source_name="groups_json",
                source_key=item["id"],
                story_file=story_file,
                canonical_name=item["name"],
                entity_type="faction",
                origin="groups_json",
                metadata={},
            )
            doc = self.documents_by_path.get(story_file)
            if doc:
                entity["description_markdown"] = doc["raw_markdown"]
                entity["summary"] = doc.get("title")
            sources.append(
                {
                    "entity_source_id": _stable_id("entity-source", f"groups_json:{item['id']}"),
                    "entity_id": entity["entity_id"],
                    "document_id": doc["document_id"] if doc else None,
                    "source_name": "groups_json",
                    "source_record_key": item["id"],
                    "story_file": story_file,
                    "is_primary": True,
                    "confidence": 1.0,
                    "metadata": {},
                }
            )
            for alias in item.get("aliases", []):
                aliases.append(
                    {
                        "alias_id": _stable_id("entity-alias", f"{entity['entity_id']}:{alias}"),
                        "entity_id": entity["entity_id"],
                        "alias": alias,
                        "normalized_alias": _slugify(alias),
                        "alias_type": "canonical" if alias == item["name"] else "alternate",
                        "source_name": "groups_json",
                        "metadata": {},
                    }
                )

        for item in self.kanon_json.get("kanon", []):
            story_file = item["story_file"]
            entity = self._ensure_entity(
                source_name="kanon_json",
                source_key=item["id"],
                story_file=story_file,
                canonical_name=item["name"],
                entity_type="kanon_topic",
                origin="kanon_json",
                metadata={"category": item.get("category")},
            )
            doc = self.documents_by_path.get(story_file)
            if doc:
                entity["description_markdown"] = doc["raw_markdown"]
                entity["summary"] = doc.get("title")
            sources.append(
                {
                    "entity_source_id": _stable_id("entity-source", f"kanon_json:{item['id']}"),
                    "entity_id": entity["entity_id"],
                    "document_id": doc["document_id"] if doc else None,
                    "source_name": "kanon_json",
                    "source_record_key": item["id"],
                    "story_file": story_file,
                    "is_primary": True,
                    "confidence": 1.0,
                    "metadata": {"category": item.get("category")},
                }
            )

        for path, doc in self.documents_by_path.items():
            if path in self.entity_by_story_file:
                continue
            if doc.get("document_kind") in {"asset_root", "group_index", "kanon_index", "world_root"}:
                continue
            entity = self._ensure_entity(
                source_name="doomsday_json",
                source_key=path,
                story_file=path,
                canonical_name=doc.get("title") or doc["stem"],
                entity_type=_entity_type_from_story_file(path),
                origin="inferred_from_document",
                metadata={"document_kind": doc.get("document_kind")},
            )
            entity["description_markdown"] = doc["raw_markdown"]
            entity["summary"] = doc.get("title")
            sources.append(
                {
                    "entity_source_id": _stable_id("entity-source", f"doomsday_json:{path}"),
                    "entity_id": entity["entity_id"],
                    "document_id": doc["document_id"],
                    "source_name": "doomsday_json",
                    "source_record_key": path,
                    "story_file": path,
                    "is_primary": True,
                    "confidence": 0.6,
                    "metadata": {"document_kind": doc.get("document_kind")},
                }
            )

        entities = sorted(
            self.entity_by_source_key.values(),
            key=lambda item: (item["entity_type"], item["canonical_name"]),
        )
        return (
            entities,
            self._dedupe_records(aliases, ["entity_id", "alias"]),
            self._dedupe_records(sources, ["entity_id", "source_name", "source_record_key"]),
            self._dedupe_records(prompts, ["entity_id", "prompt_type", "source_name", "source_record_key"]),
        )

    def _build_media_generation_data(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        entity_media: list[dict[str, Any]] = []
        media_generations: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for path, entity in self.entity_by_story_file.items():
            doc = self.documents_by_path.get(path)
            if not doc or not doc.get("primary_media_asset_id"):
                continue
            entity_media.append(
                {
                    "entity_media_id": _stable_id("entity-media", f"{entity['entity_id']}:{doc['primary_media_asset_id']}:primary"),
                    "entity_id": entity["entity_id"],
                    "media_id": doc["primary_media_asset_id"],
                    "media_role": "primary",
                    "sort_order": 0,
                    "source_name": "doomsday_json",
                    "metadata": {},
                }
            )

        defaults = {
            "model": self.manifest_json.get("model"),
            "size": self.manifest_json.get("size"),
            "quality": self.manifest_json.get("quality"),
        }
        for item in self.manifest_json.get("items", []):
            story_file = item.get("story_file")
            entity = self.entity_by_story_file.get(story_file) if story_file else None
            output_path = item.get("file")
            media_id = None
            if output_path and output_path.startswith("content/story/"):
                relative_media_path = output_path[len("content/story/") :]
                media = self.media_by_path.get(relative_media_path)
                media_id = media["media_id"] if media else None
            if entity and media_id:
                entity_media.append(
                    {
                        "entity_media_id": _stable_id("entity-media", f"{entity['entity_id']}:{media_id}:generated"),
                        "entity_id": entity["entity_id"],
                        "media_id": media_id,
                        "media_role": "generated",
                        "sort_order": 0,
                        "source_name": "generated_images_manifest",
                        "metadata": {"status": item.get("status")},
                    }
                )
            media_generations.append(
                {
                    "generation_id": _stable_id("media-generation", f"{item.get('type')}:{item.get('id')}:{output_path}"),
                    "entity_id": entity["entity_id"] if entity else None,
                    "media_id": media_id,
                    "source_name": "generated_images_manifest",
                    "source_record_key": f"{item.get('type')}:{item.get('id')}",
                    "model": defaults["model"],
                    "size": defaults["size"],
                    "quality": defaults["quality"],
                    "status": item.get("status", "unknown"),
                    "output_path": output_path,
                    "story_file": story_file,
                    "metadata": {"type": item.get("type"), "name": item.get("name")},
                }
            )
            if story_file and entity is None:
                issues.append(
                    {
                        "issue_id": _stable_id("issue", f"manifest-without-entity:{story_file}:{item.get('id')}"),
                        "document_id": self.documents_by_path.get(story_file, {}).get("document_id"),
                        "section_id": None,
                        "entity_id": None,
                        "media_id": media_id,
                        "issue_type": "manifest_entity_missing",
                        "severity": "warning",
                        "message": f"Manifest item could not be matched to an entity: {story_file}",
                        "metadata": {"source_record_key": item.get("id")},
                    }
                )

        return (
            self._dedupe_records(entity_media, ["entity_id", "media_id", "media_role"]),
            media_generations,
            issues,
        )

    def _build_entity_relations(self) -> list[dict[str, Any]]:
        relations: list[dict[str, Any]] = []
        for story_file, entity in self.entity_by_story_file.items():
            doc = next((item for item in self.markdown_documents if item["path"] == story_file), None)
            if doc is None:
                continue
            for link in doc["references"]["links"]:
                resolved_path = link.get("resolved_path")
                if not resolved_path:
                    continue
                target_entity = self.entity_by_story_file.get(resolved_path)
                if not target_entity:
                    continue
                relations.append(
                    {
                        "relation_id": _stable_id("entity-relation", f"{entity['entity_id']}:{target_entity['entity_id']}:{story_file}:{link['line']}:{link['raw_target']}"),
                        "from_entity_id": entity["entity_id"],
                        "to_entity_id": target_entity["entity_id"],
                        "relation_type": "references",
                        "directionality": "directed",
                        "confidence": 0.5,
                        "evidence_document_id": self.documents_by_path[story_file]["document_id"],
                        "evidence_section_id": None,
                        "evidence_note": link.get("label"),
                        "metadata": {"line_number": link.get("line")},
                    }
                )
        return self._dedupe_records(
            relations,
            ["relation_id"],
        )


def build_bundle(
    *,
    repo_root: Path,
    doomsday_path: Path,
    assets_path: Path,
    groups_path: Path,
    kanon_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    builder = BundleBuilder(
        repo_root=repo_root,
        doomsday=_load_json(doomsday_path),
        assets=_load_json(assets_path),
        groups=_load_json(groups_path),
        kanon=_load_json(kanon_path),
        manifest=_load_json(manifest_path),
    )
    return builder.build()


def parse_args() -> argparse.Namespace:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Build a merged worldbundle.json from doomsday.json and other worldmodel JSON sources."
    )
    parser.add_argument("--doomsday", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "doomsday.json")
    parser.add_argument("--assets", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "assets.json")
    parser.add_argument("--groups", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "groups.json")
    parser.add_argument("--kanon", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "kanon.json")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repo_root / "weltdesign" / "worldmodel" / "generated-images" / "manifest.json",
    )
    parser.add_argument("--out", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "worldbundle.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = build_bundle(
        repo_root=_repo_root(),
        doomsday_path=args.doomsday,
        assets_path=args.assets,
        groups_path=args.groups,
        kanon_path=args.kanon,
        manifest_path=args.manifest,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {args.out} "
        f"(documents={len(bundle['documents'])}, entities={len(bundle['entities'])}, "
        f"media_assets={len(bundle['media_assets'])})"
    )


if __name__ == "__main__":
    main()
