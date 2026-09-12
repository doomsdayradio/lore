# pylint: disable=too-many-lines
"""
Generiert statische Lore-HTML aus content/story nach docs/story/lore.

- docs/story/lore/index.html wird als teaserartige Startseite erzeugt
  (alle Topics als Karten mit Kurztext + Detail-Popup).
- Für jedes Markdown wird zusätzlich eine Detailseite generiert.
- Alle Bilder aus content/story werden nach docs/story/lore gespiegelt.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

try:
    import markdown
except ImportError:
    raise SystemExit(
        "Das Modul 'markdown' fehlt. Bitte installieren: pip install markdown"
    ) from None


H1_RX = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
FENCE_RX = re.compile(r"^```")
TIMELINE_MILESTONE_RX = re.compile(
    r"^\s*-\s+\*\*(?P<stamp>\d{4}(?:-\d{2})?(?:-\d{2})?(?:[ T]\d{2}(?::\d{2})?)?)\s*\|\s*(?P<title>.+?)(?::)?\*\*\s*:?\s*(?P<summary>.+?)\s*$"
)
MD_LINK_RX = re.compile(r"\]\s*\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
MD_IMG_RX = re.compile(r"!\[[^\]]*\]\s*\(\s*([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
INLINE_TAG_RX = re.compile(r"<[^>]+>")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")
AUDIO_EXTENSIONS = (".mp3",)
STORY_MEDIA_EXTENSIONS = {*(e.lower() for e in IMAGE_EXTENSIONS), *(e.lower() for e in AUDIO_EXTENSIONS)}
GENERATED_OUTPUT_EXTENSIONS = {".html", ".css", ".json", ".js", *IMAGE_EXTENSIONS, *AUDIO_EXTENSIONS}
LORE_CSS_FILES = {
    "detail": Path("site-assets/css/lore-detail.css"),
    "overview": Path("site-assets/css/lore-overview.css"),
    "timeline": Path("site-assets/css/lore-timeline.css"),
}
STYLE_BLOCK_RX = re.compile(r"\n  <style>\n(?P<css>.*?)\n  </style>\n", re.DOTALL)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _timeline_audio_sources(repo_root: Path) -> list[dict[str, str]]:
    music_dir = repo_root / "content" / "story" / "Kanon" / "Timeline" / "music"
    if not music_dir.is_dir():
        return []
    tracks: list[dict[str, str]] = []
    for path in sorted(music_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        title = path.stem.replace("-", " ").replace("_", " ").strip()
        tracks.append(
            {
                "src": f"music/{quote(path.name)}",
                "title": title,
            }
        )
    return tracks


def _run_worldmodel_image_step(
    *,
    repo_root: Path,
    generate_images: bool,
    images_overwrite: bool,
    images_limit: int | None,
    images_model: str | None,
    images_size: str | None,
) -> None:
    """
    Startet immer einen Dry-Check der Bildgenerierung.
    Echte Bildgenerierung nur, wenn --generate-images gesetzt ist.
    """
    tool = repo_root / "tools" / "worldmodel" / "generate_worldmodel_images.py"
    if not tool.is_file():
        print("Hinweis: generate_worldmodel_images.py nicht gefunden, ueberspringe Bild-Check.")
        return

    cmd = [sys.executable, str(tool)]
    if generate_images:
        if images_overwrite:
            cmd.append("--overwrite")
        if images_limit is not None:
            cmd.extend(["--limit", str(images_limit)])
        if images_model:
            cmd.extend(["--model", images_model])
        if images_size:
            cmd.extend(["--size", images_size])
        print("Bildgenerierung aktiv (per Parameter).")
    else:
        cmd.append("--dry-run")
        print("Bildgenerierung-Check (dry-run) wird ausgefuehrt.")

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout.strip():
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        if proc.stderr.strip():
            print(proc.stderr.rstrip())
        mode = "Bildgenerierung" if generate_images else "Bild-Check"
        raise SystemExit(f"{mode} fehlgeschlagen (Exit-Code {proc.returncode}).")
    if proc.stderr.strip():
        print(proc.stderr.rstrip())


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _css_variant_for_output(out_rel: Path) -> str:
    if out_rel == Path("index.html"):
        return "overview"
    if out_rel == Path("Kanon") / "Timeline" / "index.html":
        return "timeline"
    return "detail"


def _externalize_single_style_block(html: str, css_href: str) -> tuple[str, str | None]:
    match = STYLE_BLOCK_RX.search(html)
    if not match:
        return html, None
    css_text = match.group("css").strip("\n") + "\n"
    link_tag = f'\n  <link rel="stylesheet" href="{_escape_html(css_href)}" />\n'
    externalized = html[: match.start()] + link_tag + html[match.end() :]
    return externalized, css_text


def _render_inline_markdown(text: str) -> str:
    """
    Rendert bewusst nur einfache Inline-Markdown-Muster fuer Kurztexte.
    Aktuell: **bold** / __bold__ / *italic* / _italic_
    """
    rendered = _escape_html(text)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"__(.+?)__", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", rendered)
    rendered = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", rendered)
    rendered = rendered.replace("\n", "<br>")
    return rendered


def _slugify(s: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return cleaned or "topic"


def _relative_href(from_dir: Path, to_file: Path) -> str:
    return Path(os.path.relpath(to_file, from_dir)).as_posix()


def _split_link_suffix(url: str) -> tuple[str, str]:
    """
    Trennt URL-Pfad von optionalem Query/Fragment.
    Beispiel: "foo/bar.md#x" -> ("foo/bar.md", "#x")
    """
    for sep in ("#", "?"):
        idx = url.find(sep)
        if idx != -1:
            return url[:idx], url[idx:]
    return url, ""


def _read_markdown_title(md_text: str) -> str | None:
    in_fence = False
    for line in md_text.splitlines():
        stripped = line.strip()
        if FENCE_RX.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = H1_RX.match(stripped)
        if m:
            return m.group(1).strip() or None
    return None


def _resolve_story_target(
    url: str,
    *,
    current_md_rel: Path,
    story_root: Path,
    for_markdown: bool,
) -> Path | None:
    if not url or url.startswith(("http://", "https://", "mailto:", "#", "data:")):
        return None
    url_path, _ = _split_link_suffix(url)
    if not url_path:
        return None
    normalized_path = url_path.lstrip("/")
    if normalized_path.startswith("content/story/"):
        target_rel = Path(normalized_path[len("content/story/") :])
    else:
        current_dir = (story_root / current_md_rel).parent
        try:
            target_full = (current_dir / url_path).resolve()
        except (OSError, ValueError):
            return None
        try:
            target_rel = target_full.relative_to(story_root)
        except ValueError:
            return None
    if for_markdown:
        if target_rel.suffix != ".md":
            target_rel = target_rel / "index.md"
    return target_rel


def _resolve_docs_target(
    url: str,
    *,
    current_md_rel: Path,
    story_root: Path,
    docs_root: Path,
) -> Path | None:
    if not url or url.startswith(("http://", "https://", "mailto:", "#", "data:")):
        return None
    url_path, _ = _split_link_suffix(url)
    if not url_path:
        return None
    normalized_path = url_path.lstrip("/")
    if normalized_path.startswith("docs/"):
        target_rel = Path(normalized_path[len("docs/") :])
        target_full = docs_root / target_rel
    else:
        current_dir = (story_root / current_md_rel).parent
        try:
            target_full = (current_dir / url_path).resolve()
        except (OSError, ValueError):
            return None
        try:
            target_full.relative_to(docs_root)
        except ValueError:
            return None
    if not target_full.exists():
        return None
    return target_full


def _rewrite_md_links(
    md_text: str,
    *,
    current_md_rel: Path,
    story_root: Path,
    output_root: Path,
    md_to_html: dict[str, Path],
    out_path: Path,
    public_base_dir: Path | None = None,
    docs_root: Path | None = None,
) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(1).strip()
        url_path, suffix = _split_link_suffix(url)
        link_base = public_base_dir if public_base_dir is not None else out_path.parent
        if Path(url_path.replace("\\", "/")).name == "glossar.md" and suffix.startswith("#"):
            glossary_target = GLOSSARY_TARGETS.get(suffix[1:])
            if glossary_target is not None:
                mapped = md_to_html.get(glossary_target)
                if mapped is not None:
                    new_href = _relative_href(link_base, output_root / mapped)
                    return "]({})".format(new_href)
        target_rel = _resolve_story_target(
            url_path,
            current_md_rel=current_md_rel,
            story_root=story_root,
            for_markdown=True,
        )
        if target_rel is None:
            if docs_root is None:
                return match.group(0)
            docs_target = _resolve_docs_target(
                url_path,
                current_md_rel=current_md_rel,
                story_root=story_root,
                docs_root=docs_root,
            )
            if docs_target is None or not docs_target.is_file():
                return match.group(0)
            new_href = _relative_href(link_base, docs_target) + suffix
            return "]({})".format(new_href)
        mapped = md_to_html.get(target_rel.as_posix())
        if mapped is None:
            return match.group(0)
        new_href = _relative_href(link_base, output_root / mapped) + suffix
        return "]({})".format(new_href)

    return MD_LINK_RX.sub(repl, md_text)


def _rewrite_public_glossary_links(text: str) -> str:
    """Entfernt alte Glossarpfade aus öffentlichen Rohtext-Exporten."""
    def map_url(label: str, url: str) -> str:
        url_path, suffix = _split_link_suffix(url)
        if Path(url_path.replace("\\", "/")).name != "glossar.md":
            return ""
        target = GLOSSARY_TARGETS.get(suffix[1:]) if suffix.startswith("#") else None
        if target is None:
            return label
        return f"[{label}](../{target}{suffix})"

    markdown_rx = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    html_rx = re.compile(r'<a\s+href=["\']([^"\']+)["\']>(.*?)</a>', re.IGNORECASE)
    text = markdown_rx.sub(lambda match: map_url(match.group(1), match.group(2)) or match.group(0), text)
    return html_rx.sub(
        lambda match: map_url(match.group(2), match.group(1)) or match.group(0),
        text,
    )


def _rewrite_public_text(value: object) -> object:
    if isinstance(value, str):
        return _rewrite_public_glossary_links(value)
    if isinstance(value, list):
        return [_rewrite_public_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_public_text(item) for key, item in value.items()}
    return value


def _rewrite_md_images(
    md_text: str,
    *,
    current_md_rel: Path,
    story_root: Path,
    output_root: Path,
    out_path: Path,
    public_base_dir: Path | None = None,
    docs_root: Path | None = None,
) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(1).strip()
        url_path, suffix = _split_link_suffix(url)
        link_base = public_base_dir if public_base_dir is not None else out_path.parent
        target_rel = _resolve_story_target(
            url_path,
            current_md_rel=current_md_rel,
            story_root=story_root,
            for_markdown=False,
        )
        if target_rel is not None:
            src_file = story_root / target_rel
            if not src_file.is_file() or src_file.suffix.lower() not in IMAGE_EXTENSIONS:
                return match.group(0)
            new_src = _relative_href(link_base, output_root / target_rel) + suffix
            return match.group(0).replace(url, new_src, 1)
        if docs_root is None:
            return match.group(0)
        src_file = _resolve_docs_target(
            url_path,
            current_md_rel=current_md_rel,
            story_root=story_root,
            docs_root=docs_root,
        )
        if src_file is None or not src_file.is_file() or src_file.suffix.lower() not in IMAGE_EXTENSIONS:
            return match.group(0)
        new_src = _relative_href(link_base, src_file) + suffix
        return match.group(0).replace(url, new_src, 1)

    return MD_IMG_RX.sub(repl, md_text)


def _strip_housekeeping_lines(md_text: str) -> str:
    ignored_prefixes = (
        "zentrales charakterprofil:",
    )
    filtered_lines: list[str] = []
    for raw in md_text.splitlines():
        if raw.strip().lower().startswith(ignored_prefixes):
            continue
        filtered_lines.append(raw)
    return "\n".join(filtered_lines)


def _extract_overview(md_text: str, *, max_length: int | None = 240) -> str:
    lines: list[str] = []
    in_fence = False
    ignored_prefixes = (
        "zentrales charakterprofil:",
        "detailprofil:",
        "konfliktprofil:",
    )
    for raw in md_text.splitlines():
        line = raw.strip()
        if FENCE_RX.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if line.lower().startswith(ignored_prefixes):
            continue
        if line.startswith("#") or line.startswith(">"):
            continue
        if line.startswith("- ") or line.startswith("* ") or line.startswith("|"):
            continue
        lines.append(line)
        if max_length is not None and len(" ".join(lines)) > (max_length + 20):
            break
    joined = "\n".join(lines) if max_length is None else " ".join(lines)
    plain = INLINE_TAG_RX.sub("", joined)
    # Markdown-Bilder nie als Fliesstext uebernehmen (z. B. "!dddradiologo")
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", plain)
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\s+[\"'][^\"']*[\"']\)", "", plain)
    plain = re.sub(r"\[(.*?)\]\([^)]+\)", r"\1", plain)
    if max_length is None:
        normalized_lines = [
            re.sub(r"\s+", " ", ln).strip() for ln in plain.splitlines() if ln.strip()
        ]
        plain = "\n".join(normalized_lines)
    else:
        plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return "Signal vorhanden. Details im Popup."
    if max_length is not None and len(plain) > max_length:
        return plain[: max_length - 3].rstrip() + "..."
    return plain


def _extract_slogan(md_text: str) -> str | None:
    in_fence = False
    in_signatur = False
    for raw in md_text.splitlines():
        line = raw.strip()
        if FENCE_RX.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            in_signatur = heading == "fraktionssignatur"
            continue
        if not in_signatur:
            continue
        if line.startswith(("- **Slogan:**", "* **Slogan:**")):
            slogan = re.sub(r"^[*-]\s+\*\*Slogan:\*\*\s*", "", line).strip()
            if slogan.startswith(("“", '"')) and slogan.endswith(("”", '"')):
                slogan = slogan[1:-1].strip()
            if not slogan or slogan.lower().startswith("keiner"):
                return None
            return slogan
    return None


def _index_summary(
    index_overview_by_dir: dict[tuple[str, ...], str], key: tuple[str, ...]
) -> str:
    return index_overview_by_dir.get(key, "")


def _topic_count_label(count: int) -> str:
    return f"{count} Topic" if count == 1 else f"{count} Topics"


SECTION_ORDER = {
    "Weltkern": 0,
    "Kanon": 1,
    "Charaktere": 2,
    "Radiostation": 3,
    "Gruppen": 4,
    "Assets": 5,
}

GLOSSARY_TARGETS = {
    "beacons": "Assets/Sateliten/index.md",
    "der-orden": "Gruppen/Orden/letzte-migration.md",
    "der-stack": "Gruppen/DerStack/index.md",
    "doomsday-dispatcher": "Charaktere/index.md",
    "doomsday-radio": "Radio/index.md",
    "echo-1": "Radio/Bots/Echo-1.md",
    "geocache": "Gruppen/Roamer/geocacher.md",
    "geocacher": "Gruppen/Roamer/geocacher.md",
    "gerichtskirche": "Orte/Zonen/Gerichtskirche.md",
    "handelsposten": "Orte/Handelsposten/index.md",
    "hardliner": "Gruppen/Roamer/hardliner.md",
    "hillbillys": "Gruppen/Roamer/hillbillys.md",
    "human-in-the-loop-prinzip": "Gruppen/Orden/looper.md",
    "killcoin": "Assets/Gegenstaende/Killcoins.md",
    "looper": "Gruppen/Orden/looper.md",
    "mad-dog": "Charaktere/Mad-Dog.md",
    "magier": "Gruppen/Maker/magier.md",
    "maker": "Gruppen/Maker/index.md",
    "nullapostell": "Radio/Bots/Nullapostell.md",
    "orden": "Gruppen/Orden/index.md",
    "piep-matze": "Radio/Bots/piep-matze.md",
    "promptanwaelte": "Orte/Zonen/index.md",
    "rasti": "Charaktere/Rasti.md",
    "retros": "Gruppen/Orden/retros.md",
    "roamer": "Gruppen/Roamer/index.md",
    "satelliten": "Assets/Sateliten/Aufklaerungs-Satelliten.md",
    "scrip": "Assets/Gegenstaende/Scrip-Zero-Gutscheine.md",
    "spotnik": "Radio/Bots/spotnik.md",
    "stackcast": "Gruppen/DerStack/StackCast.md",
    "stack-gericht": "Kanon/Gesetze/Stack-Gericht.md",
    "steampunks": "Gruppen/Maker/steampunks.md",
    "stranded-stranglers": "Orte/Sonstiges/Stranded-Stranglers.md",
    "the-shop": "Orte/Handelsposten/The-Shop.md",
    "thermobot-9": "Radio/Bots/ThermoBot-9.md",
    "uno-orakel": "Radio/Bots/uno-orakel.md",
    "verseuchte-zonen": "Orte/Zonen/index.md",
    "viktor-weiss": "Charaktere/Viktor-Weiss.md",
    "wasteland": "index.md",
    "zero-percentler": "Gruppen/Zeros/index.md",
    "zeros": "Gruppen/Zeros/index.md",
}


def _section_sort_key(section_name: str) -> tuple[int, str]:
    return (SECTION_ORDER.get(section_name, 999), section_name.lower())


def _display_subsection_name(section_name: str, subsection_name: str) -> str:
    if section_name != "Assets" and subsection_name == "Allgemein":
        return "Uebersicht"
    return subsection_name


def _remove_first_image_with_src(html: str, src: str) -> str:
    escaped = re.escape(src)
    wrapped = re.compile(
        rf"<p>\s*<img[^>]*src=[\"']{escaped}[\"'][^>]*>\s*</p>",
        re.IGNORECASE,
    )
    updated, n = wrapped.subn("", html, count=1)
    if n:
        return updated
    inline = re.compile(rf"<img[^>]*src=[\"']{escaped}[\"'][^>]*>", re.IGNORECASE)
    updated, _ = inline.subn("", html, count=1)
    return updated


def _topic_images(md_path: Path, md_text: str, story_root: Path) -> list[Path]:
    rel = md_path.relative_to(story_root)
    images: list[Path] = []
    seen: set[str] = set()

    current_dir = (story_root / rel).parent
    for m in MD_IMG_RX.finditer(md_text):
        url = m.group(1).strip()
        target_rel = _resolve_story_target(
            url,
            current_md_rel=rel,
            story_root=story_root,
            for_markdown=False,
        )
        if target_rel is None:
            continue
        src = story_root / target_rel
        if src.is_file() and src.suffix.lower() in IMAGE_EXTENSIONS:
            key = target_rel.as_posix()
            if key not in seen:
                seen.add(key)
                images.append(target_rel)

    if images:
        return images

    # Prioritaet: Bilddateien mit gleichem Stem wie die Markdown-Datei.
    stem = md_path.stem.lower()
    preferred: list[Path] = []
    fallback: list[Path] = []

    for ext in IMAGE_EXTENSIONS:
        for img in sorted(current_dir.glob(f"*{ext}")):
            rel_img = img.relative_to(story_root)
            key = rel_img.as_posix()
            if key in seen:
                continue
            seen.add(key)
            if img.stem.lower() == stem:
                preferred.append(rel_img)
            else:
                fallback.append(rel_img)

    images.extend(preferred)
    # Fuer index.md-Seiten kein beliebiges Nachbarbild als Hero erben.
    if md_path.stem.lower() != "index":
        images.extend(fallback)
    return images


def _group_banner_image(md_path: Path, story_root: Path) -> Path | None:
    rel = md_path.relative_to(story_root)
    if not rel.parts or rel.parts[0] != "Gruppen":
        return None

    current_dir = md_path.parent
    banner_stem = f"{md_path.stem}-banner"
    for ext in IMAGE_EXTENSIONS:
        candidate = current_dir / f"{banner_stem}{ext}"
        if candidate.is_file():
            return candidate.relative_to(story_root)
    return None


def _detail_gallery_images(md_path: Path, story_root: Path) -> list[Path]:
    if md_path.stem.lower() == "index":
        return []

    current_dir = md_path.parent
    pattern = re.compile(rf"^{re.escape(md_path.stem)}(\d+)$", re.IGNORECASE)
    numbered: list[tuple[int, Path]] = []

    for candidate in sorted(current_dir.iterdir()):
        if not candidate.is_file() or candidate.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        match = pattern.match(candidate.stem)
        if not match:
            continue
        numbered.append((int(match.group(1)), candidate.relative_to(story_root)))

    numbered.sort(key=lambda item: item[0])
    return [path for _, path in numbered]


def _copy_lore_logo(story_root: Path, output_root: Path) -> None:
    src = story_root / "ddd_radio_logo.png"
    if not src.is_file():
        return
    teaser_assets = output_root.parent / "teaser" / "assets"
    teaser_assets.mkdir(parents=True, exist_ok=True)
    dest = teaser_assets / "ddd_radio_logo.png"
    if dest != src and (not dest.exists() or dest.stat().st_mtime != src.stat().st_mtime):
        shutil.copy2(src, dest)


def _copy_all_story_media(story_root: Path, output_root: Path, *, check: bool) -> int:
    if check:
        return 0
    copied = 0
    for src in story_root.rglob("*"):
        if not src.is_file() or src.suffix.lower() not in STORY_MEDIA_EXTENSIONS:
            continue
        rel = src.relative_to(story_root)
        dest = output_root / rel
        if dest != src and (not dest.exists() or dest.stat().st_mtime != src.stat().st_mtime):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
    return copied


def _postprocess_html_links(html: str) -> str:
    # Fallback: verbleibende lokale .md-Hrefs (inkl. #fragment / ?query) auf .html umbiegen.
    return re.sub(
        r'(<a\s+href=")((?!https?://|#|mailto:)[^"]*?)\.md((?:[?#][^"]*)?)(")',
        r"\1\2.html\3\4",
        html,
    )


def _detail_output_rel(rel: Path) -> Path:
    if rel.as_posix() == "index.md":
        return Path("story") / "index.html"
    return rel.with_suffix(".html")


def _iter_heading_sections(md_text: str) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    current_h2: dict[str, object] | None = None
    current_h3: dict[str, object] | None = None
    in_fence = False

    for raw in md_text.splitlines():
        stripped = raw.strip()
        if FENCE_RX.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## "):
            current_h2 = {"title": stripped[3:].strip(), "lines": [], "children": []}
            sections.append(current_h2)
            current_h3 = None
            continue
        if stripped.startswith("### "):
            if current_h2 is None:
                continue
            current_h3 = {"title": stripped[4:].strip(), "lines": []}
            children = current_h2.setdefault("children", [])
            assert isinstance(children, list)
            children.append(current_h3)
            continue
        if current_h3 is not None:
            lines = current_h3.setdefault("lines", [])
            assert isinstance(lines, list)
            lines.append(raw)
        elif current_h2 is not None:
            lines = current_h2.setdefault("lines", [])
            assert isinstance(lines, list)
            lines.append(raw)
    return sections


def _plain_markdown_excerpt(md_text: str, *, max_length: int = 220) -> str:
    lines: list[str] = []
    in_fence = False
    for raw in md_text.splitlines():
        stripped = raw.strip()
        if FENCE_RX.match(stripped):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if stripped.startswith("#"):
            continue
        stripped = re.sub(r"^[*-]\s+", "", stripped)
        stripped = re.sub(r"^\d+\.\s+", "", stripped)
        lines.append(stripped)
    plain = " ".join(lines)
    plain = INLINE_TAG_RX.sub("", plain)
    plain = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", plain)
    plain = re.sub(r"\[(.*?)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"`([^`]+)`", r"\1", plain)
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", plain)
    plain = re.sub(r"__(.+?)__", r"\1", plain)
    plain = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", plain)
    plain = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return ""
    if len(plain) > max_length:
        return plain[: max_length - 3].rstrip() + "..."
    return plain


def _parse_timeline_stamp(raw: str) -> tuple[str, int] | None:
    value = raw.strip()
    month_names = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H",
        "%Y-%m-%d",
        "%Y-%m",
        "%Y",
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if fmt == "%Y":
            label = parsed.strftime("%Y")
        elif fmt == "%Y-%m":
            label = f"{month_names[parsed.month - 1]} {parsed.year}"
        elif fmt == "%Y-%m-%d":
            label = f"{parsed.day}. {month_names[parsed.month - 1]} {parsed.year}"
        else:
            label = f"{parsed.day}. {month_names[parsed.month - 1]} {parsed.year}, {parsed.hour:02d}:{parsed.minute:02d}"
        return label, int(parsed.timestamp() * 1000)
    return None


def _parse_profile_bullets(md_text: str) -> dict[str, str]:
    profile: dict[str, str] = {}
    for raw in md_text.splitlines():
        stripped = raw.strip()
        match = re.match(r"^[-*]\s+\*\*(.+?):\*\*\s*(.+?)\s*$", stripped)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        profile[key] = value
    return profile


def _timeline_importance_score(label: str | None, relevance: str | None, status: str | None) -> int:
    normalized = (label or "").strip().casefold()
    if normalized in {"episch", "legendär", "legendaer", "sehr hoch"}:
        return 4
    if normalized in {"hoch", "groß", "gross"}:
        return 3
    if normalized in {"niedrig", "klein"}:
        return 1
    if normalized in {"mittel", "normal"}:
        return 2

    relevance_text = (relevance or "").casefold()
    if "extrem hoch" in relevance_text or "weltereignis" in relevance_text:
        return 4
    if "hoher" in relevance_text or "hoch" in relevance_text:
        return 3

    status_text = (status or "").casefold()
    if "kanonisch" in status_text:
        return 3
    if "umstritten" in status_text or "wip" in status_text or "gerücht" in status_text or "geruecht" in status_text:
        return 2
    return 2


def _parse_timeline_entry(
    *,
    md_path: Path,
    text: str,
    story_root: Path,
    output_root: Path,
    out_rel: Path,
) -> dict[str, object] | None:
    rel = md_path.relative_to(story_root)
    if rel.as_posix() == "Kanon/Timeline/index.md":
        return None
    if rel.as_posix().endswith("/vorlage.md"):
        return None

    sections = _iter_heading_sections(text)
    section_map = {
        str(section["title"]): section for section in sections if isinstance(section.get("title"), str)
    }
    profile_section = section_map.get("Kurzprofil")
    overview_section = section_map.get("Überblick")
    stages_section = section_map.get("Zeitstufen")

    profile = _parse_profile_bullets("\n".join(profile_section.get("lines", []))) if profile_section else {}
    overview = _plain_markdown_excerpt(
        "\n".join(overview_section.get("lines", [])) if overview_section else text,
        max_length=260,
    ) or _extract_overview(text, max_length=260)

    stage_heading_map = {
        "Vor 2026": "past",
        "Juni 2066 - Doomsday": "doom",
        "2222 - Jetztzeit von Doomsday Radio": "year1",
        "2222 - Radiogegenwart": "year1",
        "2222 - Radiogegenwart / Staffel 1: Restangst": "year1",
        "2222 - Radiogegenwart / Staffel 1: Signale am Abgrund": "year1",
        "2223 - Radiogegenwart": "year2",
        "2223 - Radiogegenwart / Staffel 2: Verdichtung": "year2",
        "2223 - Radiogegenwart / Staffel 2: Im Umlauf": "year2",
        "2224 - Radiogegenwart": "year3",
        "2224 - Radiogegenwart / Staffel 3: Offenlegung": "year3",
        "2224 - Radiogegenwart / Staffel 3: Zugriff": "year3",
        "2225 - Radiogegenwart": "year4",
        "2225 - Radiogegenwart / Staffel 4: Kippen": "year4",
        "2225 - Radiogegenwart / Staffel 4: Leere Häuser": "year4",
        "2226 - Radiogegenwart": "year5",
        "2226 - Radiogegenwart / Staffel 5: Nachlauf und Neuordnung": "year5",
        "2226 - Radiogegenwart / Staffel 5: Neue Wildnis": "year5",
        "Jahr 1 - Radiogegenwart": "year1",
        "Jahr 2 - Radiogegenwart": "year2",
        "Jahr 3 - Radiogegenwart": "year3",
        "Jahr 4 - Radiogegenwart": "year4",
        "Jahr 5 - Radiogegenwart": "year5",
        "Danach / spätere Entwicklung": "future",
        "Zukünftige Möglichkeiten / konkurrierende Spekulationen": "future",
    }
    stages: list[dict[str, str]] = []
    if stages_section:
        for child in stages_section.get("children", []):
            if not isinstance(child, dict):
                continue
            heading = str(child.get("title", "")).strip()
            stage_key = stage_heading_map.get(heading)
            if not stage_key:
                continue
            child_lines = list(child.get("lines", []))
            stage_body_lines: list[str] = []
            milestones_for_stage: list[dict[str, object]] = []
            for raw_line in child_lines:
                match = TIMELINE_MILESTONE_RX.match(raw_line.strip())
                if not match:
                    stage_body_lines.append(raw_line)
                    continue
                parsed_stamp = _parse_timeline_stamp(match.group("stamp"))
                if not parsed_stamp:
                    stage_body_lines.append(raw_line)
                    continue
                label, timestamp_ms = parsed_stamp
                milestones_for_stage.append(
                    {
                        "stamp": match.group("stamp").strip(),
                        "label": label,
                        "timestamp_ms": timestamp_ms,
                        "title": match.group("title").strip(),
                        "summary": match.group("summary").strip(),
                    }
                )
            stage_text = "\n".join(stage_body_lines)
            summary = _plain_markdown_excerpt(stage_text, max_length=220)
            body = _plain_markdown_excerpt(stage_text, max_length=600)
            stages.append(
                {
                    "key": stage_key,
                    "label": heading,
                    "summary": summary,
                    "body": body,
                    "milestones": milestones_for_stage,
                }
            )

    stage_by_key = {stage["key"]: stage for stage in stages}
    ordered_stages: list[dict[str, str]] = []
    for stage_key, stage_label in [
        ("past", "Vor 2026"),
        ("doom", "Juni 2066"),
        ("year1", "2222"),
        ("year2", "2223"),
        ("year3", "2224"),
        ("year4", "2225"),
        ("year5", "2226"),
        ("future", "Danach"),
    ]:
        stage = stage_by_key.get(stage_key)
        ordered_stages.append(
            {
                "key": stage_key,
                "label": stage_label,
                "summary": (stage or {}).get("summary", ""),
                "body": (stage or {}).get("body", ""),
                "milestones": (stage or {}).get("milestones", []),
            }
        )

    importance_label = profile.get("Wichtigkeit")
    importance = _timeline_importance_score(
        importance_label,
        profile.get("Relevanz für [Doomsday Radio](../glossar.md#doomsday-radio)")
        or profile.get("Relevanz für Doomsday Radio"),
        profile.get("Status"),
    )
    href = _relative_href(output_root / "Kanon" / "Timeline", output_root / out_rel)
    return {
        "title": _read_markdown_title(text) or md_path.stem,
        "story_path": rel.as_posix(),
        "href": href,
        "overview": overview,
        "status": profile.get("Status", ""),
        "type": profile.get("Typ", ""),
        "period": profile.get("Zeitraum", ""),
        "importance": importance,
        "importance_label": importance_label or "",
        "stages": ordered_stages,
    }


def _render_absolute_timeline_page(
    *,
    milestones: list[dict[str, object]],
    page_url: str,
    description: str,
    audio_sources: list[dict[str, str]],
) -> str:
    milestones_json = json.dumps(milestones, ensure_ascii=False)
    audio_sources_json = json.dumps(audio_sources, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="de" data-mode="ddd">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Doomsday Dispatch – Timeline</title>
  <meta name="description" content="{_escape_html(description)}" />
  <link rel="canonical" href="{_escape_html(page_url)}" />
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css" />
  <style>
    :root {{
      --bg: #0a0d12;
      --bg-a: #3b3028;
      --bg-b: #1b1613;
      --chassis-top: #8f7c6a;
      --chassis-mid: #665548;
      --chassis-low: #44362d;
      --bezel: #181312;
      --bezel-hi: #3e3128;
      --panel: rgba(10, 12, 16, 0.78);
      --panel-strong: rgba(16, 20, 27, 0.9);
      --text: #f3e7c9;
      --muted: #ceb991;
      --accent: #ffb347;
      --accent-hot: #ff7b39;
      --line: rgba(255, 198, 104, 0.52);
      --card-width: 360px;
      --panel-radius: 18px;
      --title-font: "Bebas Neue", Impact, sans-serif;
      --mono-font: "IBM Plex Mono", Menlo, monospace;
      --lcd-bg: #d9cf9f;
      --lcd-text: #5e552e;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      margin: 0;
      min-height: 100%;
      height: 100dvh;
      max-height: 100dvh;
      overflow: hidden;
      overflow: clip;
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: "Avenir Next", "Trebuchet MS", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 16% 12%, rgba(255, 157, 47, 0.18), transparent 20%),
        radial-gradient(circle at 82% 14%, rgba(255, 209, 102, 0.08), transparent 18%),
        radial-gradient(circle at 50% 100%, rgba(255, 90, 61, 0.14), transparent 34%),
        url("../../../map/soiled-paper.jpg") center/420px auto repeat,
        linear-gradient(165deg, var(--bg-a), var(--bg-b) 72%);
      background-blend-mode: screen, screen, screen, multiply, normal;
      max-height: 100dvh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: 0.28;
      background:
        repeating-linear-gradient(90deg, rgba(255,255,255,0.02) 0 1px, transparent 1px 7px),
        repeating-linear-gradient(180deg, rgba(0,0,0,0.08) 0 2px, transparent 2px 8px),
        radial-gradient(circle at 20% 24%, rgba(255,255,255,0.06) 0 2px, transparent 3px) 0 0 / 38px 38px;
      mix-blend-mode: soft-light;
    }}
    .noise-layer {{
      position: fixed;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 2;
      opacity: 0;
      mix-blend-mode: screen;
      transition: opacity .08s linear;
    }}
    .page {{
      position: relative;
      z-index: 3;
      height: 100dvh;
      max-height: 100dvh;
      box-sizing: border-box;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 10px;
      padding: 18px;
      overflow: hidden;
      overflow: clip;
      max-width: 1520px;
      margin: 0 auto;
      border-radius: 34px;
      border: 1px solid rgba(255,255,255,0.16);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.15), rgba(255,255,255,0) 15%, rgba(0,0,0,0.14) 82%),
        linear-gradient(180deg, var(--chassis-top), var(--chassis-mid) 48%, var(--chassis-low)),
        radial-gradient(circle at 14% 14%, rgba(255,255,255,0.22), transparent 24%),
        radial-gradient(circle at 84% 86%, rgba(0,0,0,0.24), transparent 28%),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.05) 1px, rgba(0,0,0,0.02) 1px, rgba(0,0,0,0.02) 3px, transparent 3px, transparent 7px);
      box-shadow:
        0 34px 80px rgba(0,0,0,0.46),
        0 10px 24px rgba(0,0,0,0.24),
        inset 0 1px 0 rgba(255,255,255,0.24),
        inset 0 -10px 18px rgba(0,0,0,0.24);
    }}
    .page::after {{
      content: "";
      position: absolute;
      inset: 10px;
      border-radius: 24px;
      pointer-events: none;
      border: 1px solid rgba(255,255,255,0.1);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.06),
        inset 0 0 0 1px rgba(0,0,0,0.16);
    }}
    .hero, .toolbar {{
      position: relative;
      z-index: 1;
      border-radius: var(--panel-radius);
    }}
    .hero {{
      border: 2px solid var(--bezel-hi);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01) 10%, rgba(0,0,0,0.14)),
        linear-gradient(180deg, #130707, #060203);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.08),
        inset 0 -8px 12px rgba(0,0,0,0.24),
        0 16px 34px rgba(0,0,0,.22);
    }}
    .hero {{
      padding: 16px 18px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: start;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-family: var(--title-font);
      font-size: clamp(40px, 5vw, 72px);
      line-height: .9;
      letter-spacing: .04em;
      text-transform: uppercase;
      color: #ffd166;
      text-shadow:
        0 3px 0 rgba(0,0,0,.28),
        0 0 18px rgba(255, 157, 47, .14);
    }}
    .hero p {{ margin: 0; max-width: 70ch; color: var(--muted); line-height: 1.5; }}
    .hero-link {{
      color: var(--text); text-decoration: none; border: 1px solid rgba(255, 198, 104, .28);
      padding: 12px 16px; border-radius: 999px; background: rgba(0,0,0,.24);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
    }}
    .toolbar {{
      padding: 10px 12px;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto auto;
      align-items: center;
      gap: 12px;
      min-height: 76px;
      border: 2px solid var(--bezel-hi);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01) 10%, rgba(0,0,0,0.14)),
        linear-gradient(180deg, #130707, #060203);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.08),
        inset 0 -8px 12px rgba(0,0,0,0.24),
        0 16px 34px rgba(0,0,0,.18);
      overflow: hidden;
    }}
    .toolbar > * {{ position: relative; z-index: 1; }}
    .toolbar-group {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: nowrap;
      min-width: 0;
      min-height: 52px;
      color: var(--lcd-text);
    }}
    .toolbar-group.search-group {{
      justify-content: stretch;
    }}
    .toolbar-group.zoom-group {{
      justify-content: center;
    }}
    .toolbar-group.action-group {{
      justify-content: flex-end;
    }}
    .toolbar-lcd {{
      --snow-strength: 0;
      --snow-opacity: 0;
      --beat-pulse: 0;
      display: inline-flex;
      align-items: stretch;
      gap: 10px;
      padding: 8px 10px;
      min-height: 52px;
      height: 52px;
      border: 1px solid rgba(109, 132, 63, .74);
      background:
        radial-gradient(circle at 18% 12%, rgba(245, 252, 222, .2), transparent 40%),
        linear-gradient(180deg, color-mix(in srgb, var(--lcd-bg) 93%, white 7%), color-mix(in srgb, var(--lcd-bg) 87%, #7f9465 13%) 58%, color-mix(in srgb, var(--lcd-bg) 79%, #6d8154 21%));
      box-shadow:
        inset 0 0 0 1px rgba(199,217,133,.2),
        inset 0 0 0 2px rgba(48, 64, 24, .28),
        inset 0 10px 14px rgba(216,229,162,.1),
        inset 0 -12px 18px rgba(47,64,23,.2),
        inset 0 -20px 26px rgba(28, 39, 14, .2),
        inset 0 16px 20px rgba(216,229,162,.1);
      position: relative;
      overflow: hidden;
      filter: contrast(calc(1 + var(--snow-strength) * 0.1)) saturate(calc(1 + var(--snow-strength) * 0.06)) brightness(calc(.995 + var(--beat-pulse) * .015));
      transform: none;
    }}
    .toolbar-lcd::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 1;
      opacity: calc(.04 + var(--snow-strength) * .38 + var(--beat-pulse) * .0005);
      background:
        linear-gradient(90deg,
          rgba(255, 66, 66, calc(var(--snow-strength) * .22)) 0%,
          rgba(255, 66, 66, calc(var(--snow-strength) * .1)) 38%,
          rgba(114, 190, 255, calc(var(--snow-strength) * .18)) 100%),
        linear-gradient(180deg,
          transparent 0 18%,
          rgba(245, 255, 190, calc(var(--snow-strength) * .22)) 18% 21%,
          transparent 21% 46%,
          rgba(255, 120, 120, calc(var(--snow-strength) * .12)) 46% 49%,
          transparent 49% 100%),
        radial-gradient(circle at 84% 18%, rgba(238, 250, 170, .16), transparent 32%),
        repeating-linear-gradient(90deg,
          rgba(56, 86, 24, .06) 0 1px,
          rgba(178, 210, 82, .02) 1px 2px,
          transparent 2px 4px),
        repeating-linear-gradient(0deg,
          rgba(47, 72, 18, .12) 0 1px,
          rgba(189, 215, 86, .03) 1px 3px,
          transparent 3px 5px);
      mix-blend-mode: screen;
    }}
    .toolbar-lcd::after {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 3;
      opacity: calc(var(--snow-opacity) * .42 + var(--snow-strength) * .035 + var(--beat-pulse) * .0004);
      background:
        linear-gradient(0deg,
          transparent 0 24%,
          rgba(228, 247, 150, calc(var(--snow-strength) * .34)) 24% 28%,
          transparent 28% 56%,
          rgba(188, 220, 106, calc(var(--snow-strength) * .26)) 56% 60%,
          transparent 60% 100%),
        linear-gradient(90deg,
          transparent 0 14%,
          rgba(255,255,255, calc(var(--snow-strength) * .09)) 14% 16%,
          transparent 16% 68%,
          rgba(255,255,255, calc(var(--snow-strength) * .07)) 68% 71%,
          transparent 71% 100%),
        repeating-linear-gradient(0deg,
          transparent 0 10px,
          rgba(255,255,255, calc(var(--snow-strength) * .14)) 10px 11px,
          transparent 11px 18px),
        radial-gradient(circle, rgba(205, 226, 130, .36) 0 1px, transparent 1px 100%) 0 0 / 6px 6px,
        repeating-linear-gradient(0deg, rgba(56, 78, 24, .09), rgba(56, 78, 24, .09) 1px, transparent 1px, transparent 3px);
      mix-blend-mode: screen;
    }}
    .toolbar-lcd > * {{
      position: relative;
      z-index: 1;
    }}
    .toolbar-lcd.search-lcd {{
      flex: 1 1 320px;
      min-width: 220px;
    }}
    .toolbar-lcd.scale-lcd {{
      flex: 0 0 auto;
      min-width: 280px;
      justify-content: space-between;
    }}
    .toolbar button {{
      border: 1px solid rgba(109, 132, 63, .58);
      background: rgba(255,255,255,0.03);
      color: #f3e7c9;
      padding: 9px 12px;
      border-radius: 999px;
      cursor: pointer;
      font-family: var(--mono-font);
      text-transform: uppercase;
      letter-spacing: .04em;
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.04),
        inset 0 -1px 0 rgba(0,0,0,.14);
    }}
    .toolbar-group.action-group button {{
      --led-color: #ff9b47;
      --led-off: color-mix(in srgb, var(--led-color) 48%, #141920 52%);
      appearance: none;
      position: relative;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: var(--panel-radius);
      padding: 10px 22px 10px 12px;
      color: var(--text);
      font: 700 12px/1 var(--mono-font);
      text-transform: uppercase;
      letter-spacing: 0.3px;
      cursor: pointer;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.01)),
        linear-gradient(180deg, #4a352a, #241815);
      box-shadow:
        0 10px 20px rgba(0,0,0,0.16),
        inset 0 1px 0 rgba(255,255,255,0.06);
      transition: border-color 140ms ease, box-shadow 140ms ease;
    }}
    .toolbar-group.action-group button::after {{
      content: "";
      position: absolute;
      right: 7px;
      top: 7px;
      width: 7px;
      height: 7px;
      border-radius: 2px;
      border: 1px solid color-mix(in srgb, var(--led-color) 30%, rgba(225,235,246,.2) 70%);
      background: var(--led-off);
      opacity: .94;
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--led-color) 14%, rgba(0,0,0,.58) 86%);
      pointer-events: none;
      transform: scale(1);
      filter: brightness(.72) saturate(.9);
    }}
    .toolbar-group.action-group button:hover {{
      border-color: rgba(255,209,102,0.34);
    }}
    .toolbar-group.action-group #jumpToNow {{
      --led-color: #52e07c;
      color: #1d120c;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)),
        linear-gradient(180deg, #ff9d2f, #c95314);
      border-color: rgba(255,209,102,0.38);
    }}
    .scale-readout {{
      min-width: 196px;
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      color: var(--lcd-text);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
      font: 700 15px/1.04 "VT323", var(--mono-font);
      text-transform: uppercase;
      letter-spacing: 0.22px;
    }}
    .scale-bar {{
      width: 88px;
      height: 8px;
      position: relative;
      border-top: 2px solid rgba(94, 85, 46, 0.88);
    }}
    .scale-bar::before,
    .scale-bar::after {{
      content: "";
      position: absolute;
      top: -4px;
      width: 2px;
      height: 10px;
      background: rgba(94, 85, 46, 0.88);
    }}
    .scale-bar::before {{ left: 0; }}
    .scale-bar::after {{ right: 0; }}
    .scale-label {{
      font: inherit;
      letter-spacing: inherit;
      text-transform: uppercase;
    }}
    .toolbar input[type="range"] {{
      width: min(280px, 48vw);
      height: 100%;
      margin: 0;
      accent-color: #7f9465;
    }}
    .toolbar-search {{
      width: 100%;
      min-width: 0;
      height: 100%;
      padding: 0 14px;
      border-radius: 0;
      border: 1px solid rgba(109, 132, 63, .74);
      background:
        radial-gradient(circle at 18% 12%, rgba(245, 252, 222, .2), transparent 40%),
        linear-gradient(180deg, color-mix(in srgb, var(--lcd-bg) 93%, white 7%), color-mix(in srgb, var(--lcd-bg) 87%, #7f9465 13%) 58%, color-mix(in srgb, var(--lcd-bg) 79%, #6d8154 21%));
      color: var(--lcd-text);
      outline: none;
      font: 700 16px/1.02 "VT323", var(--mono-font);
      letter-spacing: 0.22px;
      appearance: none;
      box-shadow:
        inset 0 0 0 1px rgba(199,217,133,.2),
        inset 0 0 0 2px rgba(48, 64, 24, .28),
        inset 0 10px 14px rgba(216,229,162,.1),
        inset 0 -12px 18px rgba(47,64,23,.2),
        inset 0 -20px 26px rgba(28, 39, 14, .2),
        inset 0 16px 20px rgba(216,229,162,.1);
    }}
    .toolbar-search::placeholder {{
      color: color-mix(in srgb, var(--lcd-text) 68%, transparent);
    }}
    .toolbar-search:focus {{
      border-color: rgba(109, 132, 63, .88);
      box-shadow:
        inset 0 0 0 1px rgba(199,217,133,.24),
        inset 0 0 0 2px rgba(48, 64, 24, .3),
        inset 0 10px 14px rgba(216,229,162,.1),
        inset 0 -12px 18px rgba(47,64,23,.2),
        inset 0 -20px 26px rgba(28, 39, 14, .2),
        inset 0 16px 20px rgba(216,229,162,.1),
        0 0 0 3px rgba(109, 132, 63, 0.12);
    }}
    .board-shell {{
      min-height: 0; position: relative; border-radius: 24px; overflow: hidden;
      border: 2px solid var(--bezel-hi);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01) 10%, rgba(0,0,0,0.14)),
        linear-gradient(180deg, #11171d, #090c10 74%),
        radial-gradient(circle at 20% 0%, rgba(141, 240, 202, 0.05), transparent 26%),
        radial-gradient(circle at 82% 86%, rgba(255, 157, 47, 0.08), transparent 26%);
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.08),
        inset 0 -10px 18px rgba(0,0,0,0.28),
        0 18px 40px rgba(0,0,0,.24);
      transition: background .22s ease, box-shadow .22s ease, border-color .22s ease;
    }}
    .board-shell[data-audio-state="idle"] {{
      background:
        radial-gradient(circle at top, rgba(76, 82, 92, 0.22), transparent 40%),
        linear-gradient(180deg, rgba(52, 57, 64, 0.985), rgba(38, 42, 48, 0.975));
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }}
    .board-noise-layer {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 2;
      opacity: 0;
      mix-blend-mode: screen;
      transition: opacity .08s linear;
    }}
    .timeline-hud {{
      position: absolute; top: 14px; right: 14px; z-index: 5; display: grid; gap: 6px;
      padding: 12px 14px; border-radius: 16px; border: 1px solid rgba(255,255,255,.08);
      background: rgba(10, 12, 16, 0.78); backdrop-filter: blur(10px); min-width: 200px;
    }}
    .timeline-hud strong {{ font-size: 12px; letter-spacing: .08em; text-transform: uppercase; color: #ffd38d; }}
    .timeline-hud span {{ color: var(--muted); font-size: 13px; line-height: 1.35; }}
    .timeline-minimap {{
      position: absolute;
      top: 110px;
      right: 14px;
      z-index: 5;
      width: 92px;
      height: 320px;
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,.08);
      background: rgba(10, 12, 16, 0.78);
      backdrop-filter: blur(10px);
      padding: 12px 10px;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 10px;
      cursor: default;
    }}
    .timeline-minimap-title {{
      font-size: 10px;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #ffd38d;
      text-align: center;
    }}
    .timeline-minimap-track {{
      position: relative;
      min-height: 0;
    }}
    .timeline-minimap-axis {{
      position: absolute;
      top: 0;
      bottom: 0;
      left: 50%;
      width: 1px;
      transform: translateX(-50%);
      background: linear-gradient(180deg, rgba(255, 198, 104, .18), rgba(255, 198, 104, .56), rgba(255, 198, 104, .18));
    }}
    .timeline-minimap-breaks {{
      position: absolute;
      inset: 0;
      pointer-events: none;
    }}
    .timeline-minimap-break {{
      position: absolute;
      left: 50%;
      width: 18px;
      height: 20px;
      transform: translate(-50%, -50%);
      border-radius: 999px;
      background: rgba(7, 9, 12, 0.96);
      box-shadow: 0 0 0 1px rgba(255,255,255,.06);
    }}
    .timeline-minimap-break::before,
    .timeline-minimap-break::after {{
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 1px;
      height: 12px;
      background: rgba(255, 211, 141, .75);
      border-radius: 999px;
    }}
    .timeline-minimap-break::before {{
      transform: translate(-5px, -50%) rotate(-26deg);
    }}
    .timeline-minimap-break::after {{
      transform: translate(4px, -50%) rotate(-26deg);
    }}
    .timeline-minimap-points,
    .timeline-minimap-viewport {{
      position: absolute;
      inset: 0;
    }}
    .timeline-minimap-point {{
      position: absolute;
      left: 50%;
      width: 5px;
      height: 5px;
      border-radius: 999px;
      transform: translate(-50%, -50%);
      background: rgb(var(--strand-rgb, 255, 211, 141));
      box-shadow: 0 0 0 2px rgba(var(--strand-rgb, 255, 211, 141), .12);
      opacity: .9;
    }}
    .timeline-minimap-viewport-box {{
      position: absolute;
      left: 8px;
      right: 8px;
      border-radius: 10px;
      border: 1px solid rgba(255, 211, 141, .7);
      background: rgba(255, 179, 71, .08);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,.04);
      min-height: 18px;
      cursor: grab;
      touch-action: none;
    }}
    .timeline-minimap.dragging .timeline-minimap-viewport-box {{
      cursor: grabbing;
      background: rgba(255, 179, 71, .12);
      border-color: rgba(255, 211, 141, .86);
    }}
    .board-scroll {{
      position: relative;
      z-index: 3;
      width: 100%;
      height: 100%;
      overflow: auto;
      overscroll-behavior: contain;
      touch-action: pan-y;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }}
    .board-scroll::-webkit-scrollbar {{
      width: 0;
      height: 0;
      display: none;
    }}
    .timeline-board {{ position: relative; min-height: 100%; padding: 96px 24px 140px; }}
    .audio-dock {{
      --beat: 0;
      position: fixed;
      right: 14px;
      bottom: 14px;
      z-index: 8;
      width: min(320px, calc(100vw - 28px));
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 18px;
      background: rgba(10, 12, 16, 0.86);
      box-shadow:
        0 18px 44px rgba(0,0,0,.28),
        0 0 calc(10px + var(--beat) * 20px) rgba(255, 123, 57, calc(0.06 + var(--beat) * 0.22));
      backdrop-filter: blur(12px);
      overflow: hidden;
      transition: box-shadow .12s linear, border-color .12s linear;
    }}
    .audio-dock-inner {{
      display: grid;
      gap: 10px;
      padding: 12px 14px;
    }}
    .audio-top {{
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 10px;
      align-items: center;
    }}
    .audio-play {{
      width: 38px;
      height: 38px;
      border-radius: 999px;
      border: 1px solid rgba(255, 198, 104, .28);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      cursor: pointer;
      font-size: 14px;
      transform: scale(calc(1 + var(--beat) * 0.08));
      transition: transform .1s linear, border-color .12s linear, background .12s linear;
    }}
    .audio-meta {{
      min-width: 0;
      display: grid;
      gap: 2px;
    }}
    .audio-kicker {{
      color: #ffd38d;
      font-size: 11px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    .audio-title {{
      font-size: 13px;
      color: var(--text);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .audio-time {{
      font-size: 12px;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}
    .audio-visualizer {{
      display: inline-flex;
      align-items: end;
      gap: 3px;
      height: 18px;
    }}
    .beat-bar {{
      width: 3px;
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(180deg, #ffd38d, #ff8f4d);
      transform-origin: center bottom;
      transform: scaleY(0.18);
      opacity: 0.72;
      transition: transform .08s linear, opacity .08s linear;
    }}
    .audio-progress {{
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 4px;
      border-radius: 999px;
      background: rgba(255,255,255,.10);
      outline: none;
      accent-color: var(--accent);
    }}
    .audio-progress::-webkit-slider-thumb {{
      -webkit-appearance: none;
      appearance: none;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: #ffd38d;
      border: none;
    }}
    .audio-progress::-moz-range-thumb {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: #ffd38d;
      border: none;
    }}
    .audio-progress::-moz-range-track {{
      height: 4px;
      border-radius: 999px;
      background: rgba(255,255,255,.10);
    }}
    .timeline-axis {{
      position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; transform: translateX(-50%);
      background: linear-gradient(180deg, transparent 0%, rgba(255, 198, 104, .52) 6%, rgba(255, 198, 104, .28) 94%, transparent 100%);
      box-shadow: 0 0 24px rgba(255, 179, 71, .18);
    }}
    .timeline-breaks {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 4;
    }}
    .timeline-break {{
      position: absolute;
      left: 50%;
      width: 34px;
      height: 42px;
      transform: translate(-50%, -50%);
      border-radius: 999px;
      background: rgba(8, 11, 15, 0.98);
      box-shadow:
        0 0 0 1px rgba(255,255,255,.05),
        0 8px 20px rgba(0,0,0,.2);
    }}
    .timeline-break::before,
    .timeline-break::after {{
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 2px;
      height: 24px;
      background: rgba(255, 211, 141, .88);
      border-radius: 999px;
      box-shadow: 0 0 10px rgba(255, 179, 71, .16);
    }}
    .timeline-break::before {{
      transform: translate(-8px, -50%) rotate(-28deg);
    }}
    .timeline-break::after {{
      transform: translate(6px, -50%) rotate(-28deg);
    }}
    .timeline-ruler, .timeline-years, .timeline-events {{ position: absolute; inset: 0; }}
    .timeline-ruler {{ pointer-events: none; }}
    .timeline-years {{ pointer-events: none; z-index: 6; }}
    .ruler-mark {{ position: absolute; left: 50%; transform: translate(-50%, -50%); }}
    .ruler-mark::before {{
      content: ""; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
      width: 18px; height: 1px; background: rgba(255, 198, 104, .22);
    }}
    .ruler-mark.major::before {{ width: 42px; background: rgba(255, 198, 104, .48); }}
    .ruler-label {{
      position: absolute;
      left: 50%;
      color: rgba(243,231,201,.58);
      font-size: 11px;
      letter-spacing: .08em;
      text-transform: uppercase;
      white-space: nowrap;
      text-align: center;
      pointer-events: none;
    }}
    .ruler-label.above {{
      top: -12px;
      transform: translate(-50%, -100%);
    }}
    .ruler-label.below {{
      top: 12px;
      transform: translate(-50%, 0);
    }}
    .year-marker {{ position: absolute; left: 0; right: 0; height: 0; z-index: 6; }}
    .year-dot {{
      position: absolute; left: 50%; width: 18px; height: 18px; transform: translate(-50%, -50%);
      border-radius: 999px; background: linear-gradient(180deg, #ffd38d, #ff8f4d);
      box-shadow: 0 0 0 6px rgba(255, 179, 71, .08), 0 0 24px rgba(255, 123, 57, .24);
    }}
    .year-label {{
      position: absolute;
      left: calc(50% + 28px);
      transform: translateY(-50%);
      display: grid;
      gap: 4px;
      max-width: min(24vw, 260px);
      padding: 8px 12px;
      border: 1px solid rgba(255, 209, 102, .16);
      border-radius: 12px;
      background: rgba(18, 22, 30, .86);
      box-shadow:
        0 10px 22px rgba(0,0,0,.22),
        inset 0 0 0 1px rgba(255,255,255,.02);
      backdrop-filter: blur(8px);
    }}
    .year-marker.compact .year-label {{
      left: 50%;
      right: auto;
      transform: translate(-50%, calc(-100% - 12px));
      text-align: center;
      max-width: min(22vw, 220px);
      gap: 2px;
    }}
    .year-marker.center-above .year-label {{
      left: 50%;
      right: auto;
      transform: translate(-50%, calc(-100% - 14px));
      text-align: center;
      width: min(220px, 18vw);
      max-width: min(220px, 18vw);
      gap: 3px;
    }}
    .year-marker.center-below .year-label {{
      left: 50%;
      right: auto;
      transform: translate(-50%, 14px);
      text-align: center;
      width: min(220px, 18vw);
      max-width: min(220px, 18vw);
      gap: 3px;
    }}
    .year-marker.side-left .year-label {{
      left: auto;
      right: calc(50% + 72px);
      text-align: right;
      max-width: min(15vw, 180px);
      gap: 3px;
    }}
    .year-marker.side-right .year-label {{
      left: calc(50% + 72px);
      right: auto;
      text-align: left;
      max-width: min(15vw, 180px);
      gap: 3px;
    }}
    .year-marker.epoch-left .year-label {{
      left: auto;
      right: calc(50% + 110px);
      text-align: right;
      width: min(13vw, 150px);
      max-width: min(13vw, 150px);
      gap: 2px;
    }}
    .year-marker.epoch-right .year-label {{
      left: calc(50% + 110px);
      right: auto;
      text-align: left;
      width: min(13vw, 150px);
      max-width: min(13vw, 150px);
      gap: 2px;
    }}
    .year-marker.prominent-above .year-label {{
      left: 50%;
      right: auto;
      transform: translate(-50%, calc(-100% - 20px));
      text-align: center;
      width: min(240px, 26vw);
      max-width: min(240px, 26vw);
      gap: 6px;
      padding: 10px 14px;
    }}
    .year-marker.prominent-below .year-label {{
      left: 50%;
      right: auto;
      transform: translate(-50%, 20px);
      text-align: center;
      width: min(240px, 26vw);
      max-width: min(240px, 26vw);
      gap: 6px;
      padding: 10px 14px;
    }}
    .year-label strong {{
      font-size: 14px;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #ffd166;
      line-height: 1;
      text-shadow:
        0 2px 0 rgba(0,0,0,.34),
        0 0 14px rgba(255, 157, 47, .12);
    }}
    .year-label span {{
      color: rgba(243, 231, 201, 0.78);
      font-size: 13px;
      line-height: 1.25;
      text-shadow: 0 1px 0 rgba(0,0,0,.34);
    }}
    .year-marker.prominent-above .year-label strong,
    .year-marker.prominent-below .year-label strong {{
      font-size: 28px;
      letter-spacing: .045em;
      color: #ffd166;
      text-shadow:
        0 2px 0 rgba(0,0,0,.38),
        0 0 18px rgba(255, 157, 47, .16);
    }}
    .year-marker.prominent-above .year-label span,
    .year-marker.prominent-below .year-label span {{
      font-size: 14px;
      color: rgba(243, 231, 201, 0.88);
    }}
    .year-marker.nudge-up .year-label {{
      margin-top: -46px;
    }}
    .year-marker.nudge-down .year-label {{
      margin-top: 46px;
    }}
    .year-marker.far-up .year-label {{
      margin-top: -96px;
    }}
    .year-marker.far-down .year-label {{
      margin-top: 96px;
    }}
    .event-node {{
      position: absolute; left: 50%; width: 10px; height: 10px; transform: translate(-50%, -50%);
      border-radius: 999px; background: rgb(var(--strand-rgb, 255, 211, 141)); box-shadow: 0 0 0 4px rgba(var(--strand-rgb, 255, 179, 71), .08);
      z-index: 3;
    }}
    .event-node.cluster {{
      width: 14px; height: 14px; background: rgb(var(--strand-rgb, 255, 143, 77));
      box-shadow: 0 0 0 6px rgba(var(--strand-rgb, 255, 123, 57), .12), 0 0 22px rgba(var(--strand-rgb, 255, 123, 57), .22);
    }}
    .event-card {{
      position: absolute; width: min(var(--card-width), calc(50% - 176px)); z-index: 2;
      transform-origin: center top;
      transition: width .18s ease-out, opacity .22s ease-out, transform .22s ease-out, filter .22s ease-out;
    }}
    .event-card.left {{ right: calc(50% + 156px); }}
    .event-card.right {{ left: calc(50% + 156px); }}
    .event-connector {{
      position: absolute;
      top: 0;
      left: 0;
      width: 0;
      height: 1px;
      background: rgba(var(--strand-rgb, 255, 198, 104), .42);
      transform-origin: 0 50%;
      z-index: 1;
      pointer-events: none;
    }}
    .event-connector.hidden {{
      opacity: 0;
    }}
    .event-card-inner {{
      border: 1px solid rgba(255,255,255,.12); border-radius: 16px; padding: 14px 16px;
      background: rgba(22, 27, 35, 0.96);
      box-shadow:
        0 12px 28px rgba(0,0,0,.28),
        inset 0 0 0 1px rgba(255,255,255,.03);
      display: grid; gap: 10px;
      transition: background .22s ease-out, border-color .22s ease-out, box-shadow .22s ease-out;
    }}
    .event-card-inner::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      border-radius: 16px 0 0 16px;
      background: rgba(var(--strand-rgb, 255, 211, 141), .9);
    }}
    .event-card-inner {{ position: relative; }}
    .event-chips {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      max-height: 56px;
      overflow: hidden;
      transition: opacity .24s ease-out, transform .24s ease-out;
    }}
    .event-chip {{
      display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; border-radius: 999px;
      border: 1px solid rgba(255, 198, 104, .16); background: rgba(255, 179, 71, 0.06);
      color: #f2c778; font-size: 10px; text-transform: uppercase; letter-spacing: .05em;
    }}
    button.event-chip {{
      cursor: pointer;
      font: inherit;
    }}
    .event-chip.strand {{
      border-color: rgba(var(--strand-rgb, 255, 198, 104), .32);
      background: rgba(var(--strand-rgb, 255, 198, 104), .12);
      color: rgb(var(--strand-rgb, 255, 211, 141));
    }}
    .event-meta-row {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }}
    .event-filter-button {{
      border: 1px solid rgba(var(--strand-rgb, 255, 198, 104), .28);
      background: rgba(var(--strand-rgb, 255, 198, 104), .08);
      color: rgb(var(--strand-rgb, 255, 211, 141));
      border-radius: 999px;
      width: 32px;
      height: 32px;
      padding: 0;
      font: inherit;
      font-size: 12px;
      cursor: pointer;
      transition: background .18s ease-out, border-color .18s ease-out, opacity .18s ease-out;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
    }}
    .event-filter-button:hover {{
      background: rgba(var(--strand-rgb, 255, 198, 104), .16);
      border-color: rgba(var(--strand-rgb, 255, 198, 104), .44);
    }}
    .event-filter-button .fa-solid {{
      font-size: 13px;
      pointer-events: none;
    }}
    .event-card h3 {{ margin: 0; font-size: 18px; transition: opacity .22s ease-out; }}
    .event-card h3 a {{ color: inherit; text-decoration: none; }}
    .event-card h3 a:hover {{ color: #ffd38d; }}
    .event-stamp {{ color: #ffd38d; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; transition: opacity .22s ease-out; }}
    .event-summary, .event-overview {{
      margin: 0;
      line-height: 1.5;
      font-size: 14px;
      max-height: 200px;
      overflow: hidden;
      transition: opacity .24s ease-out, transform .24s ease-out;
    }}
    .event-overview {{ color: var(--muted); }}
    .event-link {{
      color: #ffd38d;
      text-decoration: none;
      font-size: 14px;
      max-height: 24px;
      overflow: hidden;
      transition: opacity .24s ease-out, transform .24s ease-out;
    }}
    .event-card[data-detail="summary"] .event-chips,
    .event-card[data-detail="summary"] .event-overview,
    .event-card[data-detail="summary"] .event-link {{
      opacity: 0;
      max-height: 0;
      transform: translateY(-6px);
      pointer-events: none;
      margin: 0;
    }}
    .event-card[data-detail="summary"] .event-card-inner {{ padding-top: 12px; padding-bottom: 12px; }}
    .event-card[data-detail="summary"] {{
      opacity: 0.96;
      transform: scale(0.95);
      filter: saturate(0.94);
    }}
    .event-card[data-detail="summary"] .event-card-inner {{
      gap: 8px;
    }}
    .event-card[data-detail="summary"] h3 {{
      font-size: 16px;
    }}
    .event-card[data-detail="summary"] .event-summary {{
      font-size: 13px;
    }}
    .event-card[data-detail="headline"] {{
      opacity: 0.88;
      transform: scale(0.86);
      filter: saturate(0.86);
    }}
    .event-card[data-detail="headline"] .event-card-inner {{
      padding: 10px 12px;
      gap: 6px;
      background: rgba(24, 29, 37, 0.92);
      border-color: rgba(255,255,255,.14);
      box-shadow:
        0 10px 24px rgba(0,0,0,.24),
        inset 0 0 0 1px rgba(255,255,255,.025);
    }}
    .event-card[data-detail="headline"] .event-chips,
    .event-card[data-detail="headline"] .event-summary,
    .event-card[data-detail="headline"] .event-overview,
    .event-card[data-detail="headline"] .event-link,
    .event-card[data-detail="headline"] .event-filter-button {{
      opacity: 0;
      max-height: 0;
      overflow: hidden;
      transform: translateY(-8px);
      pointer-events: none;
      margin: 0;
    }}
    .event-card[data-detail="headline"] h3 {{
      font-size: 14px;
    }}
    .event-card[data-detail="headline"] .event-stamp {{
      font-size: 11px;
      opacity: 0.86;
    }}
    .event-card[data-detail="full"] .event-chips,
    .event-card[data-detail="full"] .event-summary,
    .event-card[data-detail="full"] .event-overview,
    .event-card[data-detail="full"] .event-link {{
      opacity: 1;
      max-height: 240px;
      transform: translateY(0);
      pointer-events: auto;
    }}
    .event-card[data-kind="cluster"] .event-card-inner {{
      background: rgba(28, 18, 14, 0.84);
      border-color: rgba(var(--strand-rgb, 255, 179, 71), .16);
    }}
    .event-card[data-kind="cluster"] .event-summary {{
      color: #f0d6a2;
    }}
    .event-count {{
      color: #ffcf83;
      font-size: 12px;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    .board-shell[data-view-mode="strand"] .timeline-axis,
    .board-shell[data-view-mode="strand"] .timeline-ruler,
    .board-shell[data-view-mode="strand"] .timeline-years,
    .board-shell[data-view-mode="strand"] .event-node,
    .board-shell[data-view-mode="strand"] .event-connector,
    .board-shell[data-view-mode="strand"] .timeline-hud,
    .board-shell[data-view-mode="strand"] .timeline-minimap {{
      display: none;
    }}
    .board-shell[data-view-mode="strand"] .timeline-board {{
      padding: 24px 24px 120px;
    }}
    .board-shell[data-view-mode="strand"] .event-card,
    .board-shell[data-view-mode="strand"] .event-card.left,
    .board-shell[data-view-mode="strand"] .event-card.right {{
      left: 50% !important;
      right: auto !important;
      width: min(860px, calc(100% - 24px)) !important;
      transform: translateX(-50%) !important;
    }}
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"],
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] {{
      opacity: 1;
      filter: none;
    }}
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] .event-card-inner,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-card-inner {{
      padding: 14px 16px;
      gap: 10px;
      background: rgba(18, 21, 28, 0.82);
    }}
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] .event-chips,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] .event-overview,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] .event-link,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-chips,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-summary,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-overview,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-link,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-filter-button {{
      opacity: 1;
      max-height: 240px;
      transform: translateY(0);
      pointer-events: auto;
      margin: 0;
      overflow: visible;
    }}
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] h3,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] h3 {{
      font-size: 18px;
    }}
    .board-shell[data-view-mode="strand"] .event-card[data-detail="summary"] .event-summary,
    .board-shell[data-view-mode="strand"] .event-card[data-detail="headline"] .event-summary {{
      font-size: 14px;
    }}
    .detail-modal {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      background: rgba(3, 5, 8, 0.72);
      backdrop-filter: blur(10px);
    }}
    .detail-modal.open {{ display: flex; }}
    .detail-modal-box {{
      width: min(1100px, 100%);
      height: min(84vh, 920px);
      display: grid;
      grid-template-rows: auto 1fr;
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 18px;
      background: rgba(10, 12, 16, 0.96);
      box-shadow: 0 28px 72px rgba(0,0,0,.45);
      overflow: hidden;
    }}
    .detail-modal-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      background: rgba(255,255,255,.02);
    }}
    .detail-modal-title {{
      margin: 0;
      font-size: 14px;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: #ffd38d;
    }}
    .detail-modal-close {{
      border: 1px solid rgba(255,255,255,.14);
      background: rgba(255,255,255,.04);
      color: var(--text);
      border-radius: 999px;
      width: 34px;
      height: 34px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }}
    .detail-modal-frame {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #0a0d12;
    }}
    @media (max-width: 760px) {{
      html, body {{
        overflow: auto;
      }}
      body {{
        overflow: auto;
      }}
      .page {{
        height: auto;
        min-height: 100vh;
        max-height: none;
        grid-template-rows: auto auto 1fr;
        padding: 10px;
        overflow: visible;
      }}
      .hero {{
        grid-template-columns: 1fr;
      }}
      .toolbar {{
        grid-template-columns: 1fr;
        gap: 8px;
        align-items: stretch;
      }}
      .toolbar-group {{
        width: 100%;
        flex-wrap: wrap;
        justify-content: space-between;
        min-height: 0;
      }}
      .toolbar-group.action-group {{
        justify-content: flex-start;
      }}
      .toolbar-lcd {{
        width: 100%;
        height: 52px;
      }}
      .toolbar-lcd.scale-lcd {{
        min-width: 0;
      }}
      .toolbar input[type="range"] {{
        flex: 1 1 auto;
        min-width: 0;
      }}
      .toolbar-search {{
        width: 100%;
        min-width: 0;
      }}
      .board-shell {{
        min-height: 72vh;
        border-radius: 18px;
      }}
      .board-scroll {{
        height: 72vh;
        min-height: 72vh;
        -webkit-overflow-scrolling: touch;
      }}
      .timeline-axis, .ruler-mark, .year-dot, .event-node {{ left: 22px; }}
      .year-label {{
        left: 46px;
        max-width: 86px;
        padding: 6px 8px;
      }}
      .year-label strong {{
        font-size: 12px;
      }}
      .year-label span {{
        display: none;
      }}
      .year-marker.prominent-above .year-label,
      .year-marker.prominent-below .year-label {{
        left: 46px;
        right: auto;
        width: auto;
        max-width: 86px;
        transform: translateY(-50%);
        text-align: left;
        gap: 0;
        padding: 6px 8px;
      }}
      .year-marker.prominent-above .year-label strong,
      .year-marker.prominent-below .year-label strong {{
        font-size: 12px;
      }}
      .event-card, .event-card.left, .event-card.right {{
        left: 104px; right: auto; width: calc(100% - 118px);
      }}
      .event-connector {{
        display: none;
      }}
      .event-meta-row {{
        align-items: center;
      }}
      .event-chips {{
        max-width: calc(100% - 42px);
      }}
      .audio-dock {{
        position: static;
        left: auto;
        right: auto;
        width: auto;
        margin-top: 10px;
      }}
      .detail-modal {{
        padding: 8px;
      }}
      .detail-modal-box {{
        width: 100%;
        height: calc(100vh - 16px);
        border-radius: 12px;
      }}
      .timeline-minimap {{
        display: none;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div>
        <h1>Timeline</h1>
        <p>Diese Ansicht spannt die gesamte datierte Timeline von 2026 bis in die offene Zukunft auf. Die fünf Radiogegenwartsjahre 2222 bis 2226 bleiben dabei bewusst als dichter Kern der laufenden Story vergrößert.</p>
      </div>
      <div>
        <a class="hero-link" href="../index.html">Zurück zum Kanon</a>
      </div>
    </section>
    <section class="toolbar">
      <div class="toolbar-group search-group">
        <div class="toolbar-lcd search-lcd">
          <input id="storySearch" class="toolbar-search" type="search" placeholder="Story oder Schlagwort suchen" aria-label="Story oder Schlagwort suchen" />
        </div>
      </div>
      <div class="toolbar-group zoom-group">
        <button type="button" id="zoomOut">−</button>
        <div class="toolbar-lcd scale-lcd">
          <input id="zoomRange" type="range" min="0.8" max="8" step="0.01" value="1" />
          <span class="scale-readout" id="scaleReadout"><span class="scale-bar"></span><span class="scale-label" id="scaleLabel">88 px = 1 Jahr</span></span>
        </div>
        <button type="button" id="zoomIn">+</button>
      </div>
      <div class="toolbar-group action-group">
        <button type="button" id="clearStrandFilter" hidden>Filter lösen</button>
        <button type="button" id="jumpToNow">Jetzt</button>
        <button type="button" id="fitView">Fit</button>
        <button type="button" id="resetView">Reset</button>
      </div>
    </section>
    <section class="board-shell" id="timelineShell">
      <canvas class="board-noise-layer" id="noiseLayer"></canvas>
      <div class="timeline-hud">
        <strong id="hudStage">2026</strong>
        <span id="hudFocus">Januar 2026</span>
      </div>
      <div class="timeline-minimap" id="timelineMinimap" aria-label="Minimap">
        <div class="timeline-minimap-title">Überblick</div>
        <div class="timeline-minimap-track" id="timelineMinimapTrack">
          <div class="timeline-minimap-axis"></div>
          <div class="timeline-minimap-breaks" id="timelineMinimapBreaks"></div>
          <div class="timeline-minimap-points" id="timelineMinimapPoints"></div>
          <div class="timeline-minimap-viewport" id="timelineMinimapViewport">
            <div class="timeline-minimap-viewport-box" id="timelineMinimapViewportBox"></div>
          </div>
        </div>
      </div>
      <div class="board-scroll" id="timelineScroll">
      <div class="timeline-board" id="timelineBoard">
        <div class="timeline-axis"></div>
        <div class="timeline-breaks" id="timelineBreaks"></div>
        <div class="timeline-ruler" id="timelineRuler"></div>
        <div class="timeline-years" id="timelineYears"></div>
        <div class="timeline-events" id="timelineEvents"></div>
      </div>
      </div>
    </section>
  </div>
  <aside class="audio-dock">
    <div class="audio-dock-inner">
      <div class="audio-top">
        <button type="button" class="audio-play" id="audioPlay" aria-label="Audio abspielen">▶</button>
        <div class="audio-meta">
          <span class="audio-kicker">Timeline Audio</span>
          <span class="audio-title">Doomsday Radio</span>
        </div>
        <div class="audio-visualizer" aria-hidden="true">
          <span class="beat-bar" id="beatBar1"></span>
          <span class="beat-bar" id="beatBar2"></span>
          <span class="beat-bar" id="beatBar3"></span>
        </div>
        <span class="audio-time" id="audioTime">00:00 / --:--</span>
      </div>
      <input id="audioProgress" class="audio-progress" type="range" min="0" max="1" step="0.001" value="0" aria-label="Audiofortschritt" />
      <audio id="timelineAudio" preload="metadata" playsinline></audio>
    </div>
  </aside>
  <div class="detail-modal" id="detailModal" aria-hidden="true">
    <div class="detail-modal-box" role="dialog" aria-modal="true" aria-labelledby="detailModalTitle">
      <div class="detail-modal-head">
        <h3 class="detail-modal-title" id="detailModalTitle">Detailseite</h3>
        <button type="button" class="detail-modal-close" id="detailModalClose" aria-label="Fenster schließen"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>
      </div>
      <iframe class="detail-modal-frame" id="detailModalFrame" title="Detailseite"></iframe>
    </div>
  </div>
  <script>
    (() => {{
      const milestones = {milestones_json};
      const monthNames = ["Januar","Februar","März","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
      const startMs = Date.UTC(2026, 0, 1, 0, 0, 0);
      const doomMs = Date.UTC(2066, 5, 1, 0, 0, 0);
      const coreStartMs = Date.UTC(2222, 0, 1, 0, 0, 0);
      const coreEndMs = Date.UTC(2227, 0, 1, 0, 0, 0);
      const futureMidMs = Date.UTC(2232, 0, 1, 0, 0, 0);
      const finalEndMs = Date.UTC(2327, 0, 1, 0, 0, 0);
      const endMs = finalEndMs;
      const dayMs = 24 * 60 * 60 * 1000;
      const timelineSegments = [
        {{ start: startMs, end: doomMs, weight: 0.14 }},
        {{ start: doomMs, end: coreStartMs, weight: 0.14 }},
        {{ start: coreStartMs, end: coreEndMs, weight: 0.54 }},
        {{ start: coreEndMs, end: futureMidMs, weight: 0.12 }},
        {{ start: futureMidMs, end: finalEndMs, weight: 0.06 }},
      ];
      const board = document.getElementById("timelineBoard");
      const scroller = document.getElementById("timelineScroll");
      const shell = document.getElementById("timelineShell");
      const ruler = document.getElementById("timelineRuler");
      const breaksLayer = document.getElementById("timelineBreaks");
      const yearsLayer = document.getElementById("timelineYears");
      const eventsLayer = document.getElementById("timelineEvents");
      const minimap = document.getElementById("timelineMinimap");
      const minimapTrack = document.getElementById("timelineMinimapTrack");
      const minimapBreaks = document.getElementById("timelineMinimapBreaks");
      const minimapPoints = document.getElementById("timelineMinimapPoints");
      const minimapViewportBox = document.getElementById("timelineMinimapViewportBox");
      const zoomRange = document.getElementById("zoomRange");
      const storySearch = document.getElementById("storySearch");
      const scaleLabel = document.getElementById("scaleLabel");
      const hudStage = document.getElementById("hudStage");
      const hudFocus = document.getElementById("hudFocus");
      const clearStrandFilterButton = document.getElementById("clearStrandFilter");
      const jumpToNowButton = document.getElementById("jumpToNow");
      const detailModal = document.getElementById("detailModal");
      const detailModalTitle = document.getElementById("detailModalTitle");
      const detailModalClose = document.getElementById("detailModalClose");
      const detailModalFrame = document.getElementById("detailModalFrame");
      const audio = document.getElementById("timelineAudio");
      const audioPlay = document.getElementById("audioPlay");
      const audioProgress = document.getElementById("audioProgress");
      const audioTime = document.getElementById("audioTime");
      const audioDock = document.querySelector(".audio-dock");
      const noiseCanvas = document.getElementById("noiseLayer");
      const noiseCtx = noiseCanvas.getContext("2d", {{ alpha: true }});
      const beatBars = [
        document.getElementById("beatBar1"),
        document.getElementById("beatBar2"),
        document.getElementById("beatBar3"),
      ];
      const audioSources = {audio_sources_json};
      const audioTitle = document.querySelector(".audio-title");
      let targetZoom = Number(zoomRange.value || 1);
      let viewportRenderQueued = false;
      let pointerInsideTimeline = false;
      let audioContext = null;
      let analyser = null;
      let audioData = null;
      let sourceNode = null;
      let beatFrame = 0;
      let noiseFrame = 0;
      let noiseEnergy = 0;
      let noiseImage = null;
      let bassPulse = 0;
      let activeStrandFilter = "";
      let activeSearchQuery = "";
      let minimapDrag = null;
      let suppressMinimapClick = false;
      let currentAudioIndex = -1;
      let audioUnlocked = false;
      const paddingTop = 96;
      const paddingBottom = 140;
      const strandPalette = [
        {{ color: "#ff9b71", rgb: "255, 155, 113" }},
        {{ color: "#5ad1e6", rgb: "90, 209, 230" }},
        {{ color: "#b988ff", rgb: "185, 136, 255" }},
        {{ color: "#8bd450", rgb: "139, 212, 80" }},
        {{ color: "#f3c969", rgb: "243, 201, 105" }},
        {{ color: "#ff7aa2", rgb: "255, 122, 162" }},
        {{ color: "#6fe0b3", rgb: "111, 224, 179" }},
        {{ color: "#7ea8ff", rgb: "126, 168, 255" }},
      ];

      const clamp = (value) => Math.max(0.8, Math.min(8, value));
      const coreDaysTotal = (coreEndMs - coreStartMs) / dayMs;
      const mobileMedia = window.matchMedia("(max-width: 760px)");

      function isMobileLayout() {{
        return mobileMedia.matches;
      }}

      function normalizeStrandKey(value) {{
        return String(value || "").trim().toLowerCase()
          .normalize("NFD")
          .replace(/[\\u0300-\\u036f]/g, "")
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "");
      }}

      function normalizeSearchText(value) {{
        return String(value || "").trim().toLowerCase()
          .normalize("NFD")
          .replace(/[\\u0300-\\u036f]/g, "");
      }}

      function strandColorForKey(key) {{
        const safeKey = normalizeStrandKey(key);
        if (!safeKey) return {{ color: "#ffd38d", rgb: "255, 211, 141" }};
        let hash = 0;
        for (let i = 0; i < safeKey.length; i += 1) {{
          hash = ((hash << 5) - hash + safeKey.charCodeAt(i)) >>> 0;
        }}
        return strandPalette[hash % strandPalette.length];
      }}

      function applyStrandMeta(item) {{
        const strandLabel = String(item.parent_title || "").trim();
        const strandKey = normalizeStrandKey(strandLabel);
        const color = strandColorForKey(strandKey);
        return {{
          ...item,
          strand_key: strandKey,
          strand_label: strandLabel,
          strand_color: color.color,
          strand_rgb: color.rgb,
        }};
      }}

      function updateFilterUi() {{
        const hasActiveFilter = Boolean(activeStrandFilter || activeSearchQuery);
        clearStrandFilterButton.hidden = !hasActiveFilter;
        clearStrandFilterButton.textContent = activeStrandFilter ? "Filter lösen" : "Filter lösen";
      }}

      function milestoneMatchesQuery(item, query) {{
        if (!query) return true;
        const haystack = normalizeSearchText([
          item.title,
          item.summary,
          item.parent_title,
          item.parent_overview,
          item.display_label,
          item.status,
          item.importance_label,
        ].filter(Boolean).join(" "));
        return haystack.includes(query);
      }}

      function minimapSourceItems() {{
        const searchQuery = normalizeSearchText(activeSearchQuery);
        const source = milestones.filter((item) => {{
          if (activeStrandFilter && normalizeStrandKey(item.parent_title) !== activeStrandFilter) return false;
          if (searchQuery && !milestoneMatchesQuery(item, searchQuery)) return false;
          return true;
        }});
        return source.map((item) => applyStrandMeta(item));
      }}

      function timelineBreakSpecs() {{
        return timelineSegments
          .map((segment, index) => {{
            const years = (segment.end - segment.start) / (dayMs * 365.25);
            const count = milestones.filter((item) => item.timestamp_ms >= segment.start && item.timestamp_ms < segment.end).length;
            return {{ segment, index, years, count }};
          }})
          .filter((entry) => entry.segment.start !== coreStartMs && entry.years >= 20 && entry.count <= 8)
          .map((entry) => ({{
            id: `break-${{entry.index}}`,
            timestamp_ms: entry.segment.start + (entry.segment.end - entry.segment.start) / 2,
          }}));
      }}

      function renderMinimap() {{
        if (!minimap || isMobileLayout()) return;
        const trackHeight = minimapTrack.clientHeight || 1;
        minimapPoints.innerHTML = minimapSourceItems().map((item) => {{
          const ratio = Math.max(0, Math.min(1, (item.timestamp_ms - startMs) / Math.max(1, endMs - startMs)));
          return `<span class="timeline-minimap-point" style="top:${{ratio * trackHeight}}px; --strand-rgb:${{item.strand_rgb}};"></span>`;
        }}).join("");
        if (minimapBreaks) {{
          minimapBreaks.innerHTML = timelineBreakSpecs().map((item) => {{
            const ratio = Math.max(0, Math.min(1, (item.timestamp_ms - startMs) / Math.max(1, endMs - startMs)));
            return `<span class="timeline-minimap-break" style="top:${{ratio * trackHeight}}px"></span>`;
          }}).join("");
        }}
      }}

      function renderTimelineBreaks(activeZoom) {{
        if (!breaksLayer) return;
        if (activeStrandFilter || activeSearchQuery) {{
          breaksLayer.innerHTML = "";
          return;
        }}
        breaksLayer.innerHTML = timelineBreakSpecs().map((item) => {{
          const top = yFromTimestamp(item.timestamp_ms, activeZoom);
          return `<span class="timeline-break" style="top:${{top}}px"></span>`;
        }}).join("");
      }}

      function updateMinimapViewport() {{
        if (!minimap || isMobileLayout()) return;
        const trackHeight = minimapTrack.clientHeight || 1;
        const viewportTopTs = timestampFromY(scroller.scrollTop, targetZoom);
        const viewportBottomTs = timestampFromY(scroller.scrollTop + scroller.clientHeight, targetZoom);
        const topRatio = Math.max(0, Math.min(1, (viewportTopTs - startMs) / Math.max(1, endMs - startMs)));
        const bottomRatio = Math.max(0, Math.min(1, (viewportBottomTs - startMs) / Math.max(1, endMs - startMs)));
        const top = topRatio * trackHeight;
        const bottom = bottomRatio * trackHeight;
        minimapViewportBox.style.top = `${{top}}px`;
        minimapViewportBox.style.height = `${{Math.max(18, bottom - top)}}px`;
      }}

      function minimapClientYToRatio(clientY) {{
        const rect = minimapTrack.getBoundingClientRect();
        return Math.max(0, Math.min(1, (clientY - rect.top) / Math.max(1, rect.height)));
      }}

      function focusMinimapRatio(ratio) {{
        const targetTimestamp = startMs + ratio * (endMs - startMs);
        focusOnTimestamp(targetTimestamp, targetZoom);
      }}

      function startMinimapDrag(clientY, mode) {{
        if (!minimap || isMobileLayout()) return;
        const rect = minimapTrack.getBoundingClientRect();
        const boxTop = minimapViewportBox.offsetTop;
        const boxHeight = minimapViewportBox.offsetHeight;
        minimapDrag = {{
          mode,
          rectTop: rect.top,
          rectHeight: Math.max(1, rect.height),
          boxHeight,
          offsetY: mode === "viewport" ? (clientY - rect.top - boxTop) : boxHeight / 2,
          moved: false,
        }};
        minimap.classList.add("dragging");
      }}

      function moveMinimapDrag(clientY) {{
        if (!minimapDrag) return;
        const relativeY = clientY - minimapDrag.rectTop;
        const centerY = minimapDrag.mode === "viewport"
          ? relativeY - minimapDrag.offsetY + minimapDrag.boxHeight / 2
          : relativeY;
        const ratio = Math.max(0, Math.min(1, centerY / minimapDrag.rectHeight));
        minimapDrag.moved = true;
        focusMinimapRatio(ratio);
      }}

      function endMinimapDrag() {{
        if (!minimapDrag) return null;
        const moved = minimapDrag.moved;
        minimapDrag = null;
        minimap?.classList.remove("dragging");
        suppressMinimapClick = moved;
        if (moved) {{
          window.setTimeout(() => {{
            suppressMinimapClick = false;
          }}, 120);
        }}
        return moved;
      }}

      function openDetailModal(href, title) {{
        if (!href) return;
        detailModalTitle.textContent = title || "Detailseite";
        detailModalFrame.src = href;
        detailModal.classList.add("open");
        detailModal.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
      }}

      function closeDetailModal() {{
        detailModal.classList.remove("open");
        detailModal.setAttribute("aria-hidden", "true");
        detailModalFrame.src = "";
        document.body.style.overflow = "";
      }}

      function zoomMode(activeZoom) {{
        if (activeZoom >= 4.2) return "hour";
        if (activeZoom >= 2.3) return "day";
        if (activeZoom >= 1.15) return "month";
        return "year";
      }}

      function pxPerDay(activeZoom) {{
        if (activeZoom >= 4.2) {{
          return 28 + (activeZoom - 4.2) * 30;
        }}
        if (activeZoom >= 2.3) {{
          return 6 + (activeZoom - 2.3) * 11;
        }}
        if (activeZoom >= 1.15) {{
          return 1.4 + (activeZoom - 1.15) * 3.2;
        }}
        return 0.9 + activeZoom * 0.55;
      }}

      function metrics(activeZoom) {{
        const coreWeight = timelineSegments[2].weight;
        const usableHeight = Math.round((coreDaysTotal * pxPerDay(activeZoom)) / coreWeight);
        const boardHeight = paddingTop + usableHeight + paddingBottom;
        board.style.minHeight = `${{boardHeight}}px`;
        document.documentElement.style.setProperty("--card-width", `${{Math.round(320 + activeZoom * 48)}}px`);
        return {{ usableHeight, boardHeight }};
      }}

      function yFromTimestamp(timestampMs, activeZoom) {{
        const {{ usableHeight }} = metrics(activeZoom);
        let clamped = Math.max(startMs, Math.min(endMs, timestampMs));
        let weightedRatio = 0;
        let accumulated = 0;
        for (const segment of timelineSegments) {{
          if (clamped <= segment.end) {{
            const fraction = (clamped - segment.start) / Math.max(1, segment.end - segment.start);
            weightedRatio = accumulated + fraction * segment.weight;
            return paddingTop + weightedRatio * usableHeight;
          }}
          accumulated += segment.weight;
        }}
        return paddingTop + usableHeight;
      }}

      function timestampFromY(y, activeZoom) {{
        const {{ usableHeight }} = metrics(activeZoom);
        const normalized = Math.max(0, Math.min(1, (y - paddingTop) / Math.max(1, usableHeight)));
        let accumulated = 0;
        for (const segment of timelineSegments) {{
          const next = accumulated + segment.weight;
          if (normalized <= next) {{
            const fraction = (normalized - accumulated) / Math.max(0.0001, segment.weight);
            return segment.start + fraction * (segment.end - segment.start);
          }}
          accumulated = next;
        }}
        return endMs;
      }}

      function formatDate(timestampMs, mode) {{
        const date = new Date(timestampMs);
        const year = date.getUTCFullYear();
        const month = monthNames[date.getUTCMonth()];
        const day = date.getUTCDate();
        const hour = String(date.getUTCHours()).padStart(2, "0");
        if (mode === "year") return String(year);
        if (mode === "month") return `${{month}} ${{year}}`;
        if (mode === "day") return `${{day}}. ${{month}} ${{year}}`;
        return `${{day}}. ${{month}} ${{year}}, ${{hour}}:00`;
      }}

      function formatDurationFromDays(days) {{
        const roundedHours = Math.max(1, Math.round(days * 24));
        if (days >= 365 * 2) {{
          const years = Math.round(days / 365);
          return `${{years}} Jahre`;
        }}
        if (days >= 365) {{
          const years = Math.round((days / 365) * 10) / 10;
          return `${{String(years).replace(".", ",")}} Jahre`;
        }}
        if (days >= 60) {{
          const months = Math.round(days / 30);
          return `${{months}} Monate`;
        }}
        if (days >= 30) {{
          const months = Math.round((days / 30) * 10) / 10;
          return `${{String(months).replace(".", ",")}} Monate`;
        }}
        if (days >= 2) {{
          return `${{Math.round(days)}} Tage`;
        }}
        if (days >= 1) {{
          const hours = Math.round(days * 24);
          return hours >= 24 ? "1 Tag" : `${{hours}} Stunden`;
        }}
        return `${{roundedHours}} Stunden`;
      }}

      function updateScaleReadout(activeZoom) {{
        const scaleBarPixels = 88;
        const representedDays = scaleBarPixels / pxPerDay(activeZoom);
        scaleLabel.textContent = `${{scaleBarPixels}} px = ${{formatDurationFromDays(representedDays)}}`;
      }}

      function formatClock(seconds) {{
        if (!Number.isFinite(seconds) || seconds < 0) return "--:--";
        const total = Math.floor(seconds);
        const minutes = String(Math.floor(total / 60)).padStart(2, "0");
        const secs = String(total % 60).padStart(2, "0");
        return `${{minutes}}:${{secs}}`;
      }}

      function updateAudioUi() {{
        const duration = Number.isFinite(audio.duration) ? audio.duration : 0;
        const currentTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
        audioPlay.textContent = audio.paused ? "▶" : "❚❚";
        audioPlay.setAttribute("aria-label", audio.paused ? "Audio abspielen" : "Audio pausieren");
        audioProgress.value = duration > 0 ? String(currentTime / duration) : "0";
        audioTime.textContent = `${{formatClock(currentTime)}} / ${{formatClock(duration)}}`;
      }}

      function updateAudioBackdrop() {{
        shell.dataset.audioState = audio.paused ? "idle" : "playing";
      }}

      async function unlockAudio() {{
        if (audioUnlocked) return true;
        audio.muted = false;
        audio.volume = 0.5;
        try {{
          await ensureAudioGraph();
          if (audio.paused) {{
            await audio.play();
          }}
          audioUnlocked = true;
          updateAudioUi();
          return true;
        }} catch (_error) {{
          audio.muted = true;
          updateAudioUi();
          return false;
        }}
      }}

      function resizeNoiseCanvas() {{
        const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
        const width = Math.max(1, Math.floor(window.innerWidth * dpr));
        const height = Math.max(1, Math.floor(window.innerHeight * dpr));
        if (noiseCanvas.width === width && noiseCanvas.height === height && noiseImage) return;
        noiseCanvas.width = width;
        noiseCanvas.height = height;
        noiseCanvas.style.width = `${{window.innerWidth}}px`;
        noiseCanvas.style.height = `${{window.innerHeight}}px`;
        noiseImage = noiseCtx.createImageData(width, height);
      }}

      function renderNoise() {{
        if (!noiseCtx) return;
        resizeNoiseCanvas();
        const width = noiseCanvas.width;
        const height = noiseCanvas.height;
        const data = noiseImage.data;
        const pulse = Math.max(0, Math.min(1, bassPulse));
        const gatedPulse = pulse > 0.28 ? Math.pow((pulse - 0.28) / 0.72, 1.34) : 0;
        const alpha = Math.min(0.48, gatedPulse * 0.48);
        noiseCanvas.style.opacity = alpha <= 0.002 ? "0" : String(Math.min(0.68, alpha * 2.05));
        noiseCtx.clearRect(0, 0, width, height);
        if (alpha <= 0.002) return;
        for (let i = 0; i < data.length; i += 4) {{
          const value = Math.random() * 255;
          data[i] = value;
          data[i + 1] = value;
          data[i + 2] = value;
          data[i + 3] = Math.floor((Math.random() * 0.78 + 0.48) * alpha * 255);
        }}
        noiseCtx.putImageData(noiseImage, 0, 0);
      }}

      function startNoiseLoop() {{
        if (noiseFrame) return;
        const tick = () => {{
          bassPulse *= 0.72;
          renderNoise();
          noiseFrame = requestAnimationFrame(tick);
        }};
        noiseFrame = requestAnimationFrame(tick);
      }}

      function setBeat(level, bars = null) {{
        const beat = Math.max(0, Math.min(1, level));
        audioDock.style.setProperty("--beat", String(beat));
        const values = bars || [beat, beat * 0.8, beat * 0.6];
        beatBars.forEach((bar, index) => {{
          if (!bar) return;
          const value = Math.max(0.14, Math.min(1, values[index] || 0.14));
          bar.style.transform = `scaleY(${{value}})`;
          bar.style.opacity = String(0.55 + value * 0.45);
        }});
      }}

      function startBeatLoop() {{
        if (!analyser || beatFrame) return;
        const tick = () => {{
          if (!analyser || audio.paused) {{
            beatFrame = 0;
            setBeat(0);
            return;
          }}
          analyser.getByteFrequencyData(audioData);
          const sub = (audioData[1] + audioData[2]) / (2 * 255);
          const bass = (audioData[3] + audioData[4] + audioData[5] + audioData[6]) / (4 * 255);
          const lowMid = (audioData[8] + audioData[10] + audioData[12]) / (3 * 255);
          const beat = Math.max(sub * 1.35, bass * 1.15, (sub * 0.7 + bass * 0.5));
          const bassOnly = Math.max(sub * 1.62, bass * 1.34, sub * 0.96 + bass * 0.6);
          if (bassOnly > 0.3) {{
            bassPulse = Math.max(bassPulse, bassOnly);
          }}
          setBeat(beat, [beat, bass * 0.9, lowMid * 0.55]);
          beatFrame = requestAnimationFrame(tick);
        }};
        beatFrame = requestAnimationFrame(tick);
      }}

      function stopBeatLoop() {{
        if (beatFrame) {{
          cancelAnimationFrame(beatFrame);
          beatFrame = 0;
        }}
        setBeat(0);
      }}

      async function ensureAudioGraph() {{
        if (analyser) {{
          if (audioContext && audioContext.state === "suspended") {{
            await audioContext.resume();
          }}
          return true;
        }}
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return false;
        audioContext = new AudioCtx();
        sourceNode = audioContext.createMediaElementSource(audio);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 128;
        analyser.smoothingTimeConstant = 0.82;
        audioData = new Uint8Array(analyser.frequencyBinCount);
        sourceNode.connect(analyser);
        analyser.connect(audioContext.destination);
        if (audioContext.state === "suspended") {{
          await audioContext.resume();
        }}
        return true;
      }}

      function loadAudioSource(candidate) {{
        return new Promise((resolve) => {{
          const onLoaded = () => {{
            cleanup();
            resolve(true);
          }};
          const onError = () => {{
            cleanup();
            resolve(false);
          }};
          const cleanup = () => {{
            audio.removeEventListener("loadedmetadata", onLoaded);
            audio.removeEventListener("error", onError);
          }};
          audio.addEventListener("loadedmetadata", onLoaded, {{ once: true }});
          audio.addEventListener("error", onError, {{ once: true }});
          audio.src = candidate.src;
          audio.load();
        }});
      }}

      async function attemptMutedAutoplay() {{
        audio.autoplay = true;
        audio.defaultMuted = true;
        audio.muted = true;
        try {{
          await audio.play();
          return true;
        }} catch (_error) {{
          return new Promise((resolve) => {{
            let settled = false;
            const finish = async () => {{
              if (settled) return;
              settled = true;
              cleanup();
              try {{
                await audio.play();
                resolve(true);
              }} catch (_playError) {{
                resolve(false);
              }}
            }};
            const fail = () => {{
              if (settled) return;
              settled = true;
              cleanup();
              resolve(false);
            }};
            const cleanup = () => {{
              audio.removeEventListener("loadeddata", finish);
              audio.removeEventListener("canplay", finish);
              audio.removeEventListener("error", fail);
            }};
            audio.addEventListener("loadeddata", finish, {{ once: true }});
            audio.addEventListener("canplay", finish, {{ once: true }});
            audio.addEventListener("error", fail, {{ once: true }});
            window.setTimeout(fail, 1600);
          }});
        }}
      }}

      function pickRandomAudioIndex(excludeIndex = -1) {{
        if (!audioSources.length) return -1;
        if (audioSources.length === 1) return 0;
        let nextIndex = excludeIndex;
        while (nextIndex === excludeIndex) {{
          nextIndex = Math.floor(Math.random() * audioSources.length);
        }}
        return nextIndex;
      }}

      async function resolveAudioSource() {{
        const preferredIndex = pickRandomAudioIndex(currentAudioIndex);
        const candidateOrder = [];
        if (preferredIndex >= 0) candidateOrder.push(preferredIndex);
        for (let index = 0; index < audioSources.length; index += 1) {{
          if (index === preferredIndex) continue;
          candidateOrder.push(index);
        }}
        for (const index of candidateOrder) {{
          const candidate = audioSources[index];
          const ok = await loadAudioSource(candidate);
          if (ok) {{
            currentAudioIndex = index;
            audioTitle.textContent = candidate.title;
            updateAudioUi();
            return true;
          }}
        }}
        audioTitle.textContent = "Kein Audio gefunden";
        audioPlay.disabled = true;
        audioProgress.disabled = true;
        return false;
      }}

      function aggregateMilestones(activeZoom) {{
        const searchQuery = normalizeSearchText(activeSearchQuery);
        const source = milestones.filter((item) => {{
          if (activeStrandFilter && normalizeStrandKey(item.parent_title) !== activeStrandFilter) return false;
          if (searchQuery && !milestoneMatchesQuery(item, searchQuery)) return false;
          return true;
        }});
        const ordered = source.map((item) => applyStrandMeta(item))
          .sort((a, b) => a.timestamp_ms - b.timestamp_ms || a.title.localeCompare(b.title, "de"));
        if (activeStrandFilter || searchQuery) {{
          return ordered.map((item) => ({{
            ...item,
            kind: "single",
            count: 1,
          }}));
        }}
        if (activeZoom >= 1.55) {{
          return ordered.map((item) => ({{
            ...item,
            kind: "single",
            count: 1,
          }}));
        }}

        const bucketMode = activeZoom < 1.05 ? "year" : activeZoom < 1.35 ? "quarter" : "month";
        const buckets = new Map();

        function bucketKey(item) {{
          const date = new Date(item.timestamp_ms);
          const year = date.getUTCFullYear();
          if (bucketMode === "year") return `${{year}}`;
          if (bucketMode === "quarter") return `${{year}}-q${{Math.floor(date.getUTCMonth() / 3) + 1}}`;
          return `${{year}}-${{String(date.getUTCMonth() + 1).padStart(2, "0")}}`;
        }}

        function bucketLabel(item) {{
          const date = new Date(item.timestamp_ms);
          const year = date.getUTCFullYear();
          if (bucketMode === "year") return String(year);
          if (bucketMode === "quarter") return `Quartal ${{Math.floor(date.getUTCMonth() / 3) + 1}} ${{year}}`;
          return `${{monthNames[date.getUTCMonth()]}} ${{year}}`;
        }}

        for (const item of ordered) {{
          const key = bucketKey(item);
          if (!buckets.has(key)) {{
            buckets.set(key, []);
          }}
          buckets.get(key).push(item);
        }}

        const aggregated = [];
        for (const [key, items] of buckets.entries()) {{
          if (items.length === 1) {{
            aggregated.push({{
              ...items[0],
              kind: "single",
              count: 1,
            }});
            continue;
          }}
          const timestampMs = Math.round(items.reduce((sum, item) => sum + item.timestamp_ms, 0) / items.length);
          const maxImportance = Math.max(...items.map((item) => Number(item.importance || 2)));
          const parentTitles = [...new Set(items.map((item) => item.parent_title).filter(Boolean))].slice(0, 3);
          const topTitles = items.slice(0, 3).map((item) => item.title);
          const uniqueStrands = [...new Set(items.map((item) => item.strand_key).filter(Boolean))];
          const strandKey = uniqueStrands.length === 1 ? uniqueStrands[0] : "";
          const strandLabel = uniqueStrands.length === 1 ? (items.find((item) => item.strand_key === strandKey)?.strand_label || "") : "";
          const strandColor = strandColorForKey(strandLabel || key);
          aggregated.push({{
            id: `cluster-${{key}}`,
            timestamp_ms: timestampMs,
            display_label: bucketLabel(items[0]),
            title: `${{items.length}} Ereignisse`,
            summary: topTitles.join(" · "),
            parent_overview: parentTitles.join(" / "),
            href: "",
            parent_title: bucketMode === "year" ? "Jahresverdichtung" : bucketMode === "quarter" ? "Quartalsverdichtung" : "Monatsverdichtung",
            importance: maxImportance,
            importance_label: `gebündelt`,
            status: "",
            kind: "cluster",
            count: items.length,
            bucket_mode: bucketMode,
            strand_key: strandKey,
            strand_label: strandLabel,
            strand_color: strandColor.color,
            strand_rgb: strandColor.rgb,
          }});
        }}

        return aggregated.sort((a, b) => a.timestamp_ms - b.timestamp_ms || a.title.localeCompare(b.title, "de"));
      }}

      function renderRuler(activeZoom, viewportTop = scroller.scrollTop, viewportHeight = scroller.clientHeight) {{
        const mode = zoomMode(activeZoom);
        const marks = [];
        const anchorYears = [2026, 2066, 2222, 2223, 2224, 2225, 2226, 2232, 2326];
        if (mode === "year") {{
          
        }} else if (mode === "month") {{
          for (const year of anchorYears) {{
            if (year < 2222 || year > 2226) {{
              continue;
            }}
            for (let month = 0; month < 12; month += 1) {{
              const ts = Date.UTC(year, month, 1);
              const top = yFromTimestamp(ts, activeZoom);
              const label = month % 2 === 0 ? `${{monthNames[month]}} ${{year}}` : "";
              const posClass = ((year + month) % 2 === 0) ? "above" : "below";
              marks.push(`<div class="ruler-mark ${{month % 2 === 0 ? "major" : ""}}" style="top:${{top}}px">${{label ? `<span class="ruler-label ${{posClass}}">${{label}}</span>` : ""}}</div>`);
            }}
          }}
        }} else {{
          for (const year of anchorYears) {{
            if (anchorYears.includes(year)) continue;
            const ts = Date.UTC(year, 0, 1);
            const top = yFromTimestamp(ts, activeZoom);
            const posClass = year % 2 === 0 ? "above" : "below";
            marks.push(`<div class="ruler-mark major" style="top:${{top}}px"><span class="ruler-label ${{posClass}}">${{year}}</span></div>`);
          }}
          const bufferHeight = viewportHeight * 0.9;
          const visibleTop = Math.max(0, viewportTop - bufferHeight);
          const visibleBottom = Math.min(board.offsetHeight, viewportTop + viewportHeight + bufferHeight);
          const visibleStartMs = Math.max(coreStartMs, timestampFromY(visibleTop, activeZoom));
          const visibleEndMs = Math.min(coreEndMs, timestampFromY(visibleBottom, activeZoom));
          const stepMs = mode === "day" ? dayMs : 60 * 60 * 1000;
          const firstTs = Math.floor(visibleStartMs / stepMs) * stepMs;
          const dayPixels = pxPerDay(activeZoom);
          const hourPixels = dayPixels / 24;
          const dayLabelEvery = dayPixels >= 96 ? 1 : dayPixels >= 52 ? 2 : dayPixels >= 28 ? 3 : 7;
          const showHourLabels = hourPixels >= 18;
          const hourLabelEvery = hourPixels >= 42 ? 1 : hourPixels >= 30 ? 2 : hourPixels >= 22 ? 4 : 12;
          for (let ts = firstTs; ts <= visibleEndMs; ts += stepMs) {{
            const date = new Date(ts);
            const top = yFromTimestamp(ts, activeZoom);
            const isMonthStart = date.getUTCDate() === 1 && date.getUTCHours() === 0;
            const isDayStart = mode === "hour" && date.getUTCHours() === 0 && ((date.getUTCDate() - 1) % dayLabelEvery === 0);
            const isHourLabel = mode === "hour" && showHourLabels && !isDayStart && date.getUTCHours() % hourLabelEvery === 0;
            const label = isMonthStart
              ? `${{monthNames[date.getUTCMonth()]}} ${{date.getUTCFullYear()}}`
              : isDayStart
                ? `${{date.getUTCDate()}}. ${{monthNames[date.getUTCMonth()]}} ${{date.getUTCFullYear()}}`
                : isHourLabel
                ? `${{String(date.getUTCHours()).padStart(2, "0")}}:00`
                : "";
            const markIndex = Math.floor((ts - startMs) / stepMs);
            const posClass = (markIndex % 2 === 0) ? "above" : "below";
            marks.push(`<div class="ruler-mark ${{isMonthStart || isDayStart ? "major" : ""}}" style="top:${{top}}px">${{label ? `<span class="ruler-label ${{posClass}}">${{label}}</span>` : ""}}</div>`);
          }}
        }}
        ruler.innerHTML = marks.join("");
      }}

      function renderYears(activeZoom) {{
        const labels = {{
          2026: "Die Altwelt und ihre Fehler.",
          2066: "Doomsday.",
          2222: "Staffel 1: Signale am Abgrund.",
          2223: "Staffel 2: Im Umlauf.",
          2224: "Staffel 3: Zugriff.",
          2225: "Staffel 4: Leere Häuser.",
          2226: "Staffel 5: Neue Wildnis.",
          2232: "Fernes Rauschen.",
          2326: "Das Ende: finaler Zustand des Stack."
        }};
        const cards = Array.from(eventsLayer.querySelectorAll(".event-card"));
        const items = [];
        for (const year of [2026, 2066, 2222, 2223, 2224, 2225, 2226, 2232, 2326]) {{
          const top = yFromTimestamp(Date.UTC(year, 0, 1), activeZoom);
          let className = "year-marker compact";
          if (year >= 2222 && year <= 2226) {{
            className = `year-marker ${{year % 2 === 0 ? "prominent-above" : "prominent-below"}}`;
          }} else {{
            className = "year-marker center-below";
          }}
          items.push(`<div class="${{className}}" data-year="${{year}}" style="top:${{top}}px"><span class="year-dot"></span><div class="year-label"><strong>${{year}}</strong><span>${{labels[year]}}</span></div></div>`);
        }}
        yearsLayer.innerHTML = items.join("");

        const boardRect = board.getBoundingClientRect();
        const cardRects = cards.map((card) => card.getBoundingClientRect());
        const collisionScore = (rect) => {{
          if (!rect) return Number.POSITIVE_INFINITY;
          let score = 0;
          const edgePadding = 6;
          if (rect.left < boardRect.left + edgePadding) {{
            score += (boardRect.left + edgePadding - rect.left) * 12;
          }}
          if (rect.right > boardRect.right - edgePadding) {{
            score += (rect.right - (boardRect.right - edgePadding)) * 12;
          }}
          if (rect.top < boardRect.top + edgePadding) {{
            score += (boardRect.top + edgePadding - rect.top) * 12;
          }}
          if (rect.bottom > boardRect.bottom - edgePadding) {{
            score += (rect.bottom - (boardRect.bottom - edgePadding)) * 12;
          }}
          for (const cardRect of cardRects) {{
            const overlapX = Math.max(0, Math.min(rect.right, cardRect.right) - Math.max(rect.left, cardRect.left));
            const overlapY = Math.max(0, Math.min(rect.bottom, cardRect.bottom) - Math.max(rect.top, cardRect.top));
            if (overlapX > 0 && overlapY > 0) {{
              score += overlapX * overlapY;
            }}
          }}
          return score;
        }};

        for (const marker of Array.from(yearsLayer.querySelectorAll(".year-marker"))) {{
          const year = Number(marker.dataset.year || 0);
          const candidates = (year >= 2222 && year <= 2226)
            ? [
                `year-marker ${{year % 2 === 0 ? "prominent-above" : "prominent-below"}}`,
                `year-marker ${{year % 2 === 0 ? "prominent-above" : "prominent-below"}} nudge-up`,
                `year-marker ${{year % 2 === 0 ? "prominent-above" : "prominent-below"}} nudge-down`,
                "year-marker side-left",
                "year-marker side-left nudge-up",
                "year-marker side-right",
                "year-marker side-right nudge-down",
                "year-marker compact",
              ]
            : (year === 2026 || year === 2232 || year === 2326)
            ? [
                "year-marker center-below",
                "year-marker center-above",
                "year-marker center-below nudge-down",
                "year-marker center-above nudge-up",
                "year-marker center-below far-down",
                "year-marker center-above far-up",
              ]
            : [
                "year-marker center-below",
                "year-marker center-above",
                "year-marker center-below nudge-down",
                "year-marker center-above nudge-up",
                "year-marker center-below far-down",
                "year-marker center-above far-up",
              ];
          let applied = candidates[0];
          let bestScore = Number.POSITIVE_INFINITY;
          for (const candidate of candidates) {{
            marker.className = candidate;
            const label = marker.querySelector(".year-label");
            const rect = label ? label.getBoundingClientRect() : null;
            const score = collisionScore(rect);
            if (score < bestScore) {{
              bestScore = score;
              applied = candidate;
            }}
            if (score === 0) {{
              applied = candidate;
              break;
            }}
          }}
          marker.className = applied;
        }}
      }}

      function eventInnerHtml(item) {{
        const chips = [
          item.strand_label ? `<button type="button" class="event-chip strand" data-action="filter-strand" data-strand-key="${{item.strand_key}}" data-strand-label="${{item.strand_label || ""}}" title="Diesen Strang als Liste anzeigen" aria-label="Diesen Strang als Liste anzeigen">${{item.strand_label}}</button>` : "",
          item.importance_label ? `<span class="event-chip">${{item.importance_label}}</span>` : "",
          item.status ? `<span class="event-chip">${{item.status}}</span>` : "",
        ].filter(Boolean).join("");
        const titleHtml = item.href
          ? `<h3><a href="${{item.href}}">${{item.title}}</a></h3>`
          : `<h3>${{item.title}}</h3>`;
        const detailLink = item.href
          ? `<a class="event-link" href="${{item.href}}">Detailseite öffnen</a>`
          : "";
        const filterButton = item.strand_key
          ? `<button type="button" class="event-filter-button" data-action="filter-strand" data-strand-key="${{item.strand_key}}" data-strand-label="${{item.strand_label || ""}}" title="${{activeStrandFilter === item.strand_key ? "Strangfilter aktiv" : "Nur diesen Strang anzeigen"}}" aria-label="${{activeStrandFilter === item.strand_key ? "Strangfilter aktiv" : "Nur diesen Strang anzeigen"}}"><i class="fa-solid ${{activeStrandFilter === item.strand_key ? "fa-circle-check" : "fa-filter"}}" aria-hidden="true"></i></button>`
          : "";
        const countHtml = item.kind === "cluster"
          ? `<div class="event-count">${{item.count}} Meilensteine gebündelt</div>`
          : "";
        return `
          <div class="event-card-inner">
            <div class="event-meta-row">
              <div class="event-chips">${{chips}}</div>
              ${{filterButton}}
            </div>
            ${{countHtml}}
            <div class="event-stamp">${{item.display_label}}</div>
            ${{titleHtml}}
            <p class="event-summary">${{item.summary}}</p>
            <p class="event-overview">${{item.parent_overview}}</p>
            ${{detailLink}}
          </div>`;
      }}

      function renderEvents(activeZoom) {{
        const ordered = aggregateMilestones(activeZoom);
        const existingNodes = new Map(Array.from(eventsLayer.querySelectorAll(".event-node")).map((node) => [node.dataset.eventId, node]));
        const existingConnectors = new Map(Array.from(eventsLayer.querySelectorAll(".event-connector")).map((connector) => [connector.dataset.eventId, connector]));
        const existingCards = new Map(Array.from(eventsLayer.querySelectorAll(".event-card")).map((card) => [card.dataset.eventId, card]));
        const usedIds = new Set();
        const strandMode = Boolean(activeStrandFilter);
        const searchMode = Boolean(activeSearchQuery);
        const gap = strandMode ? 24 : 18;
        const mobileLayout = isMobileLayout();
        const perSide = (mobileLayout || strandMode) ? {{ stack: [] }} : {{ left: [], right: [] }};
        for (const [index, item] of ordered.entries()) {{
          const side = (mobileLayout || strandMode) ? "right" : index % 2 === 0 ? "left" : "right";
          usedIds.add(item.id);
          let node = existingNodes.get(item.id);
          if (!node) {{
            node = document.createElement("div");
            node.className = "event-node";
            node.dataset.eventId = item.id;
            eventsLayer.appendChild(node);
          }}
          node.classList.toggle("cluster", item.kind === "cluster");
          node.dataset.timestampMs = String(item.timestamp_ms);
          node.style.setProperty("--strand-rgb", String(item.strand_rgb || "255, 211, 141"));

          let connector = existingConnectors.get(item.id);
          if (!connector) {{
            connector = document.createElement("div");
            connector.className = `event-connector ${{side}}`;
            connector.dataset.eventId = item.id;
            eventsLayer.appendChild(connector);
          }}
          connector.className = `event-connector ${{side}}`;
          connector.dataset.timestampMs = String(item.timestamp_ms);
          connector.style.setProperty("--strand-rgb", String(item.strand_rgb || "255, 198, 104"));

          let card = existingCards.get(item.id);
          if (!card) {{
            card = document.createElement("article");
            card.className = `event-card ${{side}}`;
            card.dataset.eventId = item.id;
            eventsLayer.appendChild(card);
            requestAnimationFrame(() => {{
              card.style.opacity = "";
              card.style.transform = "";
            }});
          }}
          const renderSignature = [
            item.kind,
            side,
            item.title,
            item.summary,
            item.parent_overview,
            item.display_label,
            item.count,
            item.strand_key,
            activeStrandFilter,
          ].join("|");
          if (card.dataset.renderSignature !== renderSignature || !card.querySelector(".event-card-inner")) {{
            card.className = `event-card ${{side}}`;
            card.innerHTML = eventInnerHtml(item);
            card.dataset.renderSignature = renderSignature;
          }}
          card.dataset.kind = item.kind;
          card.dataset.side = side;
          card.dataset.importance = String(item.importance);
          card.dataset.timestampMs = String(item.timestamp_ms);
          card.dataset.bucketMode = String(item.bucket_mode || "");
          card.dataset.strandKey = String(item.strand_key || "");
          card.style.setProperty("--strand-rgb", String(item.strand_rgb || "255, 211, 141"));
          const exactTop = yFromTimestamp(item.timestamp_ms, activeZoom);
          if (node) node.style.top = `${{exactTop}}px`;
          if (connector) connector.style.top = `${{exactTop}}px`;
          const detailLevel = strandMode
            ? "full"
            : searchMode
            ? "summary"
            : item.kind === "cluster"
            ? "summary"
            : activeZoom >= 2.1
              ? "full"
              : activeZoom >= 1.55
                ? "summary"
                : "headline";
          card.dataset.detail = detailLevel;
          perSide[(mobileLayout || strandMode) ? "stack" : side].push({{ card, exactTop, importance: item.importance }});
        }}

        for (const [id, node] of existingNodes.entries()) {{
          if (usedIds.has(id)) continue;
          node.remove();
        }}
        for (const [id, connector] of existingConnectors.entries()) {{
          if (usedIds.has(id)) continue;
          connector.remove();
        }}
        for (const [id, card] of existingCards.entries()) {{
          if (usedIds.has(id)) continue;
          card.remove();
        }}

        for (const side of Object.keys(perSide)) {{
          let lastBottom = -Infinity;
          for (const entry of perSide[side]) {{
            const desiredTop = strandMode ? lastBottom === -Infinity ? 0 : lastBottom + gap : entry.exactTop - 28;
            const actualTop = Math.max(desiredTop, lastBottom + gap);
            entry.card.style.top = `${{actualTop}}px`;
            lastBottom = actualTop + entry.card.offsetHeight;
          }}
        }}

        if (strandMode) {{
          for (const connector of existingConnectors.values()) {{
            connector.style.width = "0px";
          }}
          return;
        }}

        const axisX = eventsLayer.clientWidth / 2;
        for (const item of ordered) {{
          const card = eventsLayer.querySelector(`.event-card[data-event-id="${{item.id}}"]`);
          const connector = eventsLayer.querySelector(`.event-connector[data-event-id="${{item.id}}"]`);
          if (!card || !connector) continue;
          const cardLeft = card.offsetLeft;
          const cardRight = cardLeft + card.offsetWidth;
          const cardTop = card.offsetTop;
          const cardBottom = cardTop + card.offsetHeight;
          const eventY = yFromTimestamp(item.timestamp_ms, activeZoom);
          const axisGap = 4;
          if ((card.dataset.side || "") === "left") {{
            const startX = Math.max(0, cardRight);
            const startY = Math.max(cardTop, Math.min(cardBottom, eventY));
            const endX = Math.max(startX, axisX - axisGap);
            const endY = eventY;
            const dx = endX - startX;
            const dy = endY - startY;
            const length = Math.hypot(dx, dy);
            const hideConnector = Math.abs(dy) > 42 || length < 18;
            connector.classList.toggle("hidden", hideConnector);
            if (hideConnector) {{
              connector.style.width = "0px";
              continue;
            }}
            connector.style.left = `${{startX}}px`;
            connector.style.top = `${{startY}}px`;
            connector.style.width = `${{length}}px`;
            connector.style.transform = `rotate(${{Math.atan2(dy, dx)}}rad)`;
          }} else {{
            const startX = Math.min(eventsLayer.clientWidth, axisX + axisGap);
            const startY = eventY;
            const endX = Math.max(startX, cardLeft);
            const endY = Math.max(cardTop, Math.min(cardBottom, eventY));
            const dx = endX - startX;
            const dy = endY - startY;
            const length = Math.hypot(dx, dy);
            const hideConnector = Math.abs(dy) > 42 || length < 18;
            connector.classList.toggle("hidden", hideConnector);
            if (hideConnector) {{
              connector.style.width = "0px";
              continue;
            }}
            connector.style.left = `${{startX}}px`;
            connector.style.top = `${{startY}}px`;
            connector.style.width = `${{length}}px`;
            connector.style.transform = `rotate(${{Math.atan2(dy, dx)}}rad)`;
          }}
        }}
      }}

      function updateHud(activeZoom) {{
        const centerY = scroller.scrollTop + scroller.clientHeight / 2;
        const ts = timestampFromY(centerY, activeZoom);
        const date = new Date(ts);
        hudStage.textContent = String(date.getUTCFullYear());
        hudFocus.textContent = formatDate(ts, zoomMode(activeZoom));
      }}

      function focusOnTimestamp(timestampMs, activeZoom) {{
        const exactTop = yFromTimestamp(timestampMs, activeZoom);
        scroller.scrollTop = Math.max(0, exactTop - scroller.clientHeight / 2);
        updateHud(activeZoom);
      }}

      function focusOnFirstVisibleResult(activeZoom) {{
        const ordered = aggregateMilestones(activeZoom);
        if (!ordered.length) return;
        focusOnTimestamp(ordered[0].timestamp_ms, activeZoom);
      }}

      function settleViewportAfterFilterChange(activeZoom) {{
        requestAnimationFrame(() => {{
          if (activeStrandFilter) {{
            scroller.scrollTop = 0;
            updateHud(activeZoom);
            updateMinimapViewport();
            return;
          }}
          if (activeSearchQuery) {{
            focusOnFirstVisibleResult(activeZoom);
            return;
          }}
          const maxScrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
          scroller.scrollTop = Math.min(scroller.scrollTop, maxScrollTop);
          updateHud(activeZoom);
          updateMinimapViewport();
        }});
      }}

      function animateZoomTo(nextZoom, timestampMs) {{
        const startZoom = targetZoom;
        const endZoom = clamp(nextZoom);
        const startedAt = performance.now();
        const duration = 260;
        const frame = (now) => {{
          const progress = Math.min(1, (now - startedAt) / duration);
          const eased = 1 - Math.pow(1 - progress, 3);
          const activeZoom = startZoom + (endZoom - startZoom) * eased;
          targetZoom = activeZoom;
          zoomRange.value = String(activeZoom);
          render(activeZoom);
          focusOnTimestamp(timestampMs, activeZoom);
          if (progress < 1) {{
            requestAnimationFrame(frame);
          }} else {{
            targetZoom = endZoom;
            zoomRange.value = String(endZoom);
            render(endZoom);
            focusOnTimestamp(timestampMs, endZoom);
          }}
        }};
        requestAnimationFrame(frame);
      }}

      function render(activeZoom) {{
        shell.dataset.viewMode = activeStrandFilter ? "strand" : "timeline";
        metrics(activeZoom);
        updateScaleReadout(activeZoom);
        renderRuler(activeZoom);
        renderTimelineBreaks(activeZoom);
        renderEvents(activeZoom);
        renderYears(activeZoom);
        updateHud(activeZoom);
        renderMinimap();
        updateMinimapViewport();
      }}

      function scheduleViewportRender() {{
        if (viewportRenderQueued) return;
        viewportRenderQueued = true;
        requestAnimationFrame(() => {{
          viewportRenderQueued = false;
          renderRuler(targetZoom, scroller.scrollTop, scroller.clientHeight);
          updateHud(targetZoom);
          updateMinimapViewport();
        }});
      }}

      function applyZoom(nextZoom, anchorYRatio = 0.5) {{
        const previousZoom = targetZoom;
        const activeZoom = clamp(nextZoom);
        targetZoom = activeZoom;
        zoomRange.value = String(activeZoom);
        const visibleY = scroller.scrollTop + scroller.clientHeight * anchorYRatio;
        const anchorTimestamp = timestampFromY(visibleY, previousZoom);
        render(activeZoom);
        requestAnimationFrame(() => {{
          const anchoredY = yFromTimestamp(anchorTimestamp, activeZoom);
          scroller.scrollTop = Math.max(0, anchoredY - scroller.clientHeight * anchorYRatio);
          updateHud(activeZoom);
        }});
      }}

      document.getElementById("zoomIn").addEventListener("click", () => applyZoom(targetZoom + 0.12));
      document.getElementById("zoomOut").addEventListener("click", () => applyZoom(targetZoom - 0.12));
      document.getElementById("resetView").addEventListener("click", () => {{
        activeStrandFilter = "";
        activeSearchQuery = "";
        if (storySearch) storySearch.value = "";
        updateFilterUi();
        applyZoom(1);
        scroller.scrollTo({{ top: 0, behavior: "smooth" }});
      }});
      jumpToNowButton.addEventListener("click", () => {{
        activeStrandFilter = "";
        activeSearchQuery = "";
        if (storySearch) storySearch.value = "";
        updateFilterUi();
        animateZoomTo(Math.max(targetZoom, 1.28), coreStartMs + (14 * dayMs));
      }});
      document.getElementById("fitView").addEventListener("click", () => applyZoom(1));
      clearStrandFilterButton.addEventListener("click", () => {{
        activeStrandFilter = "";
        activeSearchQuery = "";
        if (storySearch) storySearch.value = "";
        updateFilterUi();
        render(targetZoom);
        settleViewportAfterFilterChange(targetZoom);
      }});
      zoomRange.addEventListener("input", () => applyZoom(Number(zoomRange.value)));
      storySearch?.addEventListener("input", () => {{
        activeSearchQuery = normalizeSearchText(storySearch.value);
        updateFilterUi();
        render(targetZoom);
        settleViewportAfterFilterChange(targetZoom);
      }});
      eventsLayer.addEventListener("click", (event) => {{
        const filterButton = event.target.closest('[data-action="filter-strand"]');
        if (filterButton) {{
          event.preventDefault();
          event.stopPropagation();
          const nextFilter = String(filterButton.dataset.strandKey || "");
          activeStrandFilter = activeStrandFilter === nextFilter ? "" : nextFilter;
          updateFilterUi();
          render(targetZoom);
          settleViewportAfterFilterChange(targetZoom);
          return;
        }}
        const detailLink = event.target.closest(".event-link, .event-card h3 a");
        if (detailLink) {{
          event.preventDefault();
          const card = detailLink.closest(".event-card");
          openDetailModal(detailLink.getAttribute("href"), card?.querySelector("h3")?.textContent || "Detailseite");
          return;
        }}
        const target = event.target.closest("[data-event-id]");
        if (!target) return;
        const eventId = target.dataset.eventId;
        const card = eventsLayer.querySelector(`.event-card[data-event-id="${{eventId}}"]`);
        const kind = card?.dataset.kind || "";
        if (kind !== "cluster") return;
        event.preventDefault();
        const timestampMs = Number(card?.dataset.timestampMs || target.dataset.timestampMs || 0);
        if (!timestampMs) return;
        animateZoomTo(1.55, timestampMs);
      }});
      detailModalClose.addEventListener("click", closeDetailModal);
      detailModal.addEventListener("click", (event) => {{
        if (event.target === detailModal) closeDetailModal();
      }});
      minimapViewportBox?.addEventListener("pointerdown", (event) => {{
        if (isMobileLayout()) return;
        event.preventDefault();
        event.stopPropagation();
        minimapViewportBox.setPointerCapture?.(event.pointerId);
        startMinimapDrag(event.clientY, "viewport");
      }});
      minimapTrack?.addEventListener("pointerdown", (event) => {{
        if (isMobileLayout()) return;
        if (event.target === minimapViewportBox) return;
        event.preventDefault();
        startMinimapDrag(event.clientY, "track");
        moveMinimapDrag(event.clientY);
      }});
      window.addEventListener("pointermove", (event) => {{
        if (!minimapDrag) return;
        event.preventDefault();
        moveMinimapDrag(event.clientY);
      }}, {{ passive: false }});
      window.addEventListener("pointerup", () => {{
        endMinimapDrag();
      }});
      window.addEventListener("pointercancel", () => {{
        endMinimapDrag();
      }});
      minimap?.addEventListener("click", (event) => {{
        if (suppressMinimapClick) return;
        const ratio = minimapClientYToRatio(event.clientY);
        focusMinimapRatio(ratio);
      }});
      window.addEventListener("keydown", (event) => {{
        if (event.key === "Escape" && detailModal.classList.contains("open")) {{
          closeDetailModal();
        }}
      }});
      audioPlay.addEventListener("click", async () => {{
        if (!audioUnlocked) {{
          await unlockAudio();
          return;
        }}
        const hasSource = audio.currentSrc || audio.src;
        if (!hasSource) return;
        if (audio.paused) {{
          try {{
            await ensureAudioGraph();
            await audio.play();
          }} catch (_error) {{}}
        }} else {{
          audio.pause();
        }}
        updateAudioUi();
      }});
      audioProgress.addEventListener("input", () => {{
        if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
        audio.currentTime = Number(audioProgress.value) * audio.duration;
        updateAudioUi();
      }});
      audio.addEventListener("timeupdate", updateAudioUi);
      audio.addEventListener("play", () => {{
        updateAudioBackdrop();
        updateAudioUi();
        startBeatLoop();
      }});
      audio.addEventListener("pause", () => {{
        updateAudioBackdrop();
        updateAudioUi();
        stopBeatLoop();
      }});
      audio.addEventListener("loadedmetadata", updateAudioUi);
      audio.addEventListener("ended", async () => {{
        updateAudioUi();
        stopBeatLoop();
        const ok = await resolveAudioSource();
        if (!ok) return;
        try {{
          await ensureAudioGraph();
          await audio.play();
        }} catch (_error) {{}}
      }});

      shell.addEventListener("pointerenter", () => {{ pointerInsideTimeline = true; }});
      shell.addEventListener("pointerleave", () => {{ pointerInsideTimeline = false; }});
      window.addEventListener("wheel", (event) => {{
        if (!(event.ctrlKey || event.metaKey)) return;
        if (!pointerInsideTimeline && !shell.contains(event.target)) return;
        event.preventDefault();
        const rect = scroller.getBoundingClientRect();
        const anchor = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
        applyZoom(targetZoom + (-event.deltaY * 0.0025), anchor);
      }}, {{ passive: false, capture: true }});

      let touchCache = new Map();
      let pinchDistance = 0;
      let pinchOriginY = 0;
      function touchDistance() {{
        const touches = Array.from(touchCache.values());
        if (touches.length < 2) return 0;
        const [a, b] = touches;
        return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      }}
      scroller.addEventListener("pointerdown", (event) => {{
        if (event.pointerType !== "touch") return;
        touchCache.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});
        if (touchCache.size === 2) {{
          pinchDistance = touchDistance();
          const touches = Array.from(touchCache.values());
          pinchOriginY = (touches[0].clientY + touches[1].clientY) / 2;
        }}
      }});
      scroller.addEventListener("pointermove", (event) => {{
        if (event.pointerType !== "touch" || !touchCache.has(event.pointerId)) return;
        touchCache.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});
        if (touchCache.size < 2 || !pinchDistance) return;
        event.preventDefault();
        const nextDistance = touchDistance();
        const rect = scroller.getBoundingClientRect();
        const anchor = Math.max(0, Math.min(1, (pinchOriginY - rect.top) / rect.height));
        applyZoom(targetZoom + (nextDistance - pinchDistance) / 280, anchor);
        pinchDistance = nextDistance;
      }}, {{ passive: false }});
      const clearPointer = (event) => {{
        touchCache.delete(event.pointerId);
        if (touchCache.size < 2) pinchDistance = 0;
      }};
      scroller.addEventListener("pointerup", clearPointer);
      scroller.addEventListener("pointercancel", clearPointer);
      scroller.addEventListener("scroll", scheduleViewportRender, {{ passive: true }});
      window.addEventListener("resize", () => {{
        resizeNoiseCanvas();
        render(targetZoom);
      }});

      render(targetZoom);
      updateFilterUi();
      audio.muted = false;
      audio.volume = 0.5;
      updateAudioBackdrop();
      updateAudioUi();
      resizeNoiseCanvas();
      startNoiseLoop();
      resolveAudioSource().then((ok) => {{
        if (!ok) return;
        updateAudioUi();
      }});
    }})();
  </script>
  <script defer src="/analytics-loader.js"></script>
</body>
</html>
"""


