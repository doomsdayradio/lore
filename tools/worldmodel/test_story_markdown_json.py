"""
Zusammenfassung:
- Unit-Test fuer `story_markdown_json.py`
- prueft den typisierten Export und den Rebuild der normalisierten Markdown-Fassung
- dient als schneller Sicherheitstest fuer Struktur- und Roundtrip-Aenderungen

Nutzungsbeispiele:
- `python -m unittest tools/worldmodel/test_story_markdown_json.py`
- `python -m unittest tools.worldmodel.test_story_markdown_json`
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import unittest
import uuid
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("story_markdown_json.py")
SPEC = importlib.util.spec_from_file_location("story_markdown_json", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module from {MODULE_PATH}")
story_markdown_json = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(story_markdown_json)


class StoryMarkdownJsonTests(unittest.TestCase):
    def test_export_builds_typed_structure_and_rebuilds_normalized_markdown(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        temp_path = tmp_root / f"story-json-test-{uuid.uuid4().hex}"
        temp_path.mkdir(parents=True, exist_ok=False)

        try:
            story_root = temp_path / "content" / "story"
            maker_root = story_root / "Gruppen" / "Maker"
            assets_root = story_root / "Assets" / "Rezepte"

            maker_root.mkdir(parents=True)
            assets_root.mkdir(parents=True)

            (story_root / "index.md").write_text("# Start\n\n## Einstieg\n\nText.\n", encoding="utf-8")
            (story_root / "Gruppen" / "index.md").parent.mkdir(parents=True, exist_ok=True)
            (story_root / "Gruppen" / "index.md").write_text("# Gruppen\n\n## Fraktionen\n\nListe.\n", encoding="utf-8")
            (maker_root / "index.md").write_text("# Maker\n\n## Überblick\n\nListe.\n", encoding="utf-8")
            (maker_root / "funker.md").write_text(
                "# Funker\n\n"
                "Kurzer Introtext.\n\n"
                "## Überblick\n\n"
                "Die Funker halten den Schrott am Singen.\n\n"
                "## Erscheinung & Stil\n\n"
                "Kabel, Rauch und Reststrom.\n",
                encoding="utf-8",
            )
            (story_root / "Assets" / "index.md").parent.mkdir(parents=True, exist_ok=True)
            (story_root / "Assets" / "index.md").write_text("# Assets\n\n## Bereiche\n\nListe.\n", encoding="utf-8")
            (assets_root / "index.md").write_text("# Rezepte\n\n## Einträge\n\nListe.\n", encoding="utf-8")
            (assets_root / "suppe.md").write_text(
                "# Rostsuppe\n\n"
                "## Zutaten\n\n"
                "- Wasser\n"
                "- Salz\n",
                encoding="utf-8",
            )

            payload = story_markdown_json.build_story_payload(story_root)

            self.assertEqual(payload["version"], 2)
            self.assertEqual(payload["statistik"]["markdown_dateien"], 7)

            funker = payload["gruppen"]["linien"]["maker"]["eintraege"][0]
            self.assertEqual(funker["typ"], "gruppen_artikel")
            self.assertEqual(funker["ueberblick"], "Die Funker halten den Schrott am Singen.")
            self.assertEqual(funker["erscheinung_und_stil"], "Kabel, Rauch und Reststrom.")
            self.assertEqual(funker["schwaechen"], "TODO")

            suppe = payload["assets"]["kategorien"]["rezepte"]["eintraege"][0]
            self.assertEqual(suppe["typ"], "asset_rezept_artikel")
            self.assertEqual(suppe["zutaten"], "- Wasser\n- Salz")
            self.assertEqual(suppe["zubereitung"], "TODO")

            export_path = temp_path / "doomsday.json"
            story_markdown_json.write_story_payload(payload, export_path)
            loaded_payload = json.loads(export_path.read_text(encoding="utf-8"))

            rebuild_root = temp_path / "rebuilt"
            story_markdown_json.rebuild_story_from_payload(loaded_payload, rebuild_root)

            rebuilt_funker = (rebuild_root / "Gruppen" / "Maker" / "funker.md").read_text(encoding="utf-8")
            rebuilt_suppe = (rebuild_root / "Assets" / "Rezepte" / "suppe.md").read_text(encoding="utf-8")

            self.assertIn("## Schwächen\n\nTODO", rebuilt_funker)
            self.assertIn("## Zubereitung\n\nTODO", rebuilt_suppe)
            self.assertIn("Kurzer Introtext.", rebuilt_funker)
        finally:
            shutil.rmtree(temp_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
