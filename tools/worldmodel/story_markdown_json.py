"""
Zusammenfassung:
- exportiert `content/story/` in ein einfaches, typisiertes `doomsday.json`
- ordnet die Inhalte den Bereichen `assets`, `gruppen`, `kanon` und `doomsday_radio` zu
- interpretiert Markdown-Ueberschriften als feste Felder pro Typ und fuellt fehlende Standardkapitel mit `TODO`
- kann aus dem JSON wieder einen normalisierten Markdown-Baum erzeugen

Liest:
- `content/story/**/*.md`

Schreibt:
- standardmaessig `weltdesign/worldmodel/doomsday.json`
- optional rekonstruierten Markdown-Baum unter `.tmp/doomsday_story_rebuild/`

Nutzungsbeispiele:
- `python tools/worldmodel/story_markdown_json.py`
- `python tools/worldmodel/story_markdown_json.py export --out weltdesign/worldmodel/doomsday.json`
- `python tools/worldmodel/story_markdown_json.py rebuild --json weltdesign/worldmodel/doomsday.json --output-root .tmp/doomsday_story_rebuild`
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FENCE_RX = re.compile(r"^```")
HEADING_RX = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
IMAGE_LINE_RX = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")


TEMPLATES: dict[str, dict[str, Any]] = {
    "gruppen_artikel": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "erscheinung_und_stil", "heading": "Erscheinung & Stil", "aliases": ["Erscheinung & Stil"]},
            {"key": "fraktionssignatur", "heading": "Fraktionssignatur", "aliases": ["Fraktionssignatur"]},
            {"key": "ziele_und_motivation", "heading": "Ziele & Motivation", "aliases": ["Ziele & Motivation"]},
            {"key": "faehigkeiten_und_staerken", "heading": "Fähigkeiten & Stärken", "aliases": ["Fähigkeiten & Stärken"]},
            {"key": "schwaechen", "heading": "Schwächen", "aliases": ["Schwächen"]},
            {"key": "besonderheiten", "heading": "Besonderheiten", "aliases": ["Besonderheiten"]},
            {"key": "rolle_in_der_doomsday_welt", "heading": "Rolle in der Doomsday-Welt", "aliases": ["Rolle in der Doomsday-Welt"]},
            {"key": "relevante_orte", "heading": "Relevante Orte", "aliases": ["Relevante Orte"]},
            {"key": "beziehungen_zu_anderen_fraktionen", "heading": "Beziehungen zu anderen Fraktionen", "aliases": ["Beziehungen zu anderen Fraktionen"]},
        ]
    },
    "asset_bau_artikel": {
        "fields": [
            {"key": "materialien_und_herkunft", "heading": "Materialien & Herkunft", "aliases": ["Materialien & Herkunft"]},
            {
                "key": "aufbau_oder_herstellung_und_anwendung",
                "heading": "Aufbau / Herstellung und Anwendung",
                "aliases": [
                    "Herstellung und Anwendung",
                    "Aufbau und Anwendung",
                    "Aufbau und Nutzung",
                    "Bau und Nutzung",
                    "Bau und Anwendung",
                ],
            },
        ]
    },
    "asset_gegenstand_artikel": {
        "fields": [
            {"key": "fakten", "heading": "Fakten", "aliases": ["Fakten"]},
            {"key": "formen_und_merkmale", "heading": "Formen & Merkmale", "aliases": ["Formen & Merkmale"]},
            {"key": "funktionsweise_und_nutzung", "heading": "Funktionsweise & Nutzung", "aliases": ["Funktionsweise & Nutzung"]},
            {"key": "rolle_in_der_welt", "heading": "Rolle in der Welt", "aliases": ["Rolle in der Welt"]},
            {"key": "stimmen_aus_der_wasteland", "heading": "Stimmen aus der Wasteland", "aliases": ["Stimmen aus der Wasteland"]},
        ]
    },
    "asset_handelsposten_artikel": {
        "fields": [
            {"key": "lage", "heading": "Lage", "aliases": ["Lage"]},
            {"key": "zuordnung", "heading": "Zuordnung", "aliases": ["Zuordnung"]},
            {"key": "schwerpunkt_und_angebot", "heading": "Schwerpunkt / Was es gibt", "aliases": ["Schwerpunkt / Was es gibt"]},
            {"key": "wer_sich_aufhaelt", "heading": "Wer sich aufhält", "aliases": ["Wer sich aufhält"]},
            {"key": "typische_gefahren", "heading": "Typische Gefahren", "aliases": ["Typische Gefahren"]},
            {"key": "besonderheiten_vor_ort", "heading": "Besonderheiten vor Ort", "aliases": ["Besonderheiten vor Ort"]},
        ]
    },
    "asset_pflanze_artikel": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "erscheinung_und_stil", "heading": "Erscheinung & Stil", "aliases": ["Erscheinung & Stil"]},
            {"key": "nutzen", "heading": "Nutzen", "aliases": ["Nutzen"]},
            {"key": "risiken", "heading": "Risiken", "aliases": ["Risiken"]},
            {"key": "relevante_orte", "heading": "Relevante Orte", "aliases": ["Relevante Orte"]},
            {"key": "beziehungen_zu_fraktionen", "heading": "Beziehungen zu Fraktionen", "aliases": ["Beziehungen zu Fraktionen"]},
            {"key": "stimmen_aus_der_wasteland", "heading": "Stimmen aus der Wasteland", "aliases": ["Stimmen aus der Wasteland"]},
        ]
    },
    "asset_rezept_artikel": {
        "fields": [
            {"key": "zutaten", "heading": "Zutaten", "aliases": ["Zutaten"]},
            {"key": "zubereitung", "heading": "Zubereitung", "aliases": ["Zubereitung"]},
        ]
    },
    "asset_satellit_artikel": {
        "fields": [
            {"key": "faehigkeit_fuer_den_stack", "heading": "Fähigkeit für den Stack", "aliases": ["Fähigkeit für den Stack"]},
            {"key": "typische_effekte", "heading": "Typische Effekte", "aliases": ["Typische Effekte"]},
            {"key": "grenzen", "heading": "Grenzen", "aliases": ["Grenzen"]},
            {"key": "rolle_in_der_welt", "heading": "Rolle in der Welt", "aliases": ["Rolle in der Welt"]},
        ]
    },
    "asset_tier_artikel": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "erscheinung_und_stil", "heading": "Erscheinung & Stil", "aliases": ["Erscheinung & Stil"]},
            {"key": "ziele_und_verhalten", "heading": "Ziele & Verhalten", "aliases": ["Ziele & Verhalten"]},
            {"key": "besonderheiten", "heading": "Besonderheiten", "aliases": ["Besonderheiten"]},
            {"key": "faehigkeiten_und_staerken", "heading": "Fähigkeiten & Stärken", "aliases": ["Fähigkeiten & Stärken"]},
            {"key": "schwaechen", "heading": "Schwächen", "aliases": ["Schwächen"]},
            {"key": "rolle_in_der_doomsday_welt", "heading": "Rolle in der Doomsday-Welt", "aliases": ["Rolle in der Doomsday-Welt"]},
            {"key": "relevante_orte", "heading": "Relevante Orte", "aliases": ["Relevante Orte"]},
            {"key": "beziehungen_zu_fraktionen", "heading": "Beziehungen zu Fraktionen", "aliases": ["Beziehungen zu Fraktionen"]},
            {"key": "stimmen_aus_der_wasteland", "heading": "Stimmen aus der Wasteland", "aliases": ["Stimmen aus der Wasteland"]},
        ]
    },
    "asset_zonen_artikel": {
        "fields": [
            {"key": "aufenthalt", "heading": "Aufenthalt", "aliases": ["Aufenthalt", "Wer sich dort aufhält"]},
            {"key": "gefahren", "heading": "Gefahren", "aliases": ["Gefahren"]},
            {"key": "zu_holen", "heading": "Zu holen", "aliases": ["Zu holen", "Was es dort zu holen gibt"]},
        ]
    },
    "timeline_artikel": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "kurzprofil", "heading": "Kurzprofil", "aliases": ["Kurzprofil"]},
            {"key": "zeitstufen", "heading": "Zeitstufen", "aliases": ["Zeitstufen"]},
            {"key": "vor_2026", "heading": "Vor 2026", "aliases": ["Vor 2026"]},
            {"key": "juni_2066_doomsday", "heading": "Juni 2066 - Doomsday", "aliases": ["Juni 2066 - Doomsday"]},
            {"key": "jetztzeit_2222", "heading": "2222 - Jetztzeit von Doomsday Radio", "aliases": ["2222 - Jetztzeit von Doomsday Radio"]},
            {
                "key": "zukuenftige_moeglichkeiten",
                "heading": "Zukünftige Möglichkeiten / konkurrierende Spekulationen",
                "aliases": ["Zukünftige Möglichkeiten / konkurrierende Spekulationen"],
            },
            {"key": "deutungen_und_konfliktlinien", "heading": "Deutungen & Konfliktlinien", "aliases": ["Deutungen & Konfliktlinien"]},
            {"key": "radiotaugliche_formen", "heading": "Radiotaugliche Formen", "aliases": ["Radiotaugliche Formen"]},
            {"key": "anschlussstellen", "heading": "Anschlussstellen", "aliases": ["Anschlussstellen"]},
            {"key": "offene_fragen", "heading": "Offene Fragen", "aliases": ["Offene Fragen"]},
        ]
    },
    "dispatcher_profil": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "erscheinung", "heading": "Erscheinung", "aliases": ["Erscheinung"]},
            {"key": "persoenlichkeit", "heading": "Persönlichkeit", "aliases": ["Persönlichkeit"]},
            {"key": "moderationsstil", "heading": "Moderationsstil", "aliases": ["Moderationsstil"]},
            {"key": "beispiele", "heading": "Beispiele", "aliases": ["Beispiele"]},
            {"key": "hintergrund", "heading": "Hintergrund", "aliases": ["Hintergrund"]},
            {"key": "sendung", "heading": "Sendung", "prefixes": ["Die Sendung:"]},
            {"key": "beziehungen", "heading": "Beziehungen", "aliases": ["Beziehungen"]},
        ]
    },
    "radio_bot_profil": {
        "fields": [
            {"key": "ueberblick", "heading": "Überblick", "aliases": ["Überblick"]},
            {"key": "persoenlichkeit_und_stil", "heading": "Persönlichkeit & Stil", "aliases": ["Persönlichkeit & Stil"]},
            {"key": "rolle_bei_doomsday_radio", "heading": "Rolle bei Doomsday Radio", "aliases": ["Rolle bei Doomsday Radio"]},
            {"key": "beziehungen_zu_den_fraktionen", "heading": "Beziehungen zu den Fraktionen", "aliases": ["Beziehungen zu den Fraktionen"]},
            {"key": "technische_rolle_prompt_konfiguration", "heading": "Technische Rolle (Prompt-Konfiguration)", "prefixes": ["Technische Rolle"]},
        ]
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_utf8_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_utf8_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


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


def _normalize_heading(value: str) -> str:
    normalized = (
        value.strip()
        .casefold()
        .replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _clean_block(text: str) -> str:
    cleaned = _strip_image_lines(text).strip()
    return cleaned if cleaned else "TODO"


def _strip_image_lines(text: str) -> str:
    kept_lines = [line for line in text.splitlines() if not IMAGE_LINE_RX.match(line.strip())]
    return "\n".join(kept_lines).strip()


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


def _parse_markdown(markdown_text: str, fallback_title: str) -> dict[str, Any]:
    lines = markdown_text.splitlines()
    headings = _extract_headings(markdown_text)
    title_heading = next((item for item in headings if item["level"] == 1), headings[0] if headings else None)
    title = title_heading["text"] if title_heading else fallback_title
    title_line = title_heading["line"] if title_heading else 0

    candidate_levels = [
        item["level"]
        for item in headings
        if item["line"] > title_line and item["level"] > (title_heading["level"] if title_heading else 0)
    ]
    section_level = min(candidate_levels) if candidate_levels else None
    section_headings = [
        item for item in headings if section_level is not None and item["line"] > title_line and item["level"] == section_level
    ]

    intro_start_index = title_line
    intro_end_index = section_headings[0]["line"] - 1 if section_headings else len(lines)
    intro = _strip_image_lines("\n".join(lines[intro_start_index:intro_end_index]))

    sections: list[dict[str, Any]] = []
    for heading in section_headings:
        next_line = len(lines) + 1
        for later_heading in headings:
            if later_heading["line"] <= heading["line"]:
                continue
            if later_heading["level"] <= section_level:
                next_line = later_heading["line"]
                break
        body_lines = lines[heading["line"] : next_line - 1]
        sections.append({"heading": heading["text"], "level": heading["level"], "content": "\n".join(body_lines).strip()})

    return {"title": title, "intro": intro, "sections": sections}


def _field_key_for_heading(article_type: str, heading: str) -> str | None:
    template = TEMPLATES.get(article_type)
    if template is None:
        return None
    normalized = _normalize_heading(heading)
    for field in template["fields"]:
        for alias in field.get("aliases", []):
            if normalized == _normalize_heading(alias):
                return field["key"]
        for prefix in field.get("prefixes", []):
            if normalized.startswith(_normalize_heading(prefix)):
                return field["key"]
    return None


def _base_article(
    *,
    path: str,
    title: str,
    article_type: str,
    area: str,
    section: str | None,
    category: str | None,
    intro: str,
    source_markdown: str,
) -> dict[str, Any]:
    return {
        "id": _slugify(path.removesuffix(".md")),
        "pfad": path,
        "titel": title,
        "typ": article_type,
        "bereich": area,
        "sektion": section,
        "kategorie": category,
        "einleitung": intro,
        "quelle_markdown": source_markdown,
    }


def _render_section(heading: str, content: str, level: int = 2) -> str:
    marker = "#" * level
    body = content.strip() if content.strip() else "TODO"
    return f"{marker} {heading}\n\n{body}"


def render_article(article: dict[str, Any]) -> str:
    parts = [f"# {article['titel']}"]
    intro = article.get("einleitung", "").strip()
    if intro:
        parts.extend(["", intro])

    article_type = article["typ"]
    if article_type in TEMPLATES:
        for field in TEMPLATES[article_type]["fields"]:
            parts.extend(["", _render_section(field["heading"], article.get(field["key"], "TODO"), 2)])
        for section in article.get("weitere_abschnitte", []):
            parts.extend(["", _render_section(section["ueberschrift"], section["inhalt"], section.get("ebene", 2))])
    else:
        sections = article.get("abschnitte", [])
        if not sections:
            sections = [{"ueberschrift": "Inhalt", "ebene": 2, "inhalt": "TODO"}]
        for section in sections:
            parts.extend(["", _render_section(section["ueberschrift"], section["inhalt"], section.get("ebene", 2))])

    return "\n".join(parts).rstrip() + "\n"


def _build_templated_article(
    *,
    path: str,
    title: str,
    article_type: str,
    area: str,
    section: str | None,
    category: str | None,
    intro: str,
    sections: list[dict[str, Any]],
    source_markdown: str,
) -> dict[str, Any]:
    article = _base_article(
        path=path,
        title=title,
        article_type=article_type,
        area=area,
        section=section,
        category=category,
        intro=intro,
        source_markdown=source_markdown,
    )
    for field in TEMPLATES[article_type]["fields"]:
        article[field["key"]] = "TODO"

    additional_sections: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for section_payload in sections:
        field_key = _field_key_for_heading(article_type, section_payload["heading"])
        content = _clean_block(section_payload["content"])
        if field_key is None or field_key in seen_keys:
            additional_sections.append(
                {
                    "ueberschrift": section_payload["heading"],
                    "ebene": section_payload["level"],
                    "inhalt": content,
                }
            )
            continue
        article[field_key] = content
        seen_keys.add(field_key)

    article["weitere_abschnitte"] = additional_sections
    article["markdown"] = render_article(article)
    return article


def _build_generic_article(
    *,
    path: str,
    title: str,
    article_type: str,
    area: str,
    section: str | None,
    category: str | None,
    intro: str,
    sections: list[dict[str, Any]],
    source_markdown: str,
) -> dict[str, Any]:
    article = _base_article(
        path=path,
        title=title,
        article_type=article_type,
        area=area,
        section=section,
        category=category,
        intro=intro,
        source_markdown=source_markdown,
    )
    article["abschnitte"] = [
        {
            "ueberschrift": item["heading"],
            "ebene": item["level"],
            "inhalt": _clean_block(item["content"]),
        }
        for item in sections
    ]
    if not article["abschnitte"]:
        article["abschnitte"] = [{"ueberschrift": "Inhalt", "ebene": 2, "inhalt": "TODO"}]
    article["markdown"] = render_article(article)
    return article


def _looks_like_timeline(sections: list[dict[str, Any]]) -> bool:
    normalized = {_normalize_heading(section["heading"]) for section in sections}
    return "kurzprofil" in normalized or "zeitstufen" in normalized


def _looks_like_radio_bot_profile(sections: list[dict[str, Any]]) -> bool:
    normalized = {_normalize_heading(section["heading"]) for section in sections}
    return "persoenlichkeit stil" in normalized or "rolle bei doomsday radio" in normalized


def _classify_article(relative_path: str, parsed: dict[str, Any]) -> tuple[str, str, str | None, str | None]:
    parts = relative_path.split("/")
    area = parts[0] if len(parts) > 1 else "root"
    section = parts[1] if len(parts) > 2 else None

    if relative_path == "index.md":
        return "sammlungsseite", "startseite", None, None
    if area == "Gruppen":
        if parts[-1] == "index.md":
            return "sammlungsseite", "gruppen", section, section
        return "gruppen_artikel", "gruppen", section, section
    if area == "Assets":
        if parts[-1] == "index.md":
            return "sammlungsseite", "assets", section, section
        assert section is not None
        mapping = {
            "Alltag": "asset_bau_artikel",
            "Arbeit": "asset_bau_artikel",
            "Medizin": "asset_bau_artikel",
            "Gegenstaende": "asset_gegenstand_artikel",
            "Handelsposten": "asset_handelsposten_artikel",
            "Pflanzen": "asset_pflanze_artikel",
            "Rezepte": "asset_rezept_artikel",
            "Sateliten": "asset_satellit_artikel",
            "Tiere": "asset_tier_artikel",
            "Zonen": "asset_zonen_artikel",
        }
        return mapping.get(section, "dokument"), "assets", section, section
    if area == "Kanon":
        if relative_path == "Kanon/glossar.md":
            return "kanon_dokument", "kanon", "Glossar", "Glossar"
        if parts[-1] == "index.md":
            return "sammlungsseite", "kanon", section, section
        if section == "Timeline" and _looks_like_timeline(parsed["sections"]):
            return "timeline_artikel", "kanon", section, section
        return "kanon_dokument", "kanon", section, section
    if area == "Radiostation":
        if parts[-1] == "index.md":
            return "sammlungsseite", "doomsday_radio", section, section
        if section == "dispatcher":
            return "dispatcher_profil", "doomsday_radio", section, section
        if section == "Radio-Bots" and _looks_like_radio_bot_profile(parsed["sections"]):
            return "radio_bot_profil", "doomsday_radio", section, section
        return "radio_dokument", "doomsday_radio", section, section
    return "dokument", "sonstiges", section, section


def _empty_area_payload(title: str) -> dict[str, Any]:
    return {"titel": title, "startseite": None}


def _empty_collection(title: str) -> dict[str, Any]:
    return {"titel": title, "startseite": None, "eintraege": []}


def _collection_key(value: str | None) -> str:
    return _slugify(value or "allgemein").replace("-", "_")


def _add_article_to_payload(payload: dict[str, Any], article: dict[str, Any]) -> None:
    path = article["pfad"]
    parts = path.split("/")

    if path == "index.md":
        payload["startseite"] = article
        return

    if article["bereich"] == "assets":
        if path == "Assets/index.md":
            payload["assets"]["startseite"] = article
            return
        category_key = _collection_key(article["sektion"])
        category = payload["assets"]["kategorien"].setdefault(
            category_key,
            _empty_collection(article["sektion"] or article["kategorie"] or category_key),
        )
        if parts[-1] == "index.md":
            category["startseite"] = article
        else:
            category["eintraege"].append(article)
        return

    if article["bereich"] == "gruppen":
        if path == "Gruppen/index.md":
            payload["gruppen"]["startseite"] = article
            return
        category_key = _collection_key(article["sektion"])
        category = payload["gruppen"]["linien"].setdefault(
            category_key,
            _empty_collection(article["sektion"] or category_key),
        )
        if parts[-1] == "index.md":
            category["startseite"] = article
        else:
            category["eintraege"].append(article)
        return

    if article["bereich"] == "kanon":
        if path == "Kanon/index.md":
            payload["kanon"]["startseite"] = article
            return
        if article["sektion"] == "Glossar":
            payload["kanon"]["glossar"] = article
            return
        category_key = _collection_key(article["sektion"])
        category = payload["kanon"]["bereiche"].setdefault(
            category_key,
            _empty_collection(article["sektion"] or category_key),
        )
        if parts[-1] == "index.md":
            category["startseite"] = article
        else:
            category["eintraege"].append(article)
        return

    if article["bereich"] == "doomsday_radio":
        if path == "Radiostation/index.md":
            payload["doomsday_radio"]["startseite"] = article
            return
        if article["sektion"] is None:
            payload["doomsday_radio"]["sender_dokumente"].append(article)
            return
        category_key = _collection_key(article["sektion"])
        category = payload["doomsday_radio"]["bereiche"].setdefault(
            category_key,
            _empty_collection(article["sektion"] or category_key),
        )
        if parts[-1] == "index.md":
            category["startseite"] = article
        else:
            category["eintraege"].append(article)
        return

    payload["sonstige_dokumente"].append(article)


def iter_articles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []

    def add(article: dict[str, Any] | None) -> None:
        if article is not None:
            articles.append(article)

    add(payload.get("startseite"))
    add(payload.get("assets", {}).get("startseite"))
    add(payload.get("gruppen", {}).get("startseite"))

    for collection in payload.get("assets", {}).get("kategorien", {}).values():
        add(collection.get("startseite"))
        articles.extend(collection.get("eintraege", []))

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
    return sorted(articles, key=lambda item: item["pfad"])


def build_story_payload(story_root: Path) -> dict[str, Any]:
    story_root = story_root.resolve()
    markdown_files = sorted(story_root.rglob("*.md"))

    payload: dict[str, Any] = {
        "version": 2,
        "generated_at": _utc_now(),
        "story_root": "content/story",
        "startseite": None,
        "assets": {
            **_empty_area_payload("Assets"),
            "kategorien": {},
        },
        "gruppen": {
            **_empty_area_payload("Gruppen"),
            "linien": {},
        },
        "kanon": {
            **_empty_area_payload("Kanon"),
            "glossar": None,
            "bereiche": {},
        },
        "doomsday_radio": {
            **_empty_area_payload("Doomsday Radio"),
            "sender_dokumente": [],
            "bereiche": {},
        },
        "sonstige_dokumente": [],
    }

    for markdown_path in markdown_files:
        relative_path = _relative_posix(markdown_path, story_root)
        source_markdown = _read_utf8_text(markdown_path)
        parsed = _parse_markdown(source_markdown, markdown_path.stem)
        article_type, area, section, category = _classify_article(relative_path, parsed)

        if article_type in TEMPLATES:
            article = _build_templated_article(
                path=relative_path,
                title=parsed["title"],
                article_type=article_type,
                area=area,
                section=section,
                category=category,
                intro=parsed["intro"],
                sections=parsed["sections"],
                source_markdown=source_markdown,
            )
        else:
            article = _build_generic_article(
                path=relative_path,
                title=parsed["title"],
                article_type=article_type,
                area=area,
                section=section,
                category=category,
                intro=parsed["intro"],
                sections=parsed["sections"],
                source_markdown=source_markdown,
            )

        _add_article_to_payload(payload, article)

    payload["statistik"] = {
        "markdown_dateien": len(iter_articles(payload)),
        "assets_eintraege": sum(len(collection["eintraege"]) for collection in payload["assets"]["kategorien"].values()),
        "gruppen_eintraege": sum(len(collection["eintraege"]) for collection in payload["gruppen"]["linien"].values()),
        "kanon_eintraege": sum(len(collection["eintraege"]) for collection in payload["kanon"]["bereiche"].values()),
        "radio_eintraege": len(payload["doomsday_radio"]["sender_dokumente"])
        + sum(len(collection["eintraege"]) for collection in payload["doomsday_radio"]["bereiche"].values()),
    }
    return payload


def write_story_payload(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _write_utf8_text(output_path, rendered)


def rebuild_story_from_payload(payload: dict[str, Any], output_root: Path) -> tuple[int, int]:
    articles = iter_articles(payload)
    directories = {
        str(Path(article["pfad"]).parent).replace("\\", "/")
        for article in articles
        if "/" in article["pfad"]
    }

    rebuilt_directories = 0
    for directory in sorted(path for path in directories if path and path != "."):
        (output_root / directory).mkdir(parents=True, exist_ok=True)
        rebuilt_directories += 1

    rebuilt_files = 0
    for article in articles:
        _write_utf8_text(output_root / article["pfad"], article["markdown"])
        rebuilt_files += 1

    return rebuilt_directories, rebuilt_files


def _load_payload(json_path: Path) -> dict[str, Any]:
    return json.loads(_read_utf8_text(json_path))


def export_command(args: argparse.Namespace) -> int:
    payload = build_story_payload(args.story_root)
    write_story_payload(payload, args.out)
    print(f"Wrote {args.out} ({payload['statistik']['markdown_dateien']} markdown files)")
    return 0


def rebuild_command(args: argparse.Namespace) -> int:
    payload = _load_payload(args.json)
    rebuilt_directories, rebuilt_files = rebuild_story_from_payload(payload, args.output_root)
    print(f"Rebuilt {rebuilt_files} markdown files in {args.output_root} ({rebuilt_directories} directories)")
    return 0


def parse_args() -> argparse.Namespace:
    repo_root = _repo_root()
    default_story_root = repo_root / "content" / "story"
    default_json_path = repo_root / "weltdesign" / "worldmodel" / "doomsday.json"
    default_rebuild_root = repo_root / ".tmp" / "doomsday_story_rebuild"

    parser = argparse.ArgumentParser(
        description=(
            "Export content/story into a simple, typed doomsday.json and rebuild "
            "the markdown folder structure from that JSON."
        )
    )
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export", help="Read content/story and write the structured doomsday.json export.")
    export_parser.add_argument("--story-root", type=Path, default=default_story_root, help="Story root to export (default: content/story).")
    export_parser.add_argument("--out", type=Path, default=default_json_path, help="Output JSON file (default: weltdesign/worldmodel/doomsday.json).")

    rebuild_parser = subparsers.add_parser("rebuild", help="Recreate the markdown files and directory structure from doomsday.json.")
    rebuild_parser.add_argument("--json", type=Path, default=default_json_path, help="Input JSON file (default: weltdesign/worldmodel/doomsday.json).")
    rebuild_parser.add_argument(
        "--output-root",
        type=Path,
        default=default_rebuild_root,
        help="Destination root for rebuilt markdown files (default: .tmp/doomsday_story_rebuild).",
    )

    args = parser.parse_args()
    if args.command is None:
        args.command = "export"
        args.story_root = default_story_root
        args.out = default_json_path
    return args


def main() -> None:
    args = parse_args()
    if args.command == "export":
        raise SystemExit(export_command(args))
    if args.command == "rebuild":
        raise SystemExit(rebuild_command(args))
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