def _timeline_template(
    *,
    events: list[dict[str, object]],
    page_url: str,
    description: str,
) -> str:
    milestone_entries: list[dict[str, object]] = []
    synthetic_stage_entries: list[dict[str, object]] = []
    milestone_id = 0
    month_names = [
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ]
    synthetic_stage_specs = {
        "past": {
            "base": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "spacing_days": 480,
            "label": "Vorlauf",
        },
        "doom": {
            "base": datetime(2066, 3, 1, tzinfo=timezone.utc),
            "spacing_days": 44,
            "label_mode": "month_year",
        },
        "future": {
            "base": datetime(2228, 1, 1, tzinfo=timezone.utc),
            "spacing_days": 220,
            "label": "Nachlauf",
        },
    }
    synthetic_stage_counters = {key: 0 for key in synthetic_stage_specs}
    for event in events:
        for stage in event.get("stages", []):
            if not isinstance(stage, dict):
                continue
            stage_key = str(stage.get("key", ""))
            for milestone in stage.get("milestones", []):
                if not isinstance(milestone, dict):
                    continue
                milestone_entries.append(
                    {
                        "id": f"m-{milestone_id}",
                        "timestamp_ms": int(milestone.get("timestamp_ms", 0)),
                        "display_label": str(milestone.get("label", "")),
                        "title": _escape_html(str(milestone.get("title", ""))),
                        "summary": _escape_html(str(milestone.get("summary", ""))),
                        "href": _escape_html(str(event.get("href", ""))),
                        "parent_title": _escape_html(str(event.get("title", ""))),
                        "parent_overview": _escape_html(str(event.get("overview", ""))),
                        "importance": int(event.get("importance", 2)),
                        "importance_label": _escape_html(str(event.get("importance_label", ""))),
                        "status": _escape_html(str(event.get("status", ""))),
                    }
                )
                milestone_id += 1
            if stage_key not in synthetic_stage_specs:
                continue
            if stage.get("milestones"):
                continue
            stage_summary = str(stage.get("summary", "")).strip() or str(stage.get("body", "")).strip()
            if not stage_summary:
                continue
            spec = synthetic_stage_specs[stage_key]
            synthetic_index = synthetic_stage_counters[stage_key]
            synthetic_stage_counters[stage_key] += 1
            synthetic_dt = spec["base"] + timedelta(days=synthetic_index * spec["spacing_days"])
            timestamp_ms = int(synthetic_dt.timestamp() * 1000)
            display_label = str(spec.get("label", ""))
            if spec.get("label_mode") == "month_year":
                display_label = f"{month_names[synthetic_dt.month - 1]} {synthetic_dt.year}"
            synthetic_stage_entries.append(
                {
                    "id": f"s-{stage_key}-{milestone_id}",
                    "timestamp_ms": timestamp_ms,
                    "display_label": display_label,
                    "title": _escape_html(str(event.get("title", ""))),
                    "summary": _escape_html(stage_summary[:320]),
                    "href": _escape_html(str(event.get("href", ""))),
                    "parent_title": _escape_html(str(event.get("title", ""))),
                    "parent_overview": _escape_html(str(stage.get("label", ""))),
                    "importance": int(event.get("importance", 2)),
                    "importance_label": _escape_html(str(event.get("importance_label", ""))),
                    "status": _escape_html(str(event.get("status", ""))),
                }
            )
            milestone_id += 1
    milestone_entries.extend(synthetic_stage_entries)
    if milestone_entries:
        return _render_absolute_timeline_page(
            milestones=milestone_entries,
            page_url=page_url,
            description=description,
            audio_sources=_timeline_audio_sources(_repo_root()),
        )

    stage_order = [
        ("past", "Vor 2026", "Vorwelt, Technikursprünge und lange Vorzeichen."),
        ("doom", "Juni 2066", "Der eigentliche Weltbruch des Doomsday."),
        ("year1", "2222", "Staffel 1: Signale am Abgrund."),
        ("year2", "2223", "Staffel 2: Im Umlauf."),
        ("year3", "2224", "Staffel 3: Zugriff."),
        ("year4", "2225", "Staffel 4: Leere Häuser."),
        ("year5", "2226", "Staffel 5: Neue Wildnis."),
        ("future", "Danach", "Endgame, Langzeitfolgen und offene Zukunftsachsen."),
    ]

    milestones_by_stage: dict[str, list[dict[str, object]]] = {key: [] for key, _, _ in stage_order}
    for event in events:
        title = str(event.get("title", ""))
        href = str(event.get("href", ""))
        overview = str(event.get("overview", ""))
        status = str(event.get("status", ""))
        event_type = str(event.get("type", ""))
        importance = int(event.get("importance", 2))
        importance_label = str(event.get("importance_label", ""))
        for stage in event.get("stages", []):
            if not isinstance(stage, dict):
                continue
            summary = str(stage.get("summary", "")).strip()
            body = str(stage.get("body", "")).strip()
            if not summary and not body:
                continue
            stage_key = str(stage.get("key", ""))
            if stage_key not in milestones_by_stage:
                continue
            milestones_by_stage[stage_key].append(
                {
                    "title": title,
                    "href": href,
                    "overview": overview,
                    "summary": summary,
                    "body": body,
                    "status": status,
                    "type": event_type,
                    "importance": importance,
                    "importance_label": importance_label,
                }
            )

    stage_blocks: list[str] = []
    for stage_key, stage_label, stage_description in stage_order:
        milestones = sorted(
            milestones_by_stage.get(stage_key, []),
            key=lambda item: (-int(item.get("importance", 2)), str(item.get("title", "")).casefold()),
        )
        milestone_cards: list[str] = []
        for idx, item in enumerate(milestones):
            side = "left" if idx % 2 == 0 else "right"
            chips = [chip for chip in [str(item.get("importance_label", "")), str(item.get("status", "")), str(item.get("type", ""))] if chip]
            chip_html = "".join(
                f'<span class="event-chip">{_escape_html(chip)}</span>' for chip in chips[:3]
            )
            milestone_cards.append(
                "\n".join(
                    [
                        f'          <article class="milestone-card milestone-card-{side}" data-importance="{int(item.get("importance", 2))}" style="--stack-index:{idx};">',
                        '            <div class="milestone-card-inner">',
                        f'              <div class="event-chips">{chip_html}</div>' if chip_html else '              <div class="event-chips"></div>',
                        f'              <h3><a href="{_escape_html(str(item.get("href", "")))}">{_escape_html(str(item.get("title", "")))}</a></h3>',
                        f'              <p class="milestone-summary">{_escape_html(str(item.get("summary", "")))}</p>',
                        f'              <p class="milestone-body">{_escape_html(str(item.get("body", "")))}</p>',
                        f'              <p class="milestone-overview">{_escape_html(str(item.get("overview", "")))}</p>',
                        f'              <a class="event-link" href="{_escape_html(str(item.get("href", "")))}">Detailseite öffnen</a>',
                        "            </div>",
                        "          </article>",
                    ]
                )
            )
        if not milestone_cards:
            milestone_cards.append(
                "\n".join(
                    [
                        '          <article class="milestone-card milestone-card-left milestone-card-empty" data-importance="1" style="--stack-index:0;">',
                        '            <div class="milestone-card-inner">',
                        '              <h3>Noch keine Achse</h3>',
                        '              <p class="milestone-summary">Für diese Zeitstufe ist noch kein belastbarer Meilenstein hinterlegt.</p>',
                        "            </div>",
                        "          </article>",
                    ]
                )
            )
        stage_blocks.append(
            "\n".join(
                [
                    f'        <section class="timeline-stage" data-stage="{_escape_html(stage_key)}" style="--card-count:{max(1, len(milestone_cards))};">',
                    '          <div class="timeline-anchor">',
                    '            <span class="timeline-dot" aria-hidden="true"></span>',
                    f'            <div class="timeline-label"><strong>{_escape_html(stage_label)}</strong><span>{_escape_html(stage_description)}</span></div>',
                    "          </div>",
                    '          <div class="timeline-stage-cards">',
                    "\n".join(milestone_cards),
                    "          </div>",
                    "        </section>",
                ]
            )
        )

    return f"""<!doctype html>
<html lang="de" data-mode="ddd">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Doomsday Dispatch – Timeline</title>
  <meta name="description" content="{_escape_html(description)}" />
  <link rel="canonical" href="{_escape_html(page_url)}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Doomsday Radio" />
  <meta property="og:locale" content="de_DE" />
  <meta property="og:title" content="Doomsday Dispatch – Timeline" />
  <meta property="og:description" content="{_escape_html(description)}" />
  <meta property="og:url" content="{_escape_html(page_url)}" />
  <meta property="og:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Doomsday Dispatch – Timeline" />
  <meta name="twitter:description" content="{_escape_html(description)}" />
  <meta name="twitter:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <style>
    :root {{
      --bg: #0a0d12;
      --panel: rgba(25, 18, 12, 0.88);
      --panel-strong: rgba(43, 30, 18, 0.92);
      --line: rgba(255, 198, 104, 0.24);
      --line-strong: rgba(255, 198, 104, 0.44);
      --text: #f3e7c9;
      --muted: #ceb991;
      --accent: #ffb347;
      --accent-hot: #ff7b39;
      --stub-width: 360px;
      --epoch-width: 360px;
      --axis-gap: 180px;
      --card-width: 420px;
      --anchor-height: 74px;
      --dot-size: 16px;
      --tick-step: 48px;
      --stage-span: 420px;
      --card-stack-gap: 170px;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      font-family: "Avenir Next", "Trebuchet MS", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top, rgba(255, 123, 57, 0.14), transparent 28%),
        radial-gradient(circle at bottom left, rgba(255, 179, 71, 0.10), transparent 24%),
        linear-gradient(180deg, #06080d 0%, #0d1118 48%, #050608 100%);
      overflow: hidden;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.02) 0, rgba(255,255,255,0.02) 1px, transparent 1px),
        linear-gradient(180deg, rgba(255,255,255,0.015) 0, rgba(255,255,255,0.015) 1px, transparent 1px);
      background-size: 72px 72px;
      mask-image: radial-gradient(circle at center, black 42%, transparent 92%);
      opacity: .45;
    }}
    .page {{
      height: 100vh;
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 10px;
      padding: 14px;
    }}
    .hero, .toolbar {{
      position: relative;
      z-index: 1;
      border: 1px solid rgba(255,255,255,.06);
      border-radius: 18px;
      background: rgba(10, 12, 16, 0.72);
      box-shadow: 0 18px 44px rgba(0,0,0,.28);
      backdrop-filter: blur(12px);
    }}
    .hero {{
      padding: 16px 18px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 14px;
      align-items: start;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(26px, 4vw, 48px);
      line-height: .98;
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    .hero p {{
      margin: 0;
      max-width: 64ch;
      color: var(--muted);
      line-height: 1.5;
    }}
    .hero-aside {{
      display: grid;
      gap: 10px;
      justify-items: end;
    }}
    .hero-meta {{
      display: flex;
      flex-wrap: wrap;
      justify-content: end;
      gap: 10px;
    }}
    .hero-pill, .event-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 198, 104, .18);
      background: rgba(255, 179, 71, 0.05);
      color: #f3c980;
      font-size: 11px;
      letter-spacing: .04em;
      text-transform: uppercase;
    }}
    .hero-link {{
      color: var(--text);
      text-decoration: none;
      border: 1px solid rgba(255, 198, 104, .28);
      padding: 12px 16px;
      border-radius: 999px;
      background: rgba(0,0,0,.18);
      transition: transform .2s ease, border-color .2s ease, background .2s ease;
    }}
    .hero-link:hover {{
      transform: translateY(-1px);
      border-color: rgba(255, 198, 104, .48);
      background: rgba(255, 179, 71, 0.12);
    }}
    .toolbar {{
      padding: 10px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: -2px;
    }}
    .toolbar-group {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .toolbar button {{
      border: 1px solid rgba(255, 198, 104, .28);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 9px 12px;
      border-radius: 999px;
      cursor: pointer;
      transition: background .2s ease, transform .2s ease, border-color .2s ease;
    }}
    .toolbar button:hover {{
      transform: translateY(-1px);
      background: rgba(255, 179, 71, 0.12);
      border-color: rgba(255, 198, 104, .48);
    }}
    .zoom-readout {{
      min-width: 62px;
      font-variant-numeric: tabular-nums;
      color: #ffd38d;
      text-align: right;
    }}
    .toolbar input[type="range"] {{
      width: min(280px, 48vw);
      accent-color: var(--accent);
    }}
    .board-shell {{
      min-height: 0;
      position: relative;
      z-index: 1;
      border-radius: 24px;
      border: 1px solid rgba(255,255,255,.06);
      overflow: hidden;
      background: rgba(7, 9, 12, 0.94);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
    }}
    .timeline-hud {{
      position: absolute;
      top: 14px;
      right: 14px;
      z-index: 4;
      display: grid;
      gap: 6px;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(255,255,255,.08);
      background: rgba(10, 12, 16, 0.78);
      backdrop-filter: blur(10px);
      box-shadow: 0 12px 28px rgba(0,0,0,.22);
      min-width: 180px;
    }}
    .timeline-hud strong {{
      font-size: 12px;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #ffd38d;
    }}
    .timeline-hud span {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }}
    .board-scroll {{
      width: 100%;
      height: 100%;
      overflow: auto;
      scroll-behavior: smooth;
      overscroll-behavior: contain;
      touch-action: pan-y;
    }}
    .timeline-board {{
      --line-offset: 50%;
      transition: min-height .18s ease-out;
      position: relative;
      min-height: 100%;
      padding: 36px 18px 120px;
      display: block;
    }}
    .timeline-board::before {{
      content: "";
      position: absolute;
      top: 0;
      bottom: 0;
      left: 50%;
      width: 1px;
      transform: translateX(-50%);
      background: linear-gradient(180deg, transparent 0%, rgba(255, 198, 104, .52) 8%, rgba(255, 198, 104, .28) 92%, transparent 100%);
      box-shadow: 0 0 24px rgba(255, 179, 71, .18);
      transition: left .18s ease-out;
    }}
    .timeline-stage {{
      position: relative;
      min-height: max(var(--stage-span), calc(var(--anchor-height) + 28px + var(--card-count, 1) * var(--card-stack-gap)));
    }}
    .timeline-anchor {{
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      min-height: var(--anchor-height);
      transition: min-height .18s ease-out;
    }}
    .timeline-dot {{
      position: absolute;
      left: 50%;
      top: 12px;
      width: var(--dot-size);
      height: var(--dot-size);
      transform: translateX(-50%);
      border-radius: 999px;
      background: linear-gradient(180deg, #ffd38d, #ff8f4d);
      box-shadow:
        0 0 0 6px rgba(255, 179, 71, .08),
        0 0 24px rgba(255, 123, 57, .24);
      transition: left .18s ease-out, transform .18s ease-out;
    }}
    .timeline-label {{
      position: relative;
      left: calc(50% + 22px);
      max-width: min(34vw, 420px);
      display: grid;
      gap: 4px;
      transition: left .18s ease-out, max-width .18s ease-out;
    }}
    .timeline-label strong {{
      font-size: 14px;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #ffd38d;
    }}
    .timeline-label span {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }}
    .timeline-stage-cards {{
      position: absolute;
      inset: 0;
    }}
    .timeline-ruler {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 0;
    }}
    .timeline-ruler-mark {{
      position: absolute;
      left: 50%;
      transform: translate(-50%, -50%);
      width: 0;
      height: 0;
    }}
    .timeline-ruler-mark::before {{
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 16px;
      height: 1px;
      transform: translate(-50%, -50%);
      background: rgba(255, 198, 104, .28);
      box-shadow: 0 0 10px rgba(255, 179, 71, .12);
    }}
    .timeline-ruler-mark[data-level="mid"]::before {{
      width: 26px;
      background: rgba(255, 198, 104, .38);
    }}
    .timeline-ruler-mark[data-level="major"]::before {{
      width: 42px;
      background: rgba(255, 198, 104, .54);
    }}
    .timeline-ruler-label {{
      position: absolute;
      top: 50%;
      left: calc(50% + 34px);
      transform: translateY(-50%);
      color: rgba(243, 231, 201, .55);
      font-size: 11px;
      letter-spacing: .08em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .milestone-card {{
      position: absolute;
      top: calc(var(--anchor-height) + 18px + var(--stack-index, 0) * var(--card-stack-gap));
      width: min(var(--card-width), calc(50% - 46px));
      transition: width .18s ease-out, margin .18s ease-out, opacity .18s ease-out;
    }}
    .milestone-card-left {{
      margin-right: calc(50% + 28px);
      justify-self: end;
    }}
    .milestone-card-right {{
      margin-left: calc(50% + 28px);
      justify-self: start;
    }}
    .milestone-card::before {{
      content: "";
      position: absolute;
      top: 24px;
      width: 28px;
      height: 1px;
      background: rgba(255, 198, 104, .24);
    }}
    .milestone-card-left::before {{
      right: -28px;
    }}
    .milestone-card-right::before {{
      left: -28px;
    }}
    .milestone-card-inner {{
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 16px;
      padding: 14px 16px;
      background: rgba(18, 21, 28, 0.78);
      box-shadow: 0 8px 24px rgba(0,0,0,.18);
      display: grid;
      gap: 10px;
      transition: transform .2s ease, border-color .2s ease, background .2s ease, padding .18s ease-out;
    }}
    .milestone-card-inner:hover {{
      transform: translateY(-1px);
      border-color: rgba(255, 198, 104, .22);
      background: rgba(24, 28, 36, 0.88);
    }}
    .milestone-card h3 {{
      margin: 0;
      font-size: clamp(16px, 1.5vw, 22px);
      line-height: 1.08;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    .milestone-card h3 a {{
      color: inherit;
      text-decoration: none;
    }}
    .milestone-card h3 a:hover {{
      color: #ffd38d;
    }}
    .milestone-summary,
    .milestone-body,
    .milestone-overview {{
      margin: 0;
      line-height: 1.5;
    }}
    .milestone-summary {{
      font-size: 14px;
      color: var(--text);
    }}
    .milestone-body,
    .milestone-overview {{
      font-size: 14px;
      color: var(--muted);
    }}
    .event-link {{
      color: #ffd38d;
      text-decoration: none;
      font-size: 14px;
    }}
    .milestone-card-empty .milestone-card-inner {{
      opacity: .62;
      border-style: dashed;
    }}
    .milestone-card[data-detail="compact"] .milestone-body,
    .milestone-card[data-detail="compact"] .milestone-overview,
    .milestone-card[data-detail="compact"] .milestone-summary,
    .milestone-card[data-detail="compact"] .event-link,
    .milestone-card[data-detail="compact"] .event-chips {{
      display: none;
    }}
    .milestone-card[data-detail="compact"] .milestone-card-inner {{
      padding-top: 12px;
      padding-bottom: 12px;
    }}
    .milestone-card[data-detail="summary"] .milestone-body,
    .milestone-card[data-detail="summary"] .milestone-overview {{
      display: none;
    }}
    .milestone-card[data-detail="summary"] .event-link {{
      display: none;
    }}
    .board-shell[data-density="far"] .milestone-card[data-importance="1"] {{
      opacity: .78;
    }}
    .board-shell[data-density="near"] .milestone-card[data-importance="4"] .milestone-card-inner {{
      border-color: rgba(255, 123, 57, .32);
      box-shadow: 0 12px 30px rgba(255, 123, 57, .10);
    }}
    @media (max-width: 960px) {{
      .page {{
        padding: 10px;
      }}
      .hero {{
        grid-template-columns: 1fr;
      }}
      .hero-aside {{
        justify-items: start;
      }}
      .toolbar {{ align-items: start; }}
      .timeline-label {{
        left: calc(50% + 18px);
        max-width: min(62vw, 360px);
      }}
      .milestone-card {{
        width: min(460px, calc(100% - 54px));
      }}
    }}
    @media (max-width: 760px) {{
      .timeline-board::before,
      .timeline-dot {{
        left: 22px;
      }}
      .timeline-label {{
        left: 48px;
        max-width: calc(100% - 58px);
      }}
      .milestone-card,
      .milestone-card-left,
      .milestone-card-right {{
        width: calc(100% - 54px);
        margin-left: 54px;
        margin-right: 0;
        justify-self: start;
      }}
      .milestone-card::before {{
        left: -28px;
        right: auto;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div>
        <h1>Timeline</h1>
        <p>Eine minimalistische Kanon-Zeitleiste mit zentraler Achse. Das Radio-Jetzt ist in fünf laufende Jahre aufgeteilt, damit große Storylines mit eigenen Längen, Meilensteinen und Überlagerungen ineinandergreifen können.</p>
      </div>
      <div class="hero-aside">
        <div class="hero-meta">
          <span class="hero-pill">{len(events)} Themenachsen</span>
          <span class="hero-pill">5 Radio-Jahre</span>
          <span class="hero-pill">Auto-generiert</span>
        </div>
        <a class="hero-link" href="../index.html">Zurück zum Kanon</a>
      </div>
    </section>

    <section class="toolbar">
      <div class="toolbar-group">
        <button type="button" id="zoomOut">−</button>
        <input id="zoomRange" type="range" min="0.75" max="2.2" step="0.01" value="1" />
        <button type="button" id="zoomIn">+</button>
        <span class="zoom-readout" id="zoomReadout">100%</span>
      </div>
      <div class="toolbar-group">
        <button type="button" id="fitView">Fit</button>
        <button type="button" id="resetView">Reset</button>
        <span class="hero-pill">Scroll = Navigation, Zoom per Pinch oder Buttons</span>
      </div>
    </section>

    <section class="board-shell" id="timelineShell" data-density="mid">
      <div class="timeline-hud" id="timelineHud">
        <strong id="hudStage">2222</strong>
        <span id="hudFocus">Januar 2222</span>
      </div>
      <div class="board-scroll" id="timelineScroll">
        <div class="timeline-board" id="timelineBoard">
          <div class="timeline-ruler" id="timelineRuler" aria-hidden="true"></div>
{chr(10).join(stage_blocks)}
        </div>
      </div>
    </section>
  </div>
  <script>
    (() => {{
      const shell = document.getElementById("timelineShell");
      const scroller = document.getElementById("timelineScroll");
      const board = document.getElementById("timelineBoard");
      const boardShell = document.getElementById("timelineShell");
      const ruler = document.getElementById("timelineRuler");
      const zoomRange = document.getElementById("zoomRange");
      const zoomReadout = document.getElementById("zoomReadout");
      const hudStage = document.getElementById("hudStage");
      const hudFocus = document.getElementById("hudFocus");
      const cards = Array.from(document.querySelectorAll(".milestone-card"));
      const stages = Array.from(document.querySelectorAll(".timeline-stage"));
      const stageYears = {{
        year1: 2222,
        year2: 2223,
        year3: 2224,
        year4: 2225,
        year5: 2226,
      }};
      const monthNames = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
      ];
      const minZoom = 0.75;
      const maxZoom = 2.2;
      let zoom = Number(zoomRange.value || 1);
      let pinchActive = false;
      let pinchDistance = 0;
      let pinchOriginY = 0;
      let targetZoom = zoom;
      let pointerInsideTimeline = false;
      const logicalUnits = 140;
      let currentMode = null;

      function clamp(value) {{
        return Math.max(minZoom, Math.min(maxZoom, value));
      }}

      function zoomMode(activeZoom) {{
        return activeZoom >= 1.85
          ? {{ label: "Stunde", step: 1, majorEvery: 4, midEvery: 1 }}
          : activeZoom >= 1.45
            ? {{ label: "Tag", step: 1, majorEvery: 5, midEvery: 1 }}
            : activeZoom >= 1.05
              ? {{ label: "Monat", step: 1, majorEvery: 6, midEvery: 1 }}
            : {{ label: "Jahr", step: 1, majorEvery: 4, midEvery: 2 }};
      }}

      function formatFocusLabel(stageKey, progress, mode) {{
        const year = stageYears[stageKey];
        if (!year || !mode) {{
          if (stageKey === "doom") return "Juni 2066";
          if (stageKey === "past") return "Vor 2026";
          if (stageKey === "future") return "Nach 2226";
          return "";
        }}
        if (mode.label === "Jahr") {{
          return String(year);
        }}
        if (mode.label === "Monat") {{
          const monthIndex = Math.min(11, Math.floor(progress * 12));
          return `${{monthNames[monthIndex]}} ${{year}}`;
        }}
        if (mode.label === "Tag") {{
          const dayOfYear = Math.min(364, Math.floor(progress * 365));
          const monthIndex = Math.min(11, Math.floor(dayOfYear / 30.5));
          const day = (dayOfYear % 30) + 1;
          return `${{day}}. ${{monthNames[monthIndex]}} ${{year}}`;
        }}
        const hourOfYear = Math.min(8759, Math.floor(progress * 8760));
        const dayOfYear = Math.floor(hourOfYear / 24);
        const hour = hourOfYear % 24;
        const monthIndex = Math.min(11, Math.floor(dayOfYear / 30.5));
        const day = (dayOfYear % 30) + 1;
        return `${{day}}. ${{monthNames[monthIndex]}} ${{year}}, ${{String(hour).padStart(2, "0")}}:00`;
      }}

      function updateRowDetail(activeZoom) {{
        shell.dataset.density = activeZoom < 1 ? "far" : activeZoom > 1.55 ? "near" : "mid";
        cards.forEach((card) => {{
          const importance = Number(card.dataset.importance || 2);
          const weighted = activeZoom * importance;
          let detail = "compact";
          if (weighted >= 4.1) {{
            detail = "full";
          }} else if (weighted >= 2.35) {{
            detail = "summary";
          }}
          card.dataset.detail = detail;
        }});
      }}

      function renderRuler(activeZoom) {{
        const pixelsPerUnit = Math.round(14 + activeZoom * activeZoom * 18);
        const boardHeight = Math.max(boardShell.clientHeight + 240, logicalUnits * pixelsPerUnit);
        board.style.minHeight = `${{boardHeight}}px`;
        const mode = zoomMode(activeZoom);
        currentMode = mode;
        const marks = [];
        for (let unit = 0; unit <= logicalUnits; unit += 1) {{
          const top = unit * pixelsPerUnit;
          if (top > boardHeight) break;
          const isMajor = unit % mode.majorEvery === 0;
          const isMid = !isMajor && unit % mode.midEvery === 0;
          const level = isMajor ? "major" : isMid ? "mid" : "minor";
          const labelValue = Math.round((unit / mode.majorEvery) * mode.step) + 1;
          const label = isMajor ? `<span class="timeline-ruler-label">${{mode.label}} ${{labelValue}}</span>` : "";
          marks.push(`<div class="timeline-ruler-mark" data-level="${{level}}" style="top:${{top}}px">${{label}}</div>`);
        }}
        ruler.innerHTML = marks.join("");
      }}

      function updateViewportContext() {{
        const viewportCenter = scroller.scrollTop + scroller.clientHeight / 2;
        let activeStage = stages[0];
        for (const stage of stages) {{
          if (stage.offsetTop <= viewportCenter) {{
            activeStage = stage;
          }} else {{
            break;
          }}
        }}
        if (activeStage) {{
          const stageKey = activeStage.dataset.stage || "";
          const stageLabel = activeStage.querySelector(".timeline-label strong");
          hudStage.textContent = stageLabel ? stageLabel.textContent : "Timeline";
          const localOffset = Math.max(0, viewportCenter - activeStage.offsetTop);
          const stageSpan = Math.max(1, activeStage.offsetHeight);
          const progress = Math.max(0, Math.min(0.999, localOffset / stageSpan));
          hudFocus.textContent = formatFocusLabel(stageKey, progress, currentMode);
        }}
      }}

      function syncBoardScale(activeZoom) {{
        const axisGap = Math.round(90 + activeZoom * activeZoom * 140);
        const cardWidth = Math.round(240 + activeZoom * activeZoom * 180);
        const anchorHeight = Math.round(38 + activeZoom * activeZoom * 42);
        const dotSize = Math.round(10 + activeZoom * 10);
        const stageSpan = Math.round(220 + activeZoom * activeZoom * 180);
        const cardStackGap = Math.round(110 + activeZoom * activeZoom * 95);
        document.documentElement.style.setProperty("--axis-gap", `${{axisGap}}px`);
        document.documentElement.style.setProperty("--card-width", `${{cardWidth}}px`);
        document.documentElement.style.setProperty("--anchor-height", `${{anchorHeight}}px`);
        document.documentElement.style.setProperty("--dot-size", `${{dotSize}}px`);
        document.documentElement.style.setProperty("--stage-span", `${{stageSpan}}px`);
        document.documentElement.style.setProperty("--card-stack-gap", `${{cardStackGap}}px`);
      }}

      function renderZoom(activeZoom) {{
        syncBoardScale(activeZoom);
        zoomReadout.textContent = `${{Math.round(activeZoom * 100)}}%`;
        updateRowDetail(activeZoom);
        renderRuler(activeZoom);
        updateViewportContext();
      }}

      function applyZoom(nextZoom, anchorYRatio = 0.35) {{
        targetZoom = clamp(nextZoom);
        zoom = targetZoom;
        zoomRange.value = String(targetZoom);
        const previousHeight = scroller.scrollHeight;
        const visibleY = scroller.scrollTop + scroller.clientHeight * anchorYRatio;
        renderZoom(targetZoom);
        requestAnimationFrame(() => {{
          const nextHeight = scroller.scrollHeight;
          if (previousHeight > 0 && nextHeight > 0) {{
            const ratio = visibleY / previousHeight;
            scroller.scrollTop = Math.max(0, ratio * nextHeight - scroller.clientHeight * anchorYRatio);
          }}
          updateViewportContext();
        }});
      }}

      document.getElementById("zoomIn").addEventListener("click", () => applyZoom(targetZoom + 0.12));
      document.getElementById("zoomOut").addEventListener("click", () => applyZoom(targetZoom - 0.12));
      document.getElementById("resetView").addEventListener("click", () => {{
        applyZoom(1);
        scroller.scrollTo({{ left: 0, top: 0, behavior: "smooth" }});
      }});
      document.getElementById("fitView").addEventListener("click", () => {{
        const fit = Math.max(minZoom, Math.min(1.05, (window.innerHeight - 180) / 980));
        applyZoom(fit);
      }});
      zoomRange.addEventListener("input", () => applyZoom(Number(zoomRange.value)));

      boardShell.addEventListener("pointerenter", () => {{
        pointerInsideTimeline = true;
      }});
      boardShell.addEventListener("pointerleave", () => {{
        pointerInsideTimeline = false;
      }});

      const handlePinchWheel = (event) => {{
        if (!(event.ctrlKey || event.metaKey)) return;
        if (!pointerInsideTimeline && !boardShell.contains(event.target)) return;
        event.preventDefault();
        const rect = scroller.getBoundingClientRect();
        const anchorYRatio = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
        const rawDelta = -event.deltaY * 0.0025;
        const delta = Math.max(-0.18, Math.min(0.18, rawDelta));
        applyZoom(targetZoom + delta, anchorYRatio);
      }};

      window.addEventListener("wheel", handlePinchWheel, {{ passive: false, capture: true }});

      let touchCache = new Map();
      function touchDistance() {{
        const touches = Array.from(touchCache.values());
        if (touches.length < 2) return 0;
        const [a, b] = touches;
        const dx = a.clientX - b.clientX;
        const dy = a.clientY - b.clientY;
        return Math.hypot(dx, dy);
      }}

      scroller.addEventListener("pointerdown", (event) => {{
        if (event.pointerType !== "touch") return;
        touchCache.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});
        if (touchCache.size === 2) {{
          pinchActive = true;
          pinchDistance = touchDistance();
          const touches = Array.from(touchCache.values());
          pinchOriginY = (touches[0].clientY + touches[1].clientY) / 2;
        }}
      }});

      scroller.addEventListener("pointermove", (event) => {{
        if (event.pointerType !== "touch") return;
        if (!touchCache.has(event.pointerId)) return;
        touchCache.set(event.pointerId, {{ clientX: event.clientX, clientY: event.clientY }});
        if (!pinchActive || touchCache.size < 2) return;
        event.preventDefault();
        const nextDistance = touchDistance();
        if (!nextDistance || !pinchDistance) return;
        const delta = (nextDistance - pinchDistance) / 240;
        const rect = scroller.getBoundingClientRect();
        const anchorYRatio = Math.max(0, Math.min(1, (pinchOriginY - rect.top) / rect.height));
        applyZoom(targetZoom + delta, anchorYRatio);
        pinchDistance = nextDistance;
      }}, {{ passive: false }});

      const clearPointer = (event) => {{
        touchCache.delete(event.pointerId);
        if (touchCache.size < 2) {{
          pinchActive = false;
          pinchDistance = 0;
        }}
      }};
      scroller.addEventListener("pointerup", clearPointer);
      scroller.addEventListener("pointercancel", clearPointer);

      const blockGesture = (event) => {{
        event.preventDefault();
      }};
      scroller.addEventListener("gesturestart", blockGesture, {{ passive: false }});
      scroller.addEventListener("gesturechange", blockGesture, {{ passive: false }});
      scroller.addEventListener("gestureend", blockGesture, {{ passive: false }});

      scroller.addEventListener("scroll", updateViewportContext, {{ passive: true }});
      window.addEventListener("resize", () => renderZoom(targetZoom));

      renderZoom(targetZoom);
    }})();
  </script>
  <script defer src="/analytics-loader.js"></script>
</body>
</html>
"""


