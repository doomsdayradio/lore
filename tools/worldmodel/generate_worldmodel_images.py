"""
Zusammenfassung:
- generiert Bilder aus `image_description`-Feldern in den Worldmodel-JSONs
- speichert die Dateien neben den referenzierten Story-Dateien
- fuehrt ein Manifest aller erzeugten Bilder unter `weltdesign/worldmodel/generated-images/`

Liest:
- `weltdesign/worldmodel/assets.json`
- `weltdesign/worldmodel/groups.json`
- Prompt-Standards unter `tools/worldmodel/*.md`
- `OPENAI_API_KEY` aus der Umgebung

Quellen:
- weltdesign/worldmodel/assets.json
- weltdesign/worldmodel/groups.json

API:
- OpenAI Images API (Model: gpt-image-1.5)
- API-Key über OPENAI_API_KEY

Nutzung:
- Nur prüfen (keine API-Calls):
  `python tools/worldmodel/generate_worldmodel_images.py --dry-run`
- Alle fehlenden Bilder generieren:
  `python tools/worldmodel/generate_worldmodel_images.py`
- Bestehende Bilder überschreiben:
  `python tools/worldmodel/generate_worldmodel_images.py --overwrite`
"""

from __future__ import annotations

import argparse
import binascii
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-image-1.5"
DEFAULT_SIZE = "1024x1024"
DEFAULT_QUALITY = "high"
OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_PROMPT_STANDARD = "tools/worldmodel/standard_bildprompt_fotorealistisch.md"
DEFAULT_PROMPT_STANDARD_FIGURE = "tools/worldmodel/standard_bildprompt_fraktionsfigur.md"
DEFAULT_PROMPT_STANDARD_BANNER = "tools/worldmodel/standard_bildprompt_banner_sigil.md"


@dataclass(frozen=True)
class ImageTask:
    source_type: str  # "assets" | "groups"
    item_id: str
    name: str
    story_file: str
    description: str


@dataclass(frozen=True)
class PromptStandardSet:
    general: str
    figure: str
    banner: str


