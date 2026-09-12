"""
Zusammenfassung:
- importiert `worldbundle.json` in eine lokale SQLite-/libSQL-kompatible Datenbank
- legt dabei die Datensaetze passend zu `schema_v2.sql` an
- eignet sich fuer lokale Tests vor dem Import nach Bunny

Liest:
- `weltdesign/worldmodel/worldbundle.json`
- `weltdesign/database/schema_v2.sql`

Schreibt:
- standardmaessig `.tmp/doomsday_world_v2.sqlite`

Nutzungsbeispiele:
- `python tools/worldmodel/import_worldbundle_sqlite.py`
- `python tools/worldmodel/import_worldbundle_sqlite.py --db .tmp/doomsday_world_v2.sqlite`
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _insert_many(
    conn: sqlite3.Connection,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO [{table}] ({', '.join(f'[{col}]' for col in columns)}) VALUES ({placeholders})"
    values = [tuple(row.get(column) for column in columns) for row in rows]
    conn.executemany(sql, values)


def _prepare_world_row(bundle: dict[str, Any]) -> dict[str, Any]:
    world = bundle["world"]
    return {
        "world_id": world["world_id"],
        "world_key": world["world_key"],
        "name": world["name"],
        "primary_language": world.get("primary_language", "de-DE"),
        "source_story_root": world.get("source_story_root"),
        "description": world.get("description"),
        "metadata_json": _json_text(world.get("metadata")),
    }


def _rows_with_world(bundle: dict[str, Any], items: list[dict[str, Any]], converters: dict[str, str]) -> list[dict[str, Any]]:
    world_id = bundle["world"]["world_id"]
    out: list[dict[str, Any]] = []
    for item in items:
        row = {"world_id": world_id}
        for key, value in item.items():
            row[converters.get(key, key)] = _json_text(value) if key == "metadata" else value
        out.append(row)
    return out


def import_bundle(bundle_path: Path, schema_path: Path, db_path: Path, *, replace_world: bool = True) -> dict[str, int]:
    bundle = _load_json(bundle_path)
    world_id = bundle["world"]["world_id"]
    import_run_id = str(uuid.uuid4())

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        with conn:
            if replace_world:
                conn.execute("DELETE FROM [world] WHERE [world_id] = ?", (world_id,))

            world_row = _prepare_world_row(bundle)
            _insert_many(
                conn,
                "world",
                ["world_id", "world_key", "name", "primary_language", "source_story_root", "description", "metadata_json"],
                [world_row],
            )
            _insert_many(
                conn,
                "import_run",
                ["import_run_id", "world_id", "bundle_id", "bundle_schema_version", "status", "notes_json"],
                [
                    {
                        "import_run_id": import_run_id,
                        "world_id": world_id,
                        "bundle_id": bundle.get("bundle_id"),
                        "bundle_schema_version": bundle.get("schema_version"),
                        "status": "running",
                        "notes_json": _json_text(bundle.get("import_hints")),
                    }
                ],
            )

            _insert_many(
                conn,
                "bundle_source_input",
                ["bundle_source_input_id", "import_run_id", "source_name", "path", "sha256", "generated_at", "metadata_json"],
                [
                    {
                        "bundle_source_input_id": str(uuid.uuid4()),
                        "import_run_id": import_run_id,
                        "source_name": item["source_name"],
                        "path": item["path"],
                        "sha256": item.get("sha256"),
                        "generated_at": item.get("generated_at"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["source_inputs"]
                ],
            )

            _insert_many(
                conn,
                "source_document",
                [
                    "document_id",
                    "world_id",
                    "path",
                    "file_name",
                    "stem",
                    "title",
                    "document_kind",
                    "directory_path",
                    "story_file",
                    "path_parts_json",
                    "sha256",
                    "byte_length",
                    "line_count",
                    "primary_media_asset_id",
                    "raw_markdown",
                    "metadata_json",
                ],
                [
                    {
                        "document_id": item["document_id"],
                        "world_id": world_id,
                        "path": item["path"],
                        "file_name": item["file_name"],
                        "stem": item["stem"],
                        "title": item.get("title"),
                        "document_kind": item.get("document_kind"),
                        "directory_path": item.get("directory"),
                        "story_file": item.get("story_file"),
                        "path_parts_json": _json_text(item.get("path_parts")),
                        "sha256": item["sha256"],
                        "byte_length": item.get("byte_length"),
                        "line_count": item.get("line_count"),
                        "primary_media_asset_id": item.get("primary_media_asset_id"),
                        "raw_markdown": item["raw_markdown"],
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["documents"]
                ],
            )

            _insert_many(
                conn,
                "source_section",
                [
                    "section_id",
                    "world_id",
                    "document_id",
                    "ordinal",
                    "heading",
                    "level",
                    "anchor_slug",
                    "start_line",
                    "end_line",
                    "markdown",
                    "plaintext",
                    "metadata_json",
                ],
                [
                    {
                        "section_id": item["section_id"],
                        "world_id": world_id,
                        "document_id": item["document_id"],
                        "ordinal": item["ordinal"],
                        "heading": item.get("heading"),
                        "level": item.get("level"),
                        "anchor_slug": item.get("anchor_slug"),
                        "start_line": item.get("start_line"),
                        "end_line": item.get("end_line"),
                        "markdown": item["markdown"],
                        "plaintext": item.get("plaintext"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["sections"]
                ],
            )

            _insert_many(
                conn,
                "media_asset",
                ["media_id", "world_id", "path", "story_file", "file_name", "extension", "mime_type", "media_kind", "sha256", "byte_length", "metadata_json"],
                [
                    {
                        "media_id": item["media_id"],
                        "world_id": world_id,
                        "path": item["path"],
                        "story_file": item.get("story_file"),
                        "file_name": item["file_name"],
                        "extension": item.get("extension"),
                        "mime_type": item.get("mime_type"),
                        "media_kind": item["media_kind"],
                        "sha256": item.get("sha256"),
                        "byte_length": item.get("byte_length"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["media_assets"]
                ],
            )

            _insert_many(
                conn,
                "source_link",
                ["link_id", "world_id", "document_id", "section_id", "line_number", "link_kind", "label", "alt_text", "raw_target", "target_document_id", "target_media_id", "target_url", "target_fragment", "resolved_path", "resolved_kind", "metadata_json"],
                [
                    {
                        "link_id": item["link_id"],
                        "world_id": world_id,
                        "document_id": item["document_id"],
                        "section_id": item.get("section_id"),
                        "line_number": item.get("line_number"),
                        "link_kind": item["link_kind"],
                        "label": item.get("label"),
                        "alt_text": item.get("alt_text"),
                        "raw_target": item["raw_target"],
                        "target_document_id": item.get("target_document_id"),
                        "target_media_id": item.get("target_media_id"),
                        "target_url": item.get("target_url"),
                        "target_fragment": item.get("target_fragment"),
                        "resolved_path": item.get("resolved_path"),
                        "resolved_kind": item.get("resolved_kind"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["links"]
                ],
            )

            _insert_many(
                conn,
                "media_usage",
                ["usage_id", "world_id", "document_id", "media_id", "link_id", "usage_kind", "ordinal", "line_number", "alt_text", "caption", "metadata_json"],
                [
                    {
                        "usage_id": item["usage_id"],
                        "world_id": world_id,
                        "document_id": item["document_id"],
                        "media_id": item["media_id"],
                        "link_id": item.get("link_id"),
                        "usage_kind": item["usage_kind"],
                        "ordinal": item.get("ordinal", 0),
                        "line_number": item.get("line_number"),
                        "alt_text": item.get("alt_text"),
                        "caption": item.get("caption"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["media_usages"]
                ],
            )

            _insert_many(
                conn,
                "entity",
                ["entity_id", "world_id", "entity_key", "entity_type", "canonical_name", "display_name", "status", "summary", "description_markdown", "origin", "metadata_json"],
                [
                    {
                        "entity_id": item["entity_id"],
                        "world_id": world_id,
                        "entity_key": item["entity_key"],
                        "entity_type": item["entity_type"],
                        "canonical_name": item["canonical_name"],
                        "display_name": item.get("display_name"),
                        "status": item.get("status", "active"),
                        "summary": item.get("summary"),
                        "description_markdown": item.get("description_markdown"),
                        "origin": item.get("origin"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entities"]
                ],
            )

            _insert_many(
                conn,
                "entity_alias",
                ["alias_id", "world_id", "entity_id", "alias", "normalized_alias", "alias_type", "source_name", "metadata_json"],
                [
                    {
                        "alias_id": item["alias_id"],
                        "world_id": world_id,
                        "entity_id": item["entity_id"],
                        "alias": item["alias"],
                        "normalized_alias": item.get("normalized_alias"),
                        "alias_type": item.get("alias_type"),
                        "source_name": item.get("source_name"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entity_aliases"]
                ],
            )

            _insert_many(
                conn,
                "entity_source",
                ["entity_source_id", "world_id", "entity_id", "document_id", "source_name", "source_record_key", "story_file", "is_primary", "confidence", "metadata_json"],
                [
                    {
                        "entity_source_id": item["entity_source_id"],
                        "world_id": world_id,
                        "entity_id": item["entity_id"],
                        "document_id": item.get("document_id"),
                        "source_name": item["source_name"],
                        "source_record_key": item.get("source_record_key"),
                        "story_file": item.get("story_file"),
                        "is_primary": 1 if item.get("is_primary") else 0,
                        "confidence": item.get("confidence"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entity_sources"]
                ],
            )

            _insert_many(
                conn,
                "entity_relation",
                ["relation_id", "world_id", "from_entity_id", "to_entity_id", "relation_type", "directionality", "confidence", "evidence_document_id", "evidence_section_id", "evidence_note", "metadata_json"],
                [
                    {
                        "relation_id": item["relation_id"],
                        "world_id": world_id,
                        "from_entity_id": item["from_entity_id"],
                        "to_entity_id": item["to_entity_id"],
                        "relation_type": item["relation_type"],
                        "directionality": item.get("directionality", "directed"),
                        "confidence": item.get("confidence"),
                        "evidence_document_id": item.get("evidence_document_id"),
                        "evidence_section_id": item.get("evidence_section_id"),
                        "evidence_note": item.get("evidence_note"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entity_relations"]
                ],
            )

            _insert_many(
                conn,
                "entity_prompt",
                ["prompt_id", "world_id", "entity_id", "prompt_type", "prompt_text", "source_name", "source_record_key", "story_file", "is_current", "metadata_json"],
                [
                    {
                        "prompt_id": item["prompt_id"],
                        "world_id": world_id,
                        "entity_id": item["entity_id"],
                        "prompt_type": item["prompt_type"],
                        "prompt_text": item["prompt_text"],
                        "source_name": item.get("source_name"),
                        "source_record_key": item.get("source_record_key"),
                        "story_file": item.get("story_file"),
                        "is_current": 1 if item.get("is_current", True) else 0,
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entity_prompts"]
                ],
            )

            _insert_many(
                conn,
                "entity_media",
                ["entity_media_id", "world_id", "entity_id", "media_id", "media_role", "sort_order", "source_name", "metadata_json"],
                [
                    {
                        "entity_media_id": item["entity_media_id"],
                        "world_id": world_id,
                        "entity_id": item["entity_id"],
                        "media_id": item["media_id"],
                        "media_role": item["media_role"],
                        "sort_order": item.get("sort_order", 0),
                        "source_name": item.get("source_name"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["entity_media"]
                ],
            )

            _insert_many(
                conn,
                "media_generation",
                ["generation_id", "world_id", "entity_id", "media_id", "source_name", "source_record_key", "model", "size", "quality", "status", "output_path", "story_file", "metadata_json"],
                [
                    {
                        "generation_id": item["generation_id"],
                        "world_id": world_id,
                        "entity_id": item.get("entity_id"),
                        "media_id": item.get("media_id"),
                        "source_name": item["source_name"],
                        "source_record_key": item.get("source_record_key"),
                        "model": item.get("model"),
                        "size": item.get("size"),
                        "quality": item.get("quality"),
                        "status": item["status"],
                        "output_path": item.get("output_path"),
                        "story_file": item.get("story_file"),
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["media_generations"]
                ],
            )

            _insert_many(
                conn,
                "validation_issue",
                ["issue_id", "world_id", "import_run_id", "document_id", "section_id", "entity_id", "media_id", "issue_type", "severity", "message", "metadata_json"],
                [
                    {
                        "issue_id": item["issue_id"],
                        "world_id": world_id,
                        "import_run_id": import_run_id,
                        "document_id": item.get("document_id"),
                        "section_id": item.get("section_id"),
                        "entity_id": item.get("entity_id"),
                        "media_id": item.get("media_id"),
                        "issue_type": item["issue_type"],
                        "severity": item["severity"],
                        "message": item["message"],
                        "metadata_json": _json_text(item.get("metadata")),
                    }
                    for item in bundle["validation_issues"]
                ],
            )

            conn.execute(
                "UPDATE [import_run] SET [status] = 'completed', [finished_at] = CURRENT_TIMESTAMP WHERE [import_run_id] = ?",
                (import_run_id,),
            )

        counts = {}
        for table in [
            "source_document",
            "source_section",
            "source_link",
            "media_asset",
            "media_usage",
            "entity",
            "entity_alias",
            "entity_source",
            "entity_relation",
            "entity_prompt",
            "entity_media",
            "media_generation",
            "validation_issue",
        ]:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM [{table}] WHERE [world_id] = ?", (world_id,)).fetchone()[0]
        counts["world"] = 1
        return counts
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(description="Import worldbundle.json into a local SQLite database using schema_v2.sql.")
    parser.add_argument("--bundle", type=Path, default=repo_root / "weltdesign" / "worldmodel" / "worldbundle.json")
    parser.add_argument("--schema", type=Path, default=repo_root / "weltdesign" / "database" / "schema_v2.sql")
    parser.add_argument("--db", type=Path, default=repo_root / ".tmp" / "doomsday_world_v2.sqlite")
    parser.add_argument("--no-replace-world", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = import_bundle(
        bundle_path=args.bundle,
        schema_path=args.schema,
        db_path=args.db,
        replace_world=not args.no_replace_world,
    )
    print(f"Imported into {args.db}")
    for table, count in counts.items():
        print(f"{table}={count}")


if __name__ == "__main__":
    main()