def _expected_output_files(
    story_root: Path, md_to_html: dict[str, Path]
) -> set[Path]:
    expected = {Path("index.html"), *md_to_html.values()}
    expected.update(
        {
            Path("data/lore.json"),
            Path("data/timeline.json"),
            Path("lore-webmcp.js"),
        }
    )
    expected.update(LORE_CSS_FILES.values())
    for src in story_root.rglob("*"):
        if src.is_file() and src.suffix.lower() in STORY_MEDIA_EXTENSIONS:
            expected.add(src.relative_to(story_root))
    return expected


def _prune_empty_dirs(root: Path) -> None:
    for directory in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            continue


def _sync_output_tree(
    output_root: Path, expected_files: set[Path], *, check: bool
) -> bool:
    stale_files: list[Path] = []
    for out_file in output_root.rglob("*"):
        if not out_file.is_file():
            continue
        rel = out_file.relative_to(output_root)
        if out_file.suffix.lower() not in GENERATED_OUTPUT_EXTENSIONS:
            continue
        if rel not in expected_files:
            stale_files.append(out_file)

    if not stale_files:
        return True

    if check:
        for stale in stale_files:
            print("Unerwartete Altdatei:", stale)
        return False

    for stale in stale_files:
        stale.unlink()
    _prune_empty_dirs(output_root)
    print(f"  {len(stale_files)} veraltete Datei(en) aus {output_root} entfernt.")
    return True