LEGACY_STORY_FILE_ALIASES: dict[str, str] = {
    "Radiostation/Programm/programm.md": "Radio/programm.md",
    "Radiostation/StackCast.md": "Gruppen/DerStack/StackCast.md",
    "Radiostation/Dispatcher/index.md": "Charaktere/index.md",
    "Radiostation/Radio-Bots/slogans.md": "Radio/Bots/index.md",
    "Charaktere/Magierjaeger.md": "Gruppen/Maker/magier.md",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Datei nicht gefunden: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ungültiges JSON in {path}: {exc}") from None


def _load_prompt_standard(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"Prompt-Standard nicht gefunden: {path}") from None

    match = re.search(r"```text\s*(.*?)```", content, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


def _select_prompt_standard(task: ImageTask, standards: PromptStandardSet) -> tuple[str, str]:
    text = " ".join(
        part.lower()
        for part in (
            task.name,
            task.story_file,
            task.description,
        )
        if part
    )

    banner_tokens = (
        "banner",
        "sigil",
        "warnzeichen",
        "warnsymbol",
        "emblem",
        "zeichen",
        "graffiti",
        "marke",
    )
    if any(token in text for token in banner_tokens):
        return "banner", standards.banner

    if task.source_type == "groups":
        return "figure", standards.figure

    return "general", standards.general


def _load_env_file(path: Path) -> None:
    """
    Minimaler .env-Loader ohne externe Abhängigkeiten.
    Lädt nur KEY=VALUE Zeilen und überschreibt bestehende ENV-Werte nicht.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _collect_tasks(payload: dict[str, Any], source_type: str) -> list[ImageTask]:
    arr = payload.get(source_type, [])
    if not isinstance(arr, list):
        raise SystemExit(f"Ungültige Struktur: Key '{source_type}' muss eine Liste sein.")

    tasks: list[ImageTask] = []
    for raw in arr:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id", "")).strip()
        name = str(raw.get("name", "")).strip()
        story_file = str(raw.get("story_file", "")).strip()
        desc = str(raw.get("image_description", "")).strip()
        if not item_id or not name or not story_file or not desc:
            # Nur mit vollständigem Datensatz generieren.
            continue
        tasks.append(
            ImageTask(
                source_type=source_type,
                item_id=item_id,
                name=name,
                story_file=story_file,
                description=desc,
            )
        )
    return tasks


def _build_prompt(task: ImageTask, prompt_standard: str, standard_kind: str) -> str:
    # Einheitlicher Prompt-Rahmen auf Basis des repoweiten Bildprompt-Standards.
    return (
        "Erstelle ein hochwertiges Lore-Bild fuer Doomsday Radio.\n"
        "Verwende den folgenden repoweiten fotorealistischen Standard als verbindlichen Stil- und Qualitätsrahmen.\n"
        "Ersetze alle Platzhalter vollstaendig und konkret. Wenn die Szenenbeschreibung bereits wie ein fertiger Prompt formuliert ist,\n"
        "dann normalisiere sie in genau diesen Stilrahmen statt sie frei zu ignorieren.\n\n"
        f"Gewaehlter Standardtyp: {standard_kind}\n\n"
        "Standardvorlage:\n"
        f"{prompt_standard}\n\n"
        "Konkrete Motivdaten:\n"
        f"- Thema: {task.name}\n"
        f"- Quelle: {task.source_type}/{task.item_id}\n"
        f"- Bildbeschreibung: {task.description}\n\n"
        "Zusatzregeln:\n"
        "- Keine Schrift, keine Logos, keine Wasserzeichen\n"
        "- Eine klare Hauptszene, kein Collage-Look\n"
        "- Fotorealistisch, glaubwürdig, brutal, postapokalyptisch\n"
        "- Die finale Ausgabe soll ein einzelner fertiger Bildprompt sein, nicht mehrere Varianten"
    )


def _request_image_b64(
    *,
    api_key: str,
    model: str,
    size: str,
    quality: str,
    prompt: str,
    timeout_s: int,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": 1,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_IMAGES_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {err_text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Netzwerkfehler: {exc}") from exc

    parsed = json.loads(body)
    data_arr = parsed.get("data", [])
    if not data_arr:
        raise RuntimeError(f"Unerwartete API-Antwort (kein data): {body[:500]}")
    first = data_arr[0]
    if "b64_json" in first:
        return str(first["b64_json"])
    if "url" in first:
        img_url = str(first["url"])
        try:
            with urllib.request.urlopen(img_url, timeout=timeout_s) as img_resp:
                img_bytes = img_resp.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Bild-Download fehlgeschlagen: {exc}") from exc
        return base64.b64encode(img_bytes).decode("ascii")
    raise RuntimeError(f"Unerwartete API-Antwort (weder b64_json noch url): {body[:500]}")


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing_raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing_raw, dict):
            existing_manifest = dict(existing_raw)
            if existing_manifest == manifest:
                return

    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _story_file_candidates(story_file: str) -> list[str]:
    rel = story_file.replace("\\", "/").strip().lstrip("/")
    if not rel:
        return []

    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = value.replace("\\", "/").strip().lstrip("/")
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    add(rel)
    add(LEGACY_STORY_FILE_ALIASES.get(rel, ""))

    legacy_prefix_map = {
        "Assets/Handelsposten/": "Orte/Handelsposten/",
        "Assets/Zonen/": "Orte/Zonen/",
        "Radiostation/Radio-Bots/": "Radio/Bots/",
        "Radiostation/": "Radio/",
    }
    for old_prefix, new_prefix in legacy_prefix_map.items():
        if rel.startswith(old_prefix):
            add(f"{new_prefix}{rel[len(old_prefix):]}")

    return candidates


def _resolve_story_md_path(repo_root: Path, story_file: str) -> Path:
    story_root = (repo_root / "content" / "story").resolve()

    for rel in _story_file_candidates(story_file):
        candidate = (story_root / rel).resolve()
        if candidate.exists():
            return candidate

    rel = story_file.replace("\\", "/").strip().lstrip("/")
    stem = Path(rel).stem
    if stem and stem.lower() != "index":
        matches = sorted(story_root.glob(f"**/{stem}.md"))
        if len(matches) == 1:
            return matches[0].resolve()

    return (story_root / rel).resolve()


def _find_existing_image_for_md(md_path: Path) -> Path | None:
    stem = md_path.stem
    folder = md_path.parent
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"):
        candidate = folder / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def run(args: argparse.Namespace) -> int:
    root = _repo_root()
    _load_env_file(root / ".env")

    assets_json = (root / args.assets_json).resolve()
    groups_json = (root / args.groups_json).resolve()
    manifest_path = (root / args.manifest).resolve()
    prompt_standard_path = (root / args.prompt_standard).resolve()
    prompt_standard_figure_path = (root / args.prompt_standard_figure).resolve()
    prompt_standard_banner_path = (root / args.prompt_standard_banner).resolve()

    assets_payload = _load_json(assets_json)
    groups_payload = _load_json(groups_json)
    standards = PromptStandardSet(
        general=_load_prompt_standard(prompt_standard_path),
        figure=_load_prompt_standard(prompt_standard_figure_path),
        banner=_load_prompt_standard(prompt_standard_banner_path),
    )

    tasks = _collect_tasks(assets_payload, "assets") + _collect_tasks(groups_payload, "groups")
    if args.limit is not None:
        tasks = tasks[: args.limit]

    if not tasks:
        print("Keine validen image_description-Einträge gefunden.")
        return 0

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print("OPENAI_API_KEY fehlt. Bitte als Umgebungsvariable setzen.", file=sys.stderr)
        return 2

    generated = 0
    skipped = 0
    failed = 0
    invalid = 0
    manifest: dict[str, Any] = {
        "model": args.model,
        "size": args.size,
        "quality": args.quality,
        "items": [],
    }

    for i, task in enumerate(tasks, start=1):
        md_path = _resolve_story_md_path(root, task.story_file)
        out_file = md_path.with_suffix(".jpg")
        if not md_path.exists():
            invalid += 1
            print(
                f"[{i}/{len(tasks)}] WARN  {task.source_type}/{task.item_id}: "
                f"story_file nicht gefunden ({task.story_file})",
                file=sys.stderr,
            )
            manifest["items"].append(
                {
                    "type": task.source_type,
                    "id": task.item_id,
                    "name": task.name,
                    "story_file": task.story_file,
                    "file": str(out_file.relative_to(root)).replace("\\", "/"),
                    "status": "skipped_invalid_story_file",
                    "error": f"story_file not found: {task.story_file}",
                }
            )
            continue
        existing_img = _find_existing_image_for_md(md_path)
        standard_kind, prompt_standard = _select_prompt_standard(task, standards)
        prompt = _build_prompt(task, prompt_standard, standard_kind)

        if existing_img is not None and not args.overwrite:
            print(
                f"[{i}/{len(tasks)}] SKIP  {task.source_type}/{task.item_id} "
                f"(Bild existiert: {existing_img.name})"
            )
            skipped += 1
            manifest["items"].append(
                {
                    "type": task.source_type,
                    "id": task.item_id,
                    "name": task.name,
                    "story_file": task.story_file,
                    "file": str(existing_img.relative_to(root)).replace("\\", "/"),
                    "status": "skipped_exists",
                }
            )
            continue

        if args.dry_run:
            print(f"[{i}/{len(tasks)}] DRY   {task.source_type}/{task.item_id}")
            manifest["items"].append(
                {
                    "type": task.source_type,
                    "id": task.item_id,
                    "name": task.name,
                    "story_file": task.story_file,
                    "file": str(out_file.relative_to(root)).replace("\\", "/"),
                    "status": "dry_run",
                    "prompt_standard": standard_kind,
                    "prompt_preview": prompt[:220],
                }
            )
            continue

        try:
            out_file.parent.mkdir(parents=True, exist_ok=True)
            b64 = _request_image_b64(
                api_key=api_key,
                model=args.model,
                size=args.size,
                quality=args.quality,
                prompt=prompt,
                timeout_s=args.timeout,
            )
            out_file.write_bytes(base64.b64decode(b64))
            generated += 1
            print(f"[{i}/{len(tasks)}] OK    {task.source_type}/{task.item_id} -> {out_file}")
            manifest["items"].append(
                {
                    "type": task.source_type,
                    "id": task.item_id,
                    "name": task.name,
                    "story_file": task.story_file,
                    "file": str(out_file.relative_to(root)).replace("\\", "/"),
                    "status": "generated",
                }
            )
        except (RuntimeError, ValueError, OSError, binascii.Error) as exc:
            failed += 1
            print(f"[{i}/{len(tasks)}] FAIL  {task.source_type}/{task.item_id}: {exc}", file=sys.stderr)
            manifest["items"].append(
                {
                    "type": task.source_type,
                    "id": task.item_id,
                    "name": task.name,
                    "story_file": task.story_file,
                    "file": str(out_file.relative_to(root)).replace("\\", "/"),
                    "status": "failed",
                    "error": str(exc),
                }
            )

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    _write_manifest(manifest_path, manifest)
    print(
        f"Fertig. generated={generated}, skipped={skipped}, invalid={invalid}, failed={failed}, "
        f"manifest={manifest_path}"
    )
    return 1 if failed > 0 else 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description=(
            "Generiert Bilder aus image_description in assets.json und groups.json "
            f"(Default-Model: {DEFAULT_MODEL})."
        )
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
        "--manifest",
        default="weltdesign/worldmodel/generated-images/manifest.json",
        help="Pfad zur Manifest-Datei relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--prompt-standard",
        default=DEFAULT_PROMPT_STANDARD,
        help="Pfad zur allgemeinen Standard-Bildprompt-Datei relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--prompt-standard-figure",
        default=DEFAULT_PROMPT_STANDARD_FIGURE,
        help="Pfad zur Fraktionsfiguren-Standarddatei relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--prompt-standard-banner",
        default=DEFAULT_PROMPT_STANDARD_BANNER,
        help="Pfad zur Banner-/Sigil-Standarddatei relativ zum Repo-Root.",
    )
    ap.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI Bildmodell (Default: {DEFAULT_MODEL}).",
    )
    ap.add_argument(
        "--size",
        default=DEFAULT_SIZE,
        help=f"Bildgröße, z. B. {DEFAULT_SIZE}.",
    )
    ap.add_argument(
        "--quality",
        default=DEFAULT_QUALITY,
        help=f"Qualität für GPT Image (Default: {DEFAULT_QUALITY}).",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Bereits existierende Bilder überschreiben.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional nur die ersten N Einträge verarbeiten.",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="HTTP Timeout in Sekunden (Default: 120).",
    )
    ap.add_argument(
        "--sleep-ms",
        type=int,
        default=250,
        help="Pause zwischen Requests in Millisekunden (Default: 250).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Keine API-Calls, nur Aufgabenliste + Manifest schreiben.",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
