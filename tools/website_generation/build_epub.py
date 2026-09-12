#!/usr/bin/env python3
"""
Generiert standardkonforme .epub Dateien aus Markdown-Geschichten für das Kraterarchiv.
"""

from __future__ import annotations

import html
import os
import re
import sys
import zipfile
from pathlib import Path


def md_to_xhtml_paragraphs(text: str) -> str:
    """Konvertiert einfachen Markdown-Fließtext in valide XHTML-Absätze."""
    lines = text.strip().split("\n\n")
    html_parts = []
    for block in lines:
        block = block.strip()
        if not block:
            continue
        if block.startswith("# "):
            title = html.escape(block[2:].strip())
            html_parts.append(f"<h1>{title}</h1>")
        elif block.startswith("## "):
            title = html.escape(block[3:].strip())
            html_parts.append(f"<h2>{title}</h2>")
        elif block.startswith("### "):
            title = html.escape(block[4:].strip())
            html_parts.append(f"<h3>{title}</h3>")
        elif block.startswith("> "):
            quote = html.escape(block[2:].strip())
            html_parts.append(f"<blockquote><p>{quote}</p></blockquote>")
        elif block.startswith("```"):
            code = html.escape(block.strip("`").strip())
            html_parts.append(f"<pre><code>{code}</code></pre>")
        else:
            # Inline formatting
            block_html = html.escape(block)
            block_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", block_html)
            block_html = re.sub(r"\*(.*?)\*", r"<em>\1</em>", block_html)
            block_html = re.sub(r"`(.*?)`", r"<code>\1</code>", block_html)
            # Br
            block_html = block_html.replace("\n", "<br/>")
            html_parts.append(f"<p>{block_html}</p>")
    return "\n".join(html_parts)


def parse_markdown_chapters(md_content: str) -> tuple[str, list[dict[str, str]]]:
    """Trennt Titel und Abschnitte/Kapitel aus einer Markdown-Erzählung."""
    book_title = "Unbekanntes Buch"
    m_title = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if m_title:
        book_title = m_title.group(1).strip()

    # Splitte gezielt nach echten Kapitelüberschriften (Abschnitt, Kapitel, Epilog, etc.)
    pattern = r"\n(?=###?\s+(?:Abschnitt|Kapitel|Epilog|[0-9]+))"
    sections = re.split(pattern, md_content)

    chapters = []
    chapter_idx = 1

    for sec in sections:
        sec_str = sec.strip()
        if not sec_str:
            continue

        first_line = sec_str.split("\n")[0].strip()
        is_chap_header = bool(re.match(r"^###?\s+(?:Abschnitt|Kapitel|Epilog|[0-9]+)", first_line))

        if not is_chap_header:
            # Preamble (z. B. Buchtitel, Untertitel). Nur verwenden, wenn das Buch keine separaten Abschnitte besitzt.
            if len(sections) == 1:
                ch_xhtml_body = md_to_xhtml_paragraphs(sec_str)
                chapters.append({
                    "id": f"chap_{chapter_idx}",
                    "filename": f"chapter_{chapter_idx}.xhtml",
                    "title": book_title,
                    "xhtml": ch_xhtml_body
                })
            continue

        ch_title = re.sub(r"^\#\#\#?\s+", "", first_line).strip()
        ch_body_md = re.sub(r"^\#\#\#?\s+.*?\n", "", sec_str, count=1)
        ch_xhtml_body = md_to_xhtml_paragraphs(ch_body_md)

        chapters.append({
            "id": f"chap_{chapter_idx}",
            "filename": f"chapter_{chapter_idx}.xhtml",
            "title": ch_title,
            "xhtml": ch_xhtml_body
        })
        chapter_idx += 1

    return book_title, chapters


def create_epub(md_file_path: Path, output_epub_path: Path, book_id: str, author: str = "Doomsday Radio"):
    """Baut eine valide EPUB3-Datei aus einer Markdown-Datei."""
    md_content = md_file_path.read_text(encoding="utf-8")
    title, chapters = parse_markdown_chapters(md_content)

    output_epub_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_epub_path, "w") as zf:
        # 1. mimetype (MUST be first, uncompressed)
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # 2. META-INF/container.xml
        container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)

        # 3. EPUB/content.opf
        manifest_items = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="css" href="style.css" media-type="text/css"/>'
        ]
        spine_itemrefs = []

        for chap in chapters:
            manifest_items.append(f'<item id="{chap["id"]}" href="{chap["filename"]}" media-type="application/xhtml+xml"/>')
            spine_itemrefs.append(f'<itemref idref="{chap["id"]}"/>')

        manifest_str = "\n    ".join(manifest_items)
        spine_str = "\n    ".join(spine_itemrefs)

        content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="pub-id">urn:uuid:{book_id}</dc:identifier>
    <dc:title>{html.escape(title)}</dc:title>
    <dc:language>de</dc:language>
    <dc:creator>{html.escape(author)}</dc:creator>
    <dc:publisher>Doomsday Radio Kraterarchiv</dc:publisher>
    <meta property="dcterms:modified">2026-09-06T12:00:00Z</meta>
  </metadata>
  <manifest>
    {manifest_str}
  </manifest>
  <spine>
    {spine_str}
  </spine>
</package>"""
        zf.writestr("EPUB/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)

        # 4. EPUB/style.css
        style_css = """body { font-family: sans-serif; line-height: 1.6; padding: 1em; color: #222; }
h1, h2, h3 { color: #111; }
blockquote { border-left: 3px solid #888; margin-left: 0; padding-left: 1em; font-style: italic; }"""
        zf.writestr("EPUB/style.css", style_css, compress_type=zipfile.ZIP_DEFLATED)

        # 5. EPUB/nav.xhtml
        nav_links = []
        for chap in chapters:
            nav_links.append(f'<li><a href="{chap["filename"]}">{html.escape(chap["title"])}</a></li>')
        nav_links_str = "\n        ".join(nav_links)

        nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="de">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Inhaltsverzeichnis</h1>
    <ol>
        {nav_links_str}
    </ol>
  </nav>
</body>
</html>"""
        zf.writestr("EPUB/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)

        # 6. Chapters
        for chap in chapters:
            chap_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="de">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(chap["title"])}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <section>
    <h2>{html.escape(chap["title"])}</h2>
    {chap["xhtml"]}
  </section>
</body>
</html>"""
            zf.writestr(f"EPUB/{chap['filename']}", chap_xhtml, compress_type=zipfile.ZIP_DEFLATED)

    print(f"[OK] EPUB erstellt: {output_epub_path} ({output_epub_path.stat().st_size} Bytes)")


def main():
    root = Path(__file__).resolve().parents[2]

    # Buch 1: Wir berichten, selbst wenn keiner mehr zuhört
    src1 = root / "content" / "story" / "Erzaehlungen" / "Wir-berichten-selbst-wenn-keiner-mehr-zuhoert.md"
    out1 = root / "docs" / "story" / "kraterarchiv" / "books" / "wir-berichten-selbst-wenn-keiner-mehr-zuhoert.epub"
    if src1.exists():
        create_epub(src1, out1, book_id="doomsday-wir-berichten-001")

    # Buch 2: Die Nacht der drei Stimmen
    src2 = root / "content" / "story" / "Kanon" / "Geschichten" / "Die-Nacht-der-drei-Stimmen.md"
    out2 = root / "docs" / "story" / "kraterarchiv" / "books" / "die-nacht-der-drei-stimmen.epub"
    if src2.exists():
        create_epub(src2, out2, book_id="doomsday-drei-stimmen-002")


if __name__ == "__main__":
    main()