def _site_base_url(docs_root: Path) -> str:
    cname_path = docs_root / "CNAME"
    host = "doomsday.radio"
    if cname_path.is_file():
        raw_host = cname_path.read_text(encoding="utf-8").strip()
        if raw_host:
            host = raw_host
    return f"https://{host}"


def _find_site_docs_root(start: Path) -> Path:
    resolved = start.resolve()
    for candidate in [resolved, *resolved.parents]:
        if (candidate / "CNAME").is_file():
            return candidate
    return resolved.parent


def _public_page_url(docs_root: Path, page_path: Path) -> str:
    rel = page_path.relative_to(docs_root).as_posix()
    return f"{_site_base_url(docs_root)}/{rel}"


def _plain_story_text(text: str) -> str:
    """Reduziert Markdown auf agententauglichen, lesbaren Text."""
    text = _strip_housekeeping_lines(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _public_lore_payload(
    *,
    story_root: Path,
    output_root: Path,
    md_to_html: dict[str, Path],
    timeline_events: list[dict[str, object]],
  ) -> tuple[dict[str, object], dict[str, object]]:
    """Erzeugt kleine öffentliche Datenexports für Suche und WebMCP."""
    entries: list[dict[str, object]] = []
    for index, md_path in enumerate(sorted(story_root.rglob("*.md")), start=1):
      rel = md_path.relative_to(story_root)
      rel_key = rel.as_posix()
      text = _strip_housekeeping_lines(md_path.read_text(encoding="utf-8"))
      title = _read_markdown_title(text) or rel.stem.replace("-", " ").title()
      out_rel = md_to_html[rel_key]
      entry: dict[str, object] = {
        "id": f"{index}-{_slugify(rel_key)}",
        "title": title,
        "source": rel_key,
        "href": _relative_href(output_root.parent, output_root / out_rel),
        "category": rel.parts[0] if rel.parts else "Weltkern",
        "subcategory": rel.parts[1] if len(rel.parts) > 1 else None,
        "summary": _extract_overview(text, max_length=320),
        "content": _rewrite_public_glossary_links(_plain_story_text(text)),
      }
      entries.append(entry)
    common = {"version": 1, "source": "content/story"}
    lore_payload = {**common, "entries": entries}
    timeline_payload = {**common, "events": _rewrite_public_text(timeline_events)}
    return lore_payload, timeline_payload


def _write_public_lore_data(
    *,
    output_root: Path,
    payloads: tuple[dict[str, object], dict[str, object]],
    webmcp_adapter: str,
    check: bool,
  ) -> bool:
    data_dir = output_root / "data"
    files = {
      data_dir / "lore.json": payloads[0],
      data_dir / "timeline.json": payloads[1],
      output_root / "lore-webmcp.js": webmcp_adapter,
    }
    for path, content in files.items():
      rendered = json.dumps(content, ensure_ascii=False, indent=2) + "\n" if isinstance(content, dict) else content
      if check:
        if not path.exists() or path.read_text(encoding="utf-8") != rendered:
          print("Abweichung:", path)
          return False
      else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    return True


def _parse_glossary_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    section = "Weitere Begriffe"
    pending_anchor = ""
    current: dict[str, str] | None = None
    for line in text.splitlines():
        anchor_match = re.fullmatch(r'\s*<a id="([^"]+)"></a>\s*', line)
        if anchor_match:
            pending_anchor = anchor_match.group(1)
            continue
        section_match = re.match(r"^##\s+(.+?)\s*$", line)
        if section_match:
            section = section_match.group(1).strip()
            continue
        term_match = re.match(r"^###\s+(.+?)\s*$", line)
        if term_match:
            if current is not None:
                entries.append(current)
            current = {
                "section": section,
                "term": term_match.group(1).strip(),
                "anchor": pending_anchor or _slugify(term_match.group(1)),
                "description": "",
                "detail": "",
            }
            pending_anchor = ""
            continue
        if current is None:
            continue
        detail_match = re.match(r"^Detail:\s*(.+?)\s*$", line)
        if detail_match:
            current["detail"] = detail_match.group(1)
        elif line.strip() and not line.lstrip().startswith("<a "):
            current["description"] = (
                f'{current["description"]} {line.strip()}'
            ).strip()
    if current is not None:
        entries.append(current)
    return entries


def _glossary_template(
    *,
    title: str,
    entries_html: str,
    sections_html: str,
    count: int,
    depth: int,
    page_url: str,
    description: str,
) -> str:
    home_href = "../" * depth + "index.html"
    assets_prefix = "../" * (depth + 1) + "teaser/assets/"
    logo_src = assets_prefix + "ddd_radio_logo.png"
    return f"""<!doctype html>
<html lang="de" data-mode="ddd">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Doomsday Dispatch – Glossar</title>
  <meta name="description" content="{_escape_html(description)}" />
  <link rel="canonical" href="{_escape_html(page_url)}" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{ color: #f3e7c9; background: #0b0f14; font-family: ui-sans-serif, system-ui, sans-serif; line-height: 1.6; }}
    #app {{ min-height: 100vh; display: grid; place-items: start center; padding: clamp(16px, 3vw, 32px); }}
    .panel {{ width: min(1180px, 96vw); overflow: hidden; border: 1px solid rgba(255,230,180,.22); border-radius: 18px; background: rgba(60,48,30,.52); box-shadow: 0 18px 40px rgba(165,90,0,.25); }}
    .content {{ padding: clamp(18px, 3vw, 34px); }}
    .head {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom: 22px; }}
    .brand {{ display:flex; align-items:center; gap:14px; }}
    .logo {{ width:76px; height:76px; object-fit:contain; }}
    h1 {{ margin:0; font-size: clamp(25px, 4vw, 44px); letter-spacing: .02em; text-transform:uppercase; }}
    .lede {{ max-width: 720px; margin: 5px 0 0; color:#d2bf95; }}
    .home {{ color:#f3e7c9; text-decoration:none; border:1px solid rgba(255,230,180,.32); border-radius:999px; padding:8px 12px; font-size:13px; background:rgba(0,0,0,.2); }}
    .toolbar {{ position:sticky; top:12px; z-index:2; display:grid; gap:12px; margin: 0 0 24px; padding:16px; border:1px solid rgba(245,195,90,.35); border-radius:14px; background:rgba(20,14,8,.94); box-shadow:0 12px 30px rgba(0,0,0,.24); }}
    .search-row {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
    .search {{ flex:1 1 320px; min-height:46px; border:1px solid rgba(255,230,180,.3); border-radius:10px; padding:0 14px; color:#f3e7c9; background:#17130f; font:inherit; }}
    .search:focus {{ outline:2px solid #f5c35a; outline-offset:2px; }}
    .result-count {{ color:#d2bf95; font-size:13px; white-space:nowrap; }}
    .letters {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .letter {{ min-width:32px; min-height:30px; border:1px solid rgba(255,230,180,.2); border-radius:7px; color:#f3e7c9; background:rgba(255,230,180,.06); cursor:pointer; }}
    .letter:hover, .letter.active {{ color:#18110a; border-color:#f5c35a; background:#f5c35a; }}
    .section-nav {{ display:flex; gap:8px; flex-wrap:wrap; }}
    .section-nav a {{ color:#f5c35a; font-size:13px; text-decoration:none; }}
    .section-nav a::after {{ content:" ·"; color:#806b43; margin-left:8px; }}
    .section-nav a:last-child::after {{ content:""; }}
    .glossary-section {{ scroll-margin-top:150px; margin: 28px 0 0; }}
    .glossary-section h2 {{ margin:0 0 12px; padding-bottom:8px; border-bottom:1px solid rgba(255,230,180,.2); font-size:14px; letter-spacing:1.3px; text-transform:uppercase; color:#f5c35a; }}
    .terms {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(270px, 1fr)); gap:10px; }}
    .term {{ scroll-margin-top:150px; min-height:170px; padding:16px; border:1px solid rgba(255,230,180,.16); border-radius:10px; background:rgba(0,0,0,.17); }}
    .term[hidden], .glossary-section[hidden] {{ display:none; }}
    .term h3 {{ margin:0 0 8px; font-size:19px; color:#fff0cb; }}
    .term p {{ margin:0 0 14px; color:#d2bf95; font-size:14px; }}
    .term a {{ color:#f5c35a; font-size:13px; }}
    .empty {{ margin:24px 0 0; padding:20px; border:1px dashed rgba(255,230,180,.28); border-radius:10px; color:#d2bf95; }}
    @media (max-width:640px) {{ .toolbar {{ top:4px; }} .term {{ min-height:0; }} .logo {{ width:60px; height:60px; }} }}
  </style>
</head>
<body>
  <div id="app"><div class="panel"><div class="content">
    <div class="head">
      <div class="brand"><img class="logo" src="{_escape_html(logo_src)}" alt="Doomsday Radio" /><div><h1>{_escape_html(title)}</h1><p class="lede">Begriffe, Stimmen, Fraktionen und Systeme der Wasteland. Durchsuchen, filtern, weiterhören.</p></div></div>
      <a class="home" href="{_escape_html(home_href)}">Zur Lore-Startseite</a>
    </div>
    <div class="toolbar" aria-label="Glossarfilter">
      <div class="search-row"><input class="search" id="glossarySearch" type="search" placeholder="Begriff suchen …" aria-label="Glossar durchsuchen" autocomplete="off" /><span class="result-count" id="glossaryCount">{count} Begriffe</span></div>
      <nav class="letters" id="glossaryLetters" aria-label="Alphabetische Navigation"></nav>
      <nav class="section-nav" aria-label="Glossarkategorien">{sections_html}</nav>
    </div>
    <main id="glossaryEntries">{entries_html}</main>
    <p class="empty" id="glossaryEmpty" hidden>Keine passenden Begriffe gefunden. Versuch es mit einem anderen Suchwort.</p>
  </div></div></div>
  <script>
    (() => {{
      const search = document.getElementById("glossarySearch");
      const count = document.getElementById("glossaryCount");
      const empty = document.getElementById("glossaryEmpty");
      const terms = [...document.querySelectorAll(".term")];
      const sections = [...document.querySelectorAll(".glossary-section")];
      const letters = document.getElementById("glossaryLetters");
      let letter = "";
      const available = [...new Set(terms.map((term) => term.dataset.term.slice(0, 1).toLocaleUpperCase("de-DE")))].sort((a,b) => a.localeCompare(b, "de"));
      const all = document.createElement("button"); all.className = "letter active"; all.type = "button"; all.textContent = "Alle"; letters.append(all);
      available.forEach((value) => {{ const button = document.createElement("button"); button.className = "letter"; button.type = "button"; button.textContent = value; button.addEventListener("click", () => {{ letter = value; document.querySelectorAll(".letter").forEach((item) => item.classList.toggle("active", item === button)); filter(); }}); letters.append(button); }});
      all.addEventListener("click", () => {{ letter = ""; document.querySelectorAll(".letter").forEach((item) => item.classList.toggle("active", item === all)); filter(); }});
      function filter() {{ const query = search.value.trim().toLocaleLowerCase("de-DE"); let visible = 0; terms.forEach((term) => {{ const matches = (!query || term.dataset.search.includes(query)) && (!letter || term.dataset.term.slice(0, 1).toLocaleUpperCase("de-DE") === letter); term.hidden = !matches; if (matches) visible += 1; }}); sections.forEach((section) => {{ section.hidden = !section.querySelector(".term:not([hidden])"); }}); count.textContent = `${{visible}} von {count} Begriffen`; empty.hidden = visible !== 0; }}
      search.addEventListener("input", filter);
    }})();
  </script>
  <script src="../lore-webmcp.js"></script>
  <script defer src="/analytics-loader.js"></script>
</body>
</html>
"""

def _detail_template(
    title: str,
    body_html: str,
    *,
    depth: int,
    page_url: str,
    description: str,
) -> str:
    home_href = "../" * depth + "index.html"
    assets_prefix = "../" * (depth + 1) + "teaser/assets/"
    logo_src = assets_prefix + "ddd_radio_logo.png"
    return f"""<!doctype html>
<html lang="de" data-mode="ddd">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Doomsday Dispatch – Lore: {_escape_html(title)}</title>
  <meta name="description" content="{_escape_html(description)}" />
  <link rel="canonical" href="{_escape_html(page_url)}" />
  <meta property="og:type" content="article" />
  <meta property="og:site_name" content="Doomsday Radio" />
  <meta property="og:locale" content="de_DE" />
  <meta property="og:title" content="Doomsday Dispatch – Lore: {_escape_html(title)}" />
  <meta property="og:description" content="{_escape_html(description)}" />
  <meta property="og:url" content="{_escape_html(page_url)}" />
  <meta property="og:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Doomsday Dispatch – Lore: {_escape_html(title)}" />
  <meta name="twitter:description" content="{_escape_html(description)}" />
  <meta name="twitter:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial;
      color: #f3e7c9;
      background: #0b0f14;
      line-height: 1.65;
    }}
    #app {{ min-height: 100vh; display: grid; place-items: start center; padding: clamp(16px, 2vw, 28px); }}
    .panel {{
      width: min(980px, 96vw);
      background: rgba(60, 48, 30, 0.52);
      border: 1px solid rgba(255, 230, 180, .22);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(165, 90, 0,.25), inset 0 0 0 1px rgba(255,255,255,.08);
      overflow: hidden;
    }}
    .content {{ padding: clamp(18px, 3vw, 30px); }}
    .head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom: 14px; }}
    .brand {{ display:flex; align-items:center; gap:12px; }}
    .brand-copy {{ display: grid; gap: 6px; }}
    .logo {{ width: 72px; height: 72px; object-fit: contain; }}
    h1 {{ margin: 0; font-size: clamp(20px, 2.6vw, 32px); text-transform: uppercase; }}
    .home {{
      display:inline-block; color:#f3e7c9; text-decoration:none; border:1px solid rgba(255,230,180,0.32);
      border-radius:999px; padding:8px 12px; font-size:13px; background: rgba(0,0,0,0.2);
    }}
    .lore-body img {{ max-width: 100%; height: auto; border-radius: 10px; border: 1px solid rgba(255,230,180,0.2); }}
    .lore-body .detail-hero {{
      width: 100%;
      max-height: 320px;
      object-fit: cover;
      object-position: center 24%;
      display: block;
      margin-bottom: 16px;
    }}
    .lore-body .detail-slogan {{
      margin: -2px 0 20px;
      padding: 14px 18px;
      border-left: 3px solid rgba(245, 195, 90, 0.95);
      border-radius: 12px;
      background:
        linear-gradient(180deg, rgba(0, 0, 0, 0.34), rgba(20, 14, 8, 0.92)),
        rgba(0, 0, 0, 0.6);
      box-shadow:
        inset 0 0 0 1px rgba(255, 230, 180, 0.08),
        0 10px 24px rgba(0, 0, 0, 0.18);
    }}
    .lore-body .detail-slogan-label {{
      display: block;
      margin-bottom: 6px;
      font-size: 11px;
      letter-spacing: 1.3px;
      text-transform: uppercase;
      color: #cfb06d;
    }}
    .lore-body .detail-slogan-text {{
      margin: 0;
      font-size: clamp(20px, 2.6vw, 30px);
      line-height: 1.15;
      font-weight: 500;
      font-style: normal;
      color: #f3c76a;
      overflow-wrap: anywhere;
    }}
    .lore-body .group-banner {{
      float: right;
      width: min(320px, 40%);
      margin: 0 0 16px 20px;
      object-fit: contain;
      object-position: top right;
      display: block;
      background: rgba(0,0,0,0.18);
    }}
    .lore-body h2 {{ clear: none; }}
    .lore-body h2:nth-of-type(2) {{ clear: both; }}
    @media (max-width: 760px) {{
      .lore-body .group-banner {{
        float: none;
        width: 100%;
        margin: 0 0 16px 0;
      }}
    }}
    .lore-body .detail-gallery {{
      display: grid;
      gap: 18px;
      margin: 24px 0 8px;
      clear: both;
    }}
    .lore-body .detail-gallery img {{
      width: 100%;
      max-width: 100%;
      max-height: 560px;
      object-fit: cover;
      object-position: center 24%;
    }}
    .lore-body a {{ color: #f59e0b; }}
    .lore-body pre {{ overflow-x:auto; background: rgba(0,0,0,0.25); padding:12px; border-radius:10px; }}
    .lore-body code {{ background: rgba(0,0,0,0.2); padding: 2px 6px; border-radius: 4px; }}
  </style>
</head>
<body>
  <div id="app">
    <div class="panel">
      <div class="content">
        <div class="head">
          <div class="brand">
            <img class="logo" src="{_escape_html(logo_src)}" alt="DDD Logo" />
            <div class="brand-copy">
              <h1>{_escape_html(title)}</h1>
            </div>
          </div>
          <a class="home" href="{_escape_html(home_href)}">Zur Lore-Startseite</a>
        </div>
        <article class="lore-body">
{body_html}
        </article>
      </div>
    </div>
  </div>
  <script defer src="/analytics-loader.js"></script>
</body>
</html>
"""


def _overview_template(
    sections_html: str,
    topics_html: str,
    count: int,
  filters_html: str,
    *,
    page_url: str,
    description: str,
) -> str:
    return f"""<!doctype html>
<html lang="de" data-mode="ddd">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <base href="../" />
  <title>Doomsday Dispatch – Lore Startseite</title>
  <meta name="description" content="{_escape_html(description)}" />
  <link rel="canonical" href="{_escape_html(page_url)}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="Doomsday Radio" />
  <meta property="og:locale" content="de_DE" />
  <meta property="og:title" content="Doomsday Dispatch – Lore Startseite" />
  <meta property="og:description" content="{_escape_html(description)}" />
  <meta property="og:url" content="{_escape_html(page_url)}" />
  <meta property="og:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Doomsday Dispatch – Lore Startseite" />
  <meta name="twitter:description" content="{_escape_html(description)}" />
  <meta name="twitter:image" content="https://doomsday.radio/story/teaser/assets/ddd_radio_logo.png" />
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    html, body {{ min-height: 100%; margin: 0; }}
    body {{
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial;
      color: #f3e7c9;
      background: #0b0f14;
      overflow-x: hidden;
    }}
    #app {{ min-height: 100vh; display: grid; place-items: start center; padding: clamp(14px, 2vw, 30px); }}
    .panel {{
      width: min(1160px, 96vw);
      background: rgba(60, 48, 30, 0.52);
      border: 1px solid rgba(255, 230, 180, .22);
      border-radius: 18px;
      box-shadow: 0 18px 40px rgba(165, 90, 0,.25), inset 0 0 0 1px rgba(255,255,255,.08);
      overflow: hidden;
    }}
    .content {{ display: grid; gap: 18px; padding: clamp(18px, 3vw, 30px); }}
    .header {{
      display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap: wrap;
      border: 1px solid rgba(255,230,180,0.24);
      border-radius: 14px;
      padding: 14px;
      background: linear-gradient(180deg, rgba(255,230,180,0.25), rgba(0,0,0,0));
    }}
    .brand {{ display:flex; align-items:center; gap:14px; }}
    .brand-copy {{ display: grid; gap: 6px; }}
    .logo {{ width: 86px; height: 86px; object-fit: contain; }}
    h1 {{ margin: 0; font-size: clamp(22px, 3.2vw, 38px); text-transform: uppercase; letter-spacing: .7px; }}
    .lede {{ margin: 0; color: #d2bf95; line-height: 1.55; }}
    .tag {{ display:inline-block; font-size:12px; border:1px solid rgba(255,230,180,0.3); border-radius:999px; padding:4px 10px; }}
    .knowledge-toolbar {{ position: sticky; top: 10px; z-index: 10; display:grid; gap: 12px; padding: 14px; border: 1px solid rgba(245,195,90,.38); border-radius: 14px; background: rgba(20,14,8,.95); box-shadow: 0 14px 30px rgba(0,0,0,.28); }}
    .knowledge-search-row {{ display:flex; align-items:center; gap: 12px; flex-wrap:wrap; }}
    .knowledge-search {{ flex: 1 1 360px; min-height: 46px; border: 1px solid rgba(255,230,180,.3); border-radius: 10px; padding: 0 14px; color:#f3e7c9; background:#17130f; font: inherit; }}
    .knowledge-search:focus {{ outline: 2px solid #f5c35a; outline-offset: 2px; }}
    .knowledge-count {{ color:#d2bf95; font-size: 13px; white-space:nowrap; }}
    .knowledge-filters {{ display:flex; gap: 7px; flex-wrap:wrap; }}
    .knowledge-filter {{ border:1px solid rgba(255,230,180,.24); border-radius: 999px; padding: 7px 11px; color:#f3e7c9; background:rgba(255,230,180,.06); cursor:pointer; font: inherit; font-size:12px; }}
    .knowledge-filter:hover, .knowledge-filter.active {{ color:#18110a; border-color:#f5c35a; background:#f5c35a; }}
    .knowledge-empty {{ display:none; padding: 24px; border:1px dashed rgba(255,230,180,.3); border-radius: 12px; color:#d2bf95; }}
    .knowledge-empty.visible {{ display:block; }}
    .topic[hidden], .subsection[hidden], .section[hidden] {{ display:none; }}
    .sections {{
      display:grid;
      gap: 16px;
    }}
    .section {{
      border: 1px solid rgba(255,230,180,0.22);
      border-radius: 14px;
      padding: 12px;
      background: rgba(0,0,0,0.14);
    }}
    .section-head {{
      display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap;
      margin: 0;
    }}
    .section h2 {{
      margin: 0;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 1.2px;
    }}
    .section summary {{
      list-style:none;
      cursor:pointer;
      padding: 2px 0;
      border-radius: 8px;
    }}
    .kanon-overview {{ border: 1px solid rgba(255,230,180,.16); border-radius: 10px; background: rgba(0,0,0,.12); }}
    .kanon-overview summary {{ padding: 10px 12px; color: #f5c35a; cursor: pointer; font-size: 12px; }}
    .kanon-overview-body {{ padding: 0 12px 12px; color: #d2bf95; font-size: 13px; line-height: 1.5; }}
    .section summary::-webkit-details-marker {{ display:none; }}
    .section summary::marker {{ display:none; }}
    .section-caret {{
      display:inline-block;
      width: 1.1em;
      color:#d2bf95;
      font-size: 12px;
      transform-origin:center;
      transition: transform .18s ease;
    }}
    .section[open] .section-caret {{ transform: rotate(90deg); }}
    .section-body {{
      margin-top: 10px;
      display:grid;
      gap: 10px;
    }}
    .section-summary {{
      margin: 0 0 10px;
      color: #d2bf95;
      font-size: 13px;
      line-height: 1.5;
    }}
    .section-count {{
      font-size: 11px;
      color: #d2bf95;
      border: 1px solid rgba(255,230,180,0.24);
      border-radius: 999px;
      padding: 2px 8px;
    }}
    .subsections {{
      display:grid;
      gap: 10px;
    }}
    .subsection {{
      border: 1px solid rgba(255,230,180,0.16);
      border-radius: 10px;
      padding: 10px;
      background: rgba(0,0,0,0.10);
    }}
    .subsection summary {{
      list-style:none;
      cursor:pointer;
    }}
    .subsection summary::-webkit-details-marker {{ display:none; }}
    .subsection summary::marker {{ display:none; }}
    .subsection-caret {{
      display:inline-block;
      width: 1.1em;
      color:#d2bf95;
      font-size: 11px;
      transform-origin:center;
      transition: transform .18s ease;
    }}
    .subsection[open] .subsection-caret {{ transform: rotate(90deg); }}
    .subsection h3 {{
      margin: 0 0 10px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: #d2bf95;
    }}
    .subsection-meta {{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      flex-wrap:wrap;
      margin-bottom: 8px;
    }}
    .subsection h3 {{ margin: 0; }}
    .subsection .details-btn {{
      border:1px solid rgba(255,230,180,0.28);
      border-radius:999px;
      background:rgba(0,0,0,0.2);
      color:#f3e7c9;
      font-size:12px;
      padding:5px 10px;
      cursor:pointer;
    }}
    .subsection-summary {{
      margin: 0 0 10px;
      color: #d2bf95;
      font-size: 13px;
      line-height: 1.5;
    }}
    .subsubsections {{
      display:grid;
      gap:10px;
    }}
    .subsubsection {{
      border: 1px solid rgba(255,230,180,0.14);
      border-radius: 10px;
      padding: 10px;
      background: rgba(0,0,0,0.08);
    }}
    .subsubsection h4 {{
      margin: 0 0 8px;
      font-size: 12px;
      letter-spacing: .9px;
      text-transform: uppercase;
      color: #d2bf95;
    }}
    .subsubsection-summary {{
      margin: 0 0 10px;
      color: #d2bf95;
      font-size: 13px;
      line-height: 1.5;
    }}
    .cards {{
      display:grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .topic {{
      border: 1px solid rgba(255,230,180,0.22);
      border-radius: 14px;
      overflow: hidden;
      background: rgba(0,0,0,0.16);
      display:flex;
      flex-direction: column;
      min-height: 100%;
    }}
    .topic img {{
      width: 100%;
      aspect-ratio: 6 / 5;
      object-fit: cover;
      object-position: center 20%;
      border-bottom: 1px solid rgba(255,230,180,0.22);
    }}
    .topic .body {{ padding: 12px; display:flex; flex-direction:column; gap: 8px; flex: 1 1 auto; }}
    .topic h3 {{ margin: 0; font-size: 14px; text-transform: uppercase; letter-spacing: .8px; }}
    .topic .path {{ margin:0; font-size:11px; color:#d2bf95; opacity:.9; }}
    .topic .overview {{ margin:0; color:#f3e7c9; line-height:1.45; font-size:14px; flex: 1 1 auto; }}
    .topic .topic-link {{ color:#f5c35a; font-size:12px; text-decoration:none; }}
    .topic button {{
      margin-top: auto; width: 100%; border: 1px solid rgba(255,230,180,0.3);
      border-radius: 10px; background: rgba(0,0,0,0.22); color:#f3e7c9;
      padding: 10px; cursor: pointer; font-weight: 600;
    }}
    .modal {{
      position: fixed; inset: 0; z-index: 200;
      display: none; align-items: flex-start; justify-content: center;
      background: rgba(5, 6, 8, .78); padding: 12px;
      overflow-y: auto;
    }}
    .modal.open {{ display: flex; }}
    .modal-box {{
      width: min(900px, 100%);
      max-height: calc(100vh - 24px);
      overflow: auto;
      background: rgba(20,16,10,0.95);
      border: 1px solid rgba(255,230,180,0.28);
      border-radius: 14px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.5);
      padding: 16px;
    }}
    .modal-head {{ display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:12px; }}
    .modal-title {{ margin:0; font-size: 17px; text-transform: uppercase; letter-spacing: .8px; }}
    .modal-close {{
      border:1px solid rgba(255,230,180,0.35); background: transparent; color:#f3e7c9;
      border-radius: 999px; padding: 6px 10px; cursor: pointer;
    }}
    .modal-content img {{ max-width: 100%; height: auto; border-radius: 8px; border:1px solid rgba(255,230,180,0.2); }}
    .modal-content .popup-hero {{
      width: 100%;
      max-height: 380px;
      object-fit: cover;
      object-position: center 20%;
      margin-bottom: 10px;
    }}
    .modal-content .detail-slogan {{
      margin: -2px 0 18px;
      padding: 12px 16px;
      border-left: 3px solid rgba(245, 195, 90, 0.95);
      border-radius: 12px;
      background:
        linear-gradient(180deg, rgba(0, 0, 0, 0.34), rgba(20, 14, 8, 0.92)),
        rgba(0, 0, 0, 0.6);
      box-shadow:
        inset 0 0 0 1px rgba(255, 230, 180, 0.08),
        0 10px 24px rgba(0, 0, 0, 0.18);
    }}
    .modal-content .detail-slogan-label {{
      display: block;
      margin-bottom: 6px;
      font-size: 11px;
      letter-spacing: 1.3px;
      text-transform: uppercase;
      color: #cfb06d;
    }}
    .modal-content .detail-slogan-text {{
      margin: 0;
      font-size: clamp(18px, 2.2vw, 26px);
      line-height: 1.15;
      font-weight: 500;
      font-style: normal;
      color: #f3c76a;
      overflow-wrap: anywhere;
    }}
    .modal-content .group-banner {{
      float: right;
      width: min(280px, 40%);
      margin: 0 0 16px 20px;
      object-fit: contain;
      object-position: top right;
      display: block;
      background: rgba(0,0,0,0.18);
    }}
    .modal-content h2 {{ clear: none; }}
    .modal-content h2:nth-of-type(2) {{ clear: both; }}
    .modal-content .popup-gallery {{
      display: grid;
      gap: 12px;
      margin-top: 14px;
      clear: both;
    }}
    .modal-content .popup-gallery img {{
      width: 100%;
      max-height: 360px;
      object-fit: cover;
      object-position: center 24%;
    }}
    .modal-content a {{ color: #f59e0b; }}
    .modal-content pre {{ overflow-x:auto; background: rgba(0,0,0,0.25); padding:10px; border-radius:8px; }}
    .footer {{ font-size: 12px; color: #d2bf95; display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap; }}
    .signature {{
      margin: 4px 0 0;
      text-align: center;
      color: #d2bf95;
      font-size: 13px;
      letter-spacing: .2px;
    }}
    @media (max-width: 980px) {{ .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 640px) {{
      .cards {{ grid-template-columns: 1fr; }}
      .logo {{ width: 66px; height: 66px; }}
      .topic img {{ aspect-ratio: 16 / 10; }}
      .modal {{ padding: 6px; }}
      .modal-box {{ max-height: calc(100vh - 12px); border-radius: 10px; }}
      .modal-content .group-banner {{
        float: none;
        width: 100%;
        margin: 0 0 16px 0;
      }}
      .section {{ padding: 10px; }}
      .section summary {{ padding: 6px 2px; }}
      .section-head {{ gap: 6px; }}
    }}
  </style>
</head>
<body>
  <div id="app">
    <div class="panel">
      <div class="content">
        <div class="header">
          <div class="brand">
            <img class="logo" src="teaser/assets/ddd_radio_logo.png" alt="Doomsday Dispatch Logo" />
            <div class="brand-copy">
              <h1>Doomsday Dispatch // Lore</h1>
              <p class="lede">Alle Themen aus <code>content/story</code> als Kurzübersicht mit Popup-Details.</p>
            </div>
          </div>
          <span class="tag">{count}</span>
        </div>
        <div class="knowledge-toolbar" aria-label="Lore durchsuchen und filtern">
          <div class="knowledge-search-row">
            <input class="knowledge-search" id="loreSearch" type="search" placeholder="Lore durchsuchen: Ort, Gruppe, Figur, Begriff …" aria-label="Lore durchsuchen" autocomplete="off" />
            <span class="knowledge-count" id="loreCount">{count} Einträge</span>
          </div>
          <div class="knowledge-filters" id="loreFilters" aria-label="Lore-Bereiche">{filters_html}</div>
        </div>
        <p class="knowledge-empty" id="loreEmpty">Keine passenden Lore-Einträge gefunden. Versuche einen anderen Suchbegriff oder setze den Bereichsfilter zurück.</p>
        <section class="sections" aria-label="Lore-Themen">
{sections_html}
        </section>
        <div class="footer">
          <span>FREQ: 107.END</span>
          <span>STATUS: LIVE / INTERFERENCE POSSIBLE</span>
          <span>Lore-Archiv</span>
        </div>
        <p class="signature">"Eine Welt, die sich über Radio vermittelt, ordnet und erinnert."</p>
      </div>
    </div>
  </div>

  <div class="modal" id="topicModal" aria-hidden="true">
    <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="topicModalTitle">
      <div class="modal-head">
        <h3 class="modal-title" id="topicModalTitle"></h3>
        <button class="modal-close" id="topicModalClose">Schliessen</button>
      </div>
      <div class="modal-content" id="topicModalContent"></div>
    </div>
  </div>

{topics_html}

  <script>
    (() => {{
      const search = document.getElementById("loreSearch");
      const count = document.getElementById("loreCount");
      const empty = document.getElementById("loreEmpty");
      const topics = [...document.querySelectorAll(".topic[data-search]")];
      const sections = [...document.querySelectorAll(".section")];
      const filters = [...document.querySelectorAll(".knowledge-filter")];
      let activeCategory = "";
      const normalize = (value) => value.toLocaleLowerCase("de-DE").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "");
      function applyFilter() {{
        const query = normalize(search.value.trim());
        let visible = 0;
        topics.forEach((topic) => {{
          const matches = (!query || normalize(topic.dataset.search || "").includes(query)) && (!activeCategory || topic.dataset.category === activeCategory);
          topic.hidden = !matches;
          if (matches) visible += 1;
        }});
        document.querySelectorAll(".subsection").forEach((subsection) => {{ subsection.hidden = !subsection.querySelector(".topic:not([hidden])"); }});
        sections.forEach((section) => {{ section.hidden = !section.querySelector(".topic:not([hidden])"); }});
        count.textContent = `${{visible}} von {count}`;
        empty.classList.toggle("visible", visible === 0);
      }}
      filters.forEach((filter) => filter.addEventListener("click", () => {{
        activeCategory = filter.dataset.category || "";
        filters.forEach((item) => item.classList.toggle("active", item === filter));
        applyFilter();
      }}));
      search.addEventListener("input", applyFilter);
    }})();

    const modal = document.getElementById("topicModal");
    const modalTitle = document.getElementById("topicModalTitle");
    const modalContent = document.getElementById("topicModalContent");
    const closeBtn = document.getElementById("topicModalClose");

    function closeModal() {{
      modal.classList.remove("open");
      modal.setAttribute("aria-hidden", "true");
      modalContent.innerHTML = "";
    }}

    document.querySelectorAll("[data-topic-id]").forEach((btn) => {{
      btn.addEventListener("click", () => {{
        const id = btn.getAttribute("data-topic-id");
        const holder = document.getElementById("topic-content-" + id);
        if (!holder) return;
        modalTitle.textContent = btn.getAttribute("data-topic-title") || "Topic";
        modalContent.innerHTML = holder.innerHTML;
        modal.classList.add("open");
        modal.setAttribute("aria-hidden", "false");
      }});
    }});

    closeBtn.addEventListener("click", closeModal);
    modal.addEventListener("click", (e) => {{ if (e.target === modal) closeModal(); }});
    document.addEventListener("keydown", (e) => {{ if (e.key === "Escape") closeModal(); }});
  </script>
  <script src="https://webmcp.dev/webmcp.js"></script>
  <script src="lore-webmcp.js"></script>
  <script defer src="/analytics-loader.js"></script>
</body>
</html>
"""


def build(story_root: Path, output_root: Path, *, check: bool = False) -> bool:
    all_md = sorted(story_root.rglob("*.md"))
    if not all_md:
        print("Keine .md-Dateien unter", story_root)
        return True

    md_to_html: dict[str, Path] = {}
    for md_path in all_md:
        rel = md_path.relative_to(story_root)
        md_to_html[rel.as_posix()] = _detail_output_rel(rel)

    expected_files = _expected_output_files(story_root, md_to_html)
    if output_root.exists() and not _sync_output_tree(
        output_root, expected_files, check=check
    ):
        return False

    if not check:
        _copy_lore_logo(story_root, output_root)
        copied = _copy_all_story_media(story_root, output_root, check=False)
        if copied:
            print(f"  {copied} Story-Medien nach {output_root} kopiert.")

    md_extensions = ["extra", "nl2br"]
    generated: list[tuple[Path, str]] = []
    css_outputs = {
        variant: output_root / css_rel for variant, css_rel in LORE_CSS_FILES.items()
    }
    css_content_by_variant: dict[str, str] = {}

    cards_by_section: dict[str, dict[str, list[str]]] = {}
    section_subgroups: dict[str, set[str]] = {}
    assets_nested_categories: dict[str, set[str]] = {}
    assets_nested_cards: dict[tuple[str, str], list[str]] = {}
    index_overview_by_dir: dict[tuple[str, ...], str] = {}
    index_title_by_dir: dict[tuple[str, ...], str] = {}
    index_popup_by_dir: dict[tuple[str, ...], tuple[str, str]] = {}
    topic_holders: list[str] = []
    visible_topic_count = 0
    timeline_events: list[dict[str, object]] = []
    site_docs_root = _find_site_docs_root(output_root)
    overview_public_base_dir = output_root.parent

    for idx, md_path in enumerate(all_md, start=1):
        rel = md_path.relative_to(story_root)
        rel_key = rel.as_posix()
        out_rel = md_to_html[rel_key]
        out_path = output_root / out_rel
        depth = len(out_rel.parts) - 1 if out_rel.parts else 0

        text = md_path.read_text(encoding="utf-8")
        text = _strip_housekeeping_lines(text)
        title = _read_markdown_title(text) or rel.stem.replace("-", " ").title()
        description = _extract_overview(text, max_length=180)
        if rel.parts[:2] == ("Kanon", "Timeline") and rel.name.lower() not in {"index.md", "vorlage.md"}:
            timeline_entry = _parse_timeline_entry(
                md_path=md_path,
                text=text,
                story_root=story_root,
                output_root=output_root,
                out_rel=out_rel,
            )
            if timeline_entry is not None:
                timeline_events.append(timeline_entry)

        rewritten_for_page = _rewrite_md_links(
            text,
            current_md_rel=rel,
            story_root=story_root,
            output_root=output_root,
            md_to_html=md_to_html,
            out_path=out_path,
            docs_root=site_docs_root,
        )
        rewritten_for_page = _rewrite_md_images(
            rewritten_for_page,
            current_md_rel=rel,
            story_root=story_root,
            output_root=output_root,
            out_path=out_path,
            docs_root=site_docs_root,
        )
        body_html = markdown.markdown(rewritten_for_page, extensions=md_extensions)
        body_html = _postprocess_html_links(body_html)
        images = _topic_images(md_path, text, story_root)
        hero_html = ""
        if images:
            hero_src = _relative_href(out_path.parent, output_root / images[0])
            hero_html = (
                f'          <p><img class="detail-hero" src="{_escape_html(hero_src)}" '
                f'alt="{_escape_html(title)}" loading="lazy" /></p>\n'
            )
            body_html = _remove_first_image_with_src(body_html, hero_src)
        slogan_html = ""
        if rel.parts and rel.parts[0] == "Gruppen" and rel.name.lower() != "index.md":
            slogan = _extract_slogan(text)
            if slogan:
                slogan_html = (
                    '          <div class="detail-slogan">\n'
                    '            <span class="detail-slogan-label">Leitsatz</span>\n'
                    f'            <p class="detail-slogan-text">"{_escape_html(slogan)}"</p>\n'
                    "          </div>\n"
                )
        banner_html = ""
        banner_image = _group_banner_image(md_path, story_root)
        if banner_image is not None:
            banner_src = _relative_href(out_path.parent, output_root / banner_image)
            banner_html = (
                f'<img class="group-banner" src="{_escape_html(banner_src)}" '
                f'alt="{_escape_html(title)} Banner" loading="lazy" />'
            )
            if "<h2>" in body_html:
                body_html = re.sub(
                    r"(<h2>)",
                    rf"{banner_html}\n\1",
                    body_html,
                    count=1,
                    flags=re.DOTALL,
                )
            else:
                body_html = banner_html + "\n" + body_html
        gallery_html = ""
        gallery_images = _detail_gallery_images(md_path, story_root)
        if gallery_images:
            gallery_items = []
            for gallery_image in gallery_images:
                gallery_src = _relative_href(out_path.parent, output_root / gallery_image)
                gallery_items.append(
                    f'            <img src="{_escape_html(gallery_src)}" alt="{_escape_html(title)} Zusatzbild" loading="lazy" />'
                )
            gallery_html = (
                '          <div class="detail-gallery">\n'
                + "\n".join(gallery_items)
                + "\n          </div>\n"
            )
        body_html_indented = (
            hero_html
            + slogan_html
            + "\n".join("          " + line for line in body_html.splitlines())
            + ("\n" + gallery_html.rstrip() if gallery_html else "")
        )
        if rel.as_posix() == "Kanon/Timeline/index.md":
            detail_html = None
        else:
            detail_html = _detail_template(
                title,
                body_html_indented,
                depth=depth,
                page_url=_public_page_url(site_docs_root, out_path),
                description=description,
            )

        if detail_html is not None:
            css_variant = _css_variant_for_output(out_rel)
            css_target = css_outputs[css_variant]
            css_href = _relative_href(out_path.parent, css_target)
            detail_html, css_text = _externalize_single_style_block(detail_html, css_href)
            if css_text is not None:
                known_css = css_content_by_variant.get(css_variant)
                if known_css is None:
                    css_content_by_variant[css_variant] = css_text
                elif known_css != css_text:
                    raise SystemExit(
                        f"Uneinheitlicher CSS-Block fuer Variante '{css_variant}' erkannt."
                    )
            if check:
                if not out_path.exists():
                    print("Fehlt:", out_path)
                    return False
                if out_path.read_text(encoding="utf-8") != detail_html:
                    print("Abweichung:", out_path)
                    return False
            else:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                generated.append((out_path, detail_html))

        # Startseite-Karte + Popup-Inhalt
        start_page_path = output_root / "index.html"
        popup_md = _rewrite_md_links(
            text,
            current_md_rel=rel,
            story_root=story_root,
            output_root=output_root,
            md_to_html=md_to_html,
            out_path=start_page_path,
            public_base_dir=overview_public_base_dir,
            docs_root=site_docs_root,
        )
        popup_md = _rewrite_md_images(
            popup_md,
            current_md_rel=rel,
            story_root=story_root,
            output_root=output_root,
            out_path=start_page_path,
            public_base_dir=overview_public_base_dir,
            docs_root=site_docs_root,
        )
        popup_html = markdown.markdown(popup_md, extensions=md_extensions)
        popup_html = _postprocess_html_links(popup_html)
        if banner_image is not None:
            popup_banner_src = _relative_href(
                overview_public_base_dir, output_root / banner_image
            )
            popup_banner_html = (
                f'<img class="group-banner" src="{_escape_html(popup_banner_src)}" '
                f'alt="{_escape_html(title)} Banner" loading="lazy" />'
            )
            if "<h2>" in popup_html:
                popup_html = re.sub(
                    r"(<h2>)",
                    rf"{popup_banner_html}\n\1",
                    popup_html,
                    count=1,
                    flags=re.DOTALL,
                )
            else:
                popup_html = popup_banner_html + "\n" + popup_html
        detail_href = _relative_href(overview_public_base_dir, output_root / out_rel)
        popup_html += (
            f'<p><a href="{_escape_html(detail_href)}">Vollansicht als Seite oeffnen</a></p>'
        )

        overview = _extract_overview(text)
        slogan = _extract_slogan(text) if rel.parts and rel.parts[0] == "Gruppen" else None
        topic_id = f"{idx}-{_slugify(rel_key)}"
        is_index_file = rel.name.lower() == "index.md"

        if len(rel.parts) == 1:
            section = "Weltkern"
            subsection = "Alle"
        else:
            section = rel.parts[0]
            subsection = rel.parts[1] if len(rel.parts) > 2 else "Allgemein"

        # Index-Dateien strukturieren Kategorien und liefern Beschreibungen,
        # werden aber nicht als eigene Topic-Karte angezeigt.
        if is_index_file:
            dir_key = tuple(rel.parent.parts)
            if not dir_key:
                # Root-index.md beschreibt die Startkategorie "Weltkern".
                dir_key = ("Weltkern",)
            index_overview_by_dir[dir_key] = _extract_overview(text, max_length=None)
            index_title_by_dir[dir_key] = title
            index_popup_id = f"index-{_slugify('-'.join(dir_key))}"
            index_popup_by_dir[dir_key] = (index_popup_id, title)
            section_subgroups.setdefault(section, set()).add(subsection)
            if section == "Assets" and len(dir_key) >= 3:
                nested_category = dir_key[2]
                assets_nested_categories.setdefault(subsection, set()).add(nested_category)
            topic_holders.append(
                "\n".join(
                    [
                        f'<template id="topic-content-{_escape_html(index_popup_id)}">',
                        popup_html,
                        "</template>",
                    ]
                )
            )
            continue

        image_html = ""
        if images:
            src = _relative_href(overview_public_base_dir, output_root / images[0])
            image_html = (
                f'<img src="{_escape_html(src)}" alt="{_escape_html(title)}" loading="lazy" />'
            )

        card_search = f"{title} {rel_key} {overview}"
        card_html = (
            "\n".join(
                [
              f'          <article class="topic" data-search="{_escape_html(card_search.casefold())}" data-category="{_escape_html(section)}">',
                    f"            {image_html}" if image_html else "",
                    '            <div class="body">',
                    f"              <h3>{_escape_html(title)}</h3>",
                    f'              <p class="path">{_escape_html(rel_key)}</p>',
                    f'              <p class="overview">{_render_inline_markdown(overview)}</p>',
                    f'              <a class="topic-link" href="{_escape_html(detail_href)}">Vollansicht öffnen</a>',
                    (
                        f'              <button type="button" data-topic-id="{_escape_html(topic_id)}" '
                        f'data-topic-title="{_escape_html(title)}">Details...</button>'
                    ),
                    "            </div>",
                    "          </article>",
                ]
            )
        )
        cards_by_section.setdefault(section, {}).setdefault(subsection, []).append(card_html)
        section_subgroups.setdefault(section, set()).add(subsection)
        if section == "Assets" and subsection != "Allgemein":
            nested_category = rel.parts[2] if len(rel.parts) > 3 else "Allgemein"
            assets_nested_categories.setdefault(subsection, set()).add(nested_category)
            assets_nested_cards.setdefault((subsection, nested_category), []).append(card_html)
        visible_topic_count += 1

        popup_hero = ""
        if images:
            hero_src = _relative_href(overview_public_base_dir, output_root / images[0])
            popup_hero = (
                f'<img class="popup-hero" src="{_escape_html(hero_src)}" '
                f'alt="{_escape_html(title)}" loading="lazy" />'
            )
            popup_html = _remove_first_image_with_src(popup_html, hero_src)
        popup_slogan_html = ""
        if slogan and rel.name.lower() != "index.md":
            popup_slogan_html = (
                '<div class="detail-slogan">\n'
                '  <span class="detail-slogan-label">Leitsatz</span>\n'
                f'  <p class="detail-slogan-text">"{_escape_html(slogan)}"</p>\n'
                "</div>"
            )
        popup_gallery_html = ""
        if gallery_images:
            popup_gallery_items = []
            for gallery_image in gallery_images:
                gallery_src = _relative_href(
                    overview_public_base_dir, output_root / gallery_image
                )
                popup_gallery_items.append(
                    f'<img src="{_escape_html(gallery_src)}" alt="{_escape_html(title)} Zusatzbild" loading="lazy" />'
                )
            popup_gallery_html = (
                '<div class="popup-gallery">\n'
                + "\n".join(popup_gallery_items)
                + "\n</div>"
            )
        topic_holders.append(
            "\n".join(
                [
                    f'<template id="topic-content-{_escape_html(topic_id)}">',
                    popup_hero,
                    popup_slogan_html,
                    popup_html,
                    popup_gallery_html,
                    "</template>",
                ]
            )
        )

    ordered_sections = sorted(section_subgroups.keys(), key=_section_sort_key)
    filters_html = (
      '<button type="button" class="knowledge-filter active" data-category="">Alle Bereiche</button>'
      + ''.join(
        f'<button type="button" class="knowledge-filter" data-category="{_escape_html(section_name)}">{_escape_html(index_title_by_dir.get((section_name,), section_name))}</button>'
        for section_name in ordered_sections
      )
    )
    section_blocks: list[str] = []
    for section_idx, section_name in enumerate(ordered_sections):
        subgroups = cards_by_section.get(section_name, {})
        subgroup_names = section_subgroups.get(section_name, set())
        total_cards = sum(len(v) for v in subgroups.values())
        section_summary = _index_summary(index_overview_by_dir, (section_name,))
        section_summary_short = section_summary
        section_summary_full = ""
        if section_name == "Kanon" and section_summary:
          summary_parts = [part for part in section_summary.split("\n") if part.strip()]
          section_summary_short = "\n".join(summary_parts[:3])
          section_summary_full = "\n".join(summary_parts[3:])
        section_title = index_title_by_dir.get((section_name,), section_name)
        section_body: str
        if section_name == "Weltkern":
            cards_html = "\n".join(subgroups.get("Alle", []))
            section_body = "\n".join(
                [
                    '            <div class="cards">',
                    cards_html,
                    "            </div>",
                ]
            )
        else:
            ordered_subgroups = sorted(subgroup_names, key=lambda s: (s != "Allgemein", s.lower()))
            subsection_blocks: list[str] = []
            for subgroup_name in ordered_subgroups:
                cards_html = "\n".join(subgroups.get(subgroup_name, []))
                dir_key = (section_name,) if subgroup_name == "Allgemein" else (section_name, subgroup_name)
                subgroup_title = index_title_by_dir.get(dir_key) or _display_subsection_name(section_name, subgroup_name)
                subgroup_summary = _index_summary(index_overview_by_dir, dir_key)
                if subgroup_name == "Allgemein" and subgroup_summary == section_summary:
                    subgroup_summary = ""
                if not cards_html and not subgroup_summary:
                    continue
                nested_categories = sorted(
                    assets_nested_categories.get(subgroup_name, set()),
                    key=lambda s: (s != "Allgemein", s.lower()),
                )
                subgroup_popup = index_popup_by_dir.get(dir_key)
                subgroup_popup_btn = ""
                if subgroup_popup:
                    popup_id, popup_title = subgroup_popup
                    subgroup_popup_btn = (
                        f'<button type="button" class="details-btn" data-topic-id="{_escape_html(popup_id)}" '
                        f'data-topic-title="{_escape_html(popup_title)}">Details...</button>'
                    )
                # Wenn eine Untergruppe nur via index.md beschrieben ist (z. B. Der Stack/Zeros),
                # rendern wir eine normale Topic-Karte statt nur Textblock.
                if not cards_html and subgroup_popup_btn:
                    cards_html = "\n".join(
                        [
                            '              <article class="topic">',
                            '                <div class="body">',
                            f"                  <h3>{_escape_html(subgroup_title)}</h3>",
                            (
                                f'                  <p class="overview">{_render_inline_markdown(subgroup_summary)}</p>'
                                if subgroup_summary
                                else ""
                            ),
                            (
                                f'                  <button type="button" data-topic-id="{_escape_html(popup_id)}" '
                                f'data-topic-title="{_escape_html(popup_title)}">Details...</button>'
                            ),
                            "                </div>",
                            "              </article>",
                        ]
                    )
                    subgroup_summary = ""
                nested_html = ""
                has_real_nested_categories = any(n != "Allgemein" for n in nested_categories)
                if has_real_nested_categories:
                    nested_blocks: list[str] = []
                    for nested_name in nested_categories:
                        if nested_name == "Allgemein":
                            continue
                        nested_key = (subgroup_name, nested_name)
                        nested_cards_html = "\n".join(assets_nested_cards.get(nested_key, []))
                        nested_dir_key = (
                            (section_name, subgroup_name)
                            if nested_name == "Allgemein"
                            else (section_name, subgroup_name, nested_name)
                        )
                        nested_title = index_title_by_dir.get(nested_dir_key, nested_name)
                        nested_summary = _index_summary(index_overview_by_dir, nested_dir_key)
                        if not nested_cards_html and not nested_summary:
                            continue
                        nested_blocks.append(
                            "\n".join(
                                [
                                    '                <section class="subsubsection">',
                                    f'                  <h4>{_escape_html(nested_title)}</h4>',
                                    (
                                        f'                  <p class="subsubsection-summary">{_render_inline_markdown(nested_summary)}</p>'
                                        if nested_summary
                                        else ""
                                    ),
                                    (
                                        "\n".join(
                                            [
                                                '                  <div class="cards">',
                                                nested_cards_html,
                                                "                  </div>",
                                            ]
                                        )
                                        if nested_cards_html
                                        else ""
                                    ),
                                    "                </section>",
                                ]
                            )
                        )
                    if nested_blocks:
                        nested_html = "\n".join(
                            [
                                '              <div class="subsubsections">',
                                "\n".join(nested_blocks),
                                "              </div>",
                            ]
                        )
                        # Bei vorhandenen Unterkategorien keine doppelte flache Kartenliste rendern.
                        cards_html = ""
                if section_name == "Assets":
                    subsection_blocks.append(
                        "\n".join(
                            [
                                f'            <details class="subsection"{" open" if section_name == "Kanon" and subgroup_name == "Allgemein" else ""}>',
                                "              <summary>",
                                '                <div class="subsection-meta">',
                                f'                  <h3><span class="subsection-caret" aria-hidden="true">▶</span>{_escape_html(subgroup_title)}</h3>',
                                f"                  {subgroup_popup_btn}" if subgroup_popup_btn else "",
                                "                </div>",
                                "              </summary>",
                                (
                                    f'              <p class="subsection-summary">{_render_inline_markdown(subgroup_summary)}</p>'
                                    if subgroup_summary
                                    else ""
                                ),
                                (
                                    "\n".join(
                                        [
                                            '              <div class="cards">',
                                            cards_html,
                                            "              </div>",
                                        ]
                                    )
                                    if cards_html
                                    else ""
                                ),
                                nested_html,
                                "            </details>",
                            ]
                        )
                    )
                else:
                    subsection_blocks.append(
                        "\n".join(
                            [
                                '            <section class="subsection">',
                                '              <div class="subsection-meta">',
                                f'                <h3>{_escape_html(subgroup_title)}</h3>',
                                f"                {subgroup_popup_btn}" if subgroup_popup_btn else "",
                                "              </div>",
                                (
                                    f'              <p class="subsection-summary">{_render_inline_markdown(subgroup_summary)}</p>'
                                    if subgroup_summary
                                    else ""
                                ),
                                (
                                    "\n".join(
                                        [
                                            '              <div class="cards">',
                                            cards_html,
                                            "              </div>",
                                        ]
                                    )
                                    if cards_html
                                    else ""
                                ),
                                nested_html,
                                "            </section>",
                            ]
                        )
                    )
            section_body = "\n".join(
                [
                    '            <div class="subsections">',
                    "\n".join(subsection_blocks),
                    "            </div>",
                ]
            )
        section_blocks.append(
            "\n".join(
                [
                    f'          <details class="section"{" open" if section_idx == 0 or section_name == "Kanon" else ""}>',
                    "            <summary>",
                    '              <div class="section-head">',
                    "                <span class=\"section-caret\" aria-hidden=\"true\">▶</span>",
                    f'                <h2>{_escape_html(section_title)}</h2>',
                    f'                <span class="section-count">{_topic_count_label(total_cards)}</span>',
                    "              </div>",
                    "            </summary>",
                    '            <div class="section-body">',
                    (
                      f'              <p class="section-summary">{_render_inline_markdown(section_summary_short)}</p>'
                      if section_summary_short
                      else ""
                    ),
                    (
                      '              <details class="kanon-overview">'
                      '<summary>Kanon vollständig lesen</summary>'
                      f'<div class="kanon-overview-body">{_render_inline_markdown(section_summary_full)}</div>'
                      '</details>'
                      if section_summary_full
                        else ""
                    ),
                    section_body,
                    "            </div>",
                    "          </details>",
                ]
            )
        )

    start_html = _overview_template(
        sections_html="\n".join(section_blocks),
        topics_html="\n".join(topic_holders),
        count=_topic_count_label(visible_topic_count),
      filters_html=filters_html,
        page_url=_public_page_url(site_docs_root, output_root / "index.html"),
        description="Alle Themen aus content/story als Lore-Uebersicht mit Detailseiten.",
    )
    start_path = output_root / "index.html"
    timeline_index_path = output_root / "Kanon" / "Timeline" / "index.html"
    timeline_index_html = _timeline_template(
        events=sorted(
            timeline_events,
            key=lambda item: (-int(item.get("importance", 2)), str(item.get("title", "")).casefold()),
        ),
        page_url=_public_page_url(site_docs_root, timeline_index_path),
        description="Scrollbare und zoombare Timeline der kanonischen Themenachsen von Doomsday Radio.",
    )
    # Die Overview-Seite nutzt <base href="../"> und rechnet Links relativ zu docs/story.
    # Deshalb muss das CSS-Href ebenfalls von diesem öffentlichen Basispfad aus berechnet werden.
    start_css_href = _relative_href(
        overview_public_base_dir, css_outputs[_css_variant_for_output(Path("index.html"))]
    )
    start_html, start_css_text = _externalize_single_style_block(start_html, start_css_href)
    if start_css_text is not None:
        css_content_by_variant["overview"] = start_css_text

    timeline_css_href = _relative_href(
        timeline_index_path.parent,
        css_outputs[_css_variant_for_output(Path("Kanon") / "Timeline" / "index.html")],
    )
    timeline_index_html, timeline_css_text = _externalize_single_style_block(
        timeline_index_html, timeline_css_href
    )
    if timeline_css_text is not None:
        css_content_by_variant["timeline"] = timeline_css_text

    webmcp_adapter = """(() => {
  const register = () => {
    if (typeof window.WebMCP !== "function") return;
    const mcp = new window.WebMCP();
    const getJson = (path) => fetch(path).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
    const text = (value) => ({ content: [{ type: "text", text: JSON.stringify(value) }] });
    mcp.registerTool("search_lore", "Durchsucht das öffentliche Lore-Kompendium.",
      { query: { type: "string" } }, async ({ query }) => {
        const data = await getJson("data/lore.json");
        const needle = query.toLocaleLowerCase("de-DE");
        return text(data.entries.filter((entry) =>
          `${entry.title} ${entry.summary} ${entry.content}`.toLocaleLowerCase("de-DE").includes(needle)));
      });
    mcp.registerTool("search_timeline", "Durchsucht die öffentliche Doomsday-Timeline.",
      { query: { type: "string" } }, async ({ query }) => {
        const data = await getJson("data/timeline.json");
        const needle = query.toLocaleLowerCase("de-DE");
        return text(data.events.filter((event) => JSON.stringify(event).toLocaleLowerCase("de-DE").includes(needle)));
      });
  };
  if (typeof window.WebMCP === "function") register();
  else window.addEventListener("webmcp-ready", register, { once: true });
})();
"""
    public_payloads = _public_lore_payload(
        story_root=story_root,
        output_root=output_root,
        md_to_html=md_to_html,
        timeline_events=timeline_events,
    )
    if not _write_public_lore_data(
        output_root=output_root,
        payloads=public_payloads,
        webmcp_adapter=webmcp_adapter,
        check=check,
    ):
        return False

    if check:
        if not start_path.exists():
            print("Fehlt:", start_path)
            return False
        if start_path.read_text(encoding="utf-8") != start_html:
            print("Abweichung:", start_path)
            return False
        if not timeline_index_path.exists():
            print("Fehlt:", timeline_index_path)
            return False
        if timeline_index_path.read_text(encoding="utf-8") != timeline_index_html:
            print("Abweichung:", timeline_index_path)
            return False
        for css_variant, css_text in css_content_by_variant.items():
            css_path = css_outputs[css_variant]
            if not css_path.exists():
                print("Fehlt:", css_path)
                return False
            if css_path.read_text(encoding="utf-8") != css_text:
                print("Abweichung:", css_path)
                return False
    else:
        generated.append((start_path, start_html))
        generated.append((timeline_index_path, timeline_index_html))
        for css_variant, css_text in css_content_by_variant.items():
            generated.append((css_outputs[css_variant], css_text))
        for out_path, html in generated:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(html, encoding="utf-8")
        print(f"Lore-HTML generiert: {len(generated)} Dateien nach {output_root}.")

    return True


def main() -> None:
    root = _repo_root()
    story_root = root / "content" / "story"
    output_root = root / "docs" / "story" / "lore"

    ap = argparse.ArgumentParser(
        description="Generiert Lore-HTML aus content/story nach docs/story/lore (teaserartige Startseite + Detailseiten)."
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Prüfen, ob generierter Output aktuell ist (CI); Exit-Code 1 bei Abweichung.",
    )
    ap.add_argument(
        "--story-root",
        type=Path,
        default=story_root,
        help="Quellverzeichnis mit Markdown (default: content/story)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=output_root,
        help="Zielverzeichnis für HTML (default: docs/story/lore)",
    )
    ap.add_argument(
        "--generate-images",
        action="store_true",
        help=(
            "Generiert Bilder vor dem Lore-Build. "
            "Ohne dieses Flag wird nur ein Dry-Check der Bildgenerierung ausgefuehrt."
        ),
    )
    ap.add_argument(
        "--images-overwrite",
        action="store_true",
        help="Nur mit --generate-images: vorhandene Bilder ueberschreiben.",
    )
    ap.add_argument(
        "--images-limit",
        type=int,
        default=None,
        help="Nur mit --generate-images: optional nur die ersten N Eintraege generieren.",
    )
    ap.add_argument(
        "--images-model",
        type=str,
        default=None,
        help="Nur mit --generate-images: Modellname fuer Bildgenerierung.",
    )
    ap.add_argument(
        "--images-size",
        type=str,
        default=None,
        help="Nur mit --generate-images: Bildgroesse, z. B. 1024x1024.",
    )
    args = ap.parse_args()

    if not args.story_root.is_dir():
        raise SystemExit(f"Story-Root existiert nicht: {args.story_root}")

    _run_worldmodel_image_step(
        repo_root=root,
        generate_images=args.generate_images,
        images_overwrite=args.images_overwrite,
        images_limit=args.images_limit,
        images_model=args.images_model,
        images_size=args.images_size,
    )

    ok = build(args.story_root, args.output, check=args.check)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
