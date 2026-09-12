"""
Zusammenfassung:
- importiert `worldbundle.json` direkt in die Bunny/libSQL-Datenbank
- kann das `schema_v2.sql` bei Bedarf anlegen oder eine bestehende Welt ersetzen
- ist fuer den produktiven DB-Pfad gedacht, den auch die World-Tools nutzen

Liest:
- `weltdesign/worldmodel/worldbundle.json`
- `weltdesign/database/schema_v2.sql`
- standardmaessig Secrets aus `weltdesign/database/secrets.json`

Schreibt:
- Daten direkt in Bunny/libSQL

Nutzungsbeispiele:
- `python tools/worldmodel/import_worldbundle_bunny.py`
- `python tools/worldmodel/import_worldbundle_bunny.py --wipe-existing-schema`
- `python tools/worldmodel/import_worldbundle_bunny.py --no-ensure-schema`
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

import requests


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


_ENV_SESSION = requests.Session()
_DIRECT_SESSION = requests.Session()
_DIRECT_SESSION.trust_env = False


def _build_pipeline_url(bunny_database_url: str) -> str:
    base = bunny_database_url.replace("libsql://", "https://").rstrip("/")
    return f"{base}/v2/pipeline"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_secrets(path: Path) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pipeline_post(url: str, token: str, sql_statements: list[str], *, timeout_s: int = 60) -> requests.Response:
    payload: dict[str, Any] = {
        "requests": [{"type": "execute", "stmt": {"sql": sql}} for sql in sql_statements]
        + [{"type": "close"}]
    }

    def _do_post(session: requests.Session) -> requests.Response:
        return session.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_s,
        )

    try:
        return _do_post(_ENV_SESSION)
    except requests.exceptions.ProxyError:
        return _do_post(_DIRECT_SESSION)


def _response_has_errors(response: requests.Response) -> bool:
    try:
        data = response.json()
    except ValueError:
        return True

    if "error" in data:
        return True

    for result in data.get("results", []):
        if result.get("type") == "error":
            return True

    return False


def _extract_result_rows(response: requests.Response, request_idx: int = 0) -> list[list[Any]]:
    try:
        data = response.json()
    except ValueError:
        return []

    results = data.get("results", [])
    if not isinstance(results, list) or request_idx >= len(results):
        return []

    result = results[request_idx]
    if not isinstance(result, dict) or result.get("type") != "ok":
        return []

    response_data = result.get("response", {})
    if not isinstance(response_data, dict):
        return []

    result_data = response_data.get("result")
    if not isinstance(result_data, dict):
        return []

    rows = result_data.get("rows")
    if not isinstance(rows, list):
        return []

    out: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        out.append([cell.get("value") if isinstance(cell, dict) else cell for cell in row])
    return out


def _list_existing_tables(url: str, token: str, *, timeout_s: int) -> list[str]:
    resp = _pipeline_post(
        url,
        token,
        ["SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"],
        timeout_s=timeout_s,
    )
    if _response_has_errors(resp):
        print("ERROR while listing existing tables")
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(resp.text)
        sys.exit(1)
    return [str(row[0]) for row in _extract_result_rows(resp, 0) if row]


def _sql_quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return _sql_quote_string(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return _sql_quote_string(str(value))


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    for line in sql_text.splitlines():
        current.append(line)
        candidate = "\n".join(current).strip()
        if candidate and sqlite3.complete_statement(candidate):
            statements.append(candidate)
            current = []
    tail = "\n".join(current).strip()
    if tail:
        statements.append(tail)
    return [statement.strip() for statement in statements if statement.strip()]


def _insert_statement(table: str, row: dict[str, Any]) -> str:
    columns = ", ".join(f"[{column}]" for column in row.keys())
    values = ", ".join(_sql_value(value) for value in row.values())
    return f"INSERT INTO [{table}] ({columns}) VALUES ({values})"


def _prepare_insert_statements(bundle: dict[str, Any], import_run_id: str) -> list[str]:
    world = bundle["world"]
    world_id = world["world_id"]

    statements = [
        _insert_statement(
            "world",
            {
                "world_id": world["world_id"],
                "world_key": world["world_key"],
                "name": world["name"],
                "primary_language": world.get("primary_language", "de-DE"),
                "source_story_root": world.get("source_story_root"),
                "description": world.get("description"),
                "metadata_json": _json_text(world.get("metadata")),
            },
        ),
        _insert_statement(
            "import_run",
            {
                "import_run_id": import_run_id,
                "world_id": world_id,
                "bundle_id": bundle.get("bundle_id"),
                "bundle_schema_version": bundle.get("schema_version"),
                "status": "running",
                "notes_json": _json_text(bundle.get("import_hints")),
            },
        ),
    ]

    statements.extend(
        _insert_statement(
            "bundle_source_input",
            {
                "bundle_source_input_id": str(uuid.uuid4()),
                "import_run_id": import_run_id,
                "source_name": item["source_name"],
                "path": item["path"],
                "sha256": item.get("sha256"),
                "generated_at": item.get("generated_at"),
                "metadata_json": _json_text(item.get("metadata")),
            },
        )
        for item in bundle["source_inputs"]
    )

    statements.extend(
        _insert_statement(
            "source_document",
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
            },
        )
        for item in bundle["documents"]
    )

    statements.extend(
        _insert_statement(
            "source_section",
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
            },
        )
        for item in bundle["sections"]
    )

    statements.extend(
        _insert_statement(
            "media_asset",
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
            },
        )
        for item in bundle["media_assets"]
    )

    statements.extend(
        _insert_statement(
            "source_link",
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
            },
        )
        for item in bundle["links"]
    )

    statements.extend(
        _insert_statement(
            "media_usage",
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
            },
        )
        for item in bundle["media_usages"]
    )

    statements.extend(
        _insert_statement(
            "entity",
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
            },
        )
        for item in bundle["entities"]
    )

    statements.extend(
        _insert_statement(
            "entity_alias",
            {
                "alias_id": item["alias_id"],
                "world_id": world_id,
                "entity_id": item["entity_id"],
                "alias": item["alias"],
                "normalized_alias": item.get("normalized_alias"),
                "alias_type": item.get("alias_type"),
                "source_name": item.get("source_name"),
                "metadata_json": _json_text(item.get("metadata")),
            },
        )
        for item in bundle["entity_aliases"]
    )

    statements.extend(
        _insert_statement(
            "entity_source",
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
            },
        )
        for item in bundle["entity_sources"]
    )

    statements.extend(
        _insert_statement(
            "entity_relation",
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
            },
        )
        for item in bundle["entity_relations"]
    )

    statements.extend(
        _insert_statement(
            "entity_prompt",
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
            },
        )
        for item in bundle["entity_prompts"]
    )

    statements.extend(
        _insert_statement(
            "entity_media",
            {
                "entity_media_id": item["entity_media_id"],
                "world_id": world_id,
                "entity_id": item["entity_id"],
                "media_id": item["media_id"],
                "media_role": item["media_role"],
                "sort_order": item.get("sort_order", 0),
                "source_name": item.get("source_name"),
                "metadata_json": _json_text(item.get("metadata")),
            },
        )
        for item in bundle["entity_media"]
    )

    statements.extend(
        _insert_statement(
            "media_generation",
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
            },
        )
        for item in bundle["media_generations"]
    )

    statements.extend(
        _insert_statement(
            "validation_issue",
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
            },
        )
        for item in bundle["validation_issues"]
    )

    statements.append(
        "UPDATE [import_run] "
        f"SET [status] = 'completed', [finished_at] = CURRENT_TIMESTAMP WHERE [import_run_id] = {_sql_value(import_run_id)}"
    )

    return statements


def _run_sql_chunks(
    url: str,
    token: str,
    chunks: list[list[str]],
    *,
    timeout_s: int,
    label: str,
) -> None:
    for index, chunk in enumerate(chunks, start=1):
        resp = _pipeline_post(url, token, chunk, timeout_s=timeout_s)
        if _response_has_errors(resp):
            print(f"ERROR during {label} chunk {index}/{len(chunks)}")
            try:
                print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
            except ValueError:
                print(resp.text)
            sys.exit(1)


def import_bundle_to_bunny(
    *,
    bundle_path: Path,
    schema_path: Path,
    secrets_path: Path,
    replace_world: bool,
    ensure_schema: bool,
    wipe_existing_schema: bool,
    timeout_s: int,
    schema_chunk_size: int,
    insert_chunk_size: int,
) -> dict[str, int]:
    bundle = _load_json(bundle_path)
    secrets = _load_secrets(secrets_path)
    url = _build_pipeline_url(secrets["BUNNY_DATABASE_URL"])
    auth_token = secrets["BUNNY_DATABASE_AUTH_TOKEN"]
    read_only_token = secrets.get("BUNNY_DATABASE_READ_ONLY_AUTH_TOKEN", auth_token)
    world_id = bundle["world"]["world_id"]
    import_run_id = str(uuid.uuid4())

    if ensure_schema:
        if wipe_existing_schema:
            existing_tables = _list_existing_tables(url, auth_token, timeout_s=timeout_s)
            if existing_tables:
                drop_statements = [
                    f"DROP TABLE IF EXISTS [{table}]"
                    for table in reversed(existing_tables)
                ]
                _run_sql_chunks(
                    url,
                    auth_token,
                    [["PRAGMA foreign_keys = OFF"] + chunk for chunk in _chunked(drop_statements, schema_chunk_size)],
                    timeout_s=timeout_s,
                    label="schema wipe",
                )
        schema_sql = schema_path.read_text(encoding="utf-8")
        schema_statements = _split_sql_statements(schema_sql)
        schema_chunks = _chunked(["PRAGMA foreign_keys = ON"] + schema_statements, schema_chunk_size)
        _run_sql_chunks(url, auth_token, schema_chunks, timeout_s=timeout_s, label="schema apply")

    setup_statements = ["PRAGMA foreign_keys = ON"]
    if replace_world:
        setup_statements.append(f"DELETE FROM [world] WHERE [world_id] = {_sql_value(world_id)}")
    resp = _pipeline_post(url, auth_token, setup_statements, timeout_s=timeout_s)
    if _response_has_errors(resp):
        print("ERROR during setup phase")
        try:
            print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(resp.text)
        sys.exit(1)

    insert_statements = _prepare_insert_statements(bundle, import_run_id)
    insert_chunks = _chunked(insert_statements, insert_chunk_size)
    _run_sql_chunks(
        url,
        auth_token,
        [["PRAGMA foreign_keys = ON"] + chunk for chunk in insert_chunks],
        timeout_s=timeout_s,
        label="insert",
    )

    verify_sql = [
        f"SELECT COUNT(*) FROM [source_document] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [source_section] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [source_link] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [media_asset] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [media_usage] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity_alias] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity_source] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity_relation] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity_prompt] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [entity_media] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [media_generation] WHERE [world_id] = {_sql_value(world_id)}",
        f"SELECT COUNT(*) FROM [validation_issue] WHERE [world_id] = {_sql_value(world_id)}",
    ]
    verify_resp = _pipeline_post(url, read_only_token, verify_sql, timeout_s=timeout_s)
    if _response_has_errors(verify_resp):
        print("ERROR during verify phase")
        try:
            print(json.dumps(verify_resp.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(verify_resp.text)
        sys.exit(1)

    table_names = [
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
    ]
    counts = {
        table: int((_extract_result_rows(verify_resp, index) or [[0]])[0][0])
        for index, table in enumerate(table_names)
    }
    counts["world"] = 1
    return counts


def parse_args() -> argparse.Namespace:
    repo_root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Import worldbundle.json directly into Bunny/libSQL using schema_v2.sql."
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        default=repo_root / "weltdesign" / "worldmodel" / "worldbundle.json",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=repo_root / "weltdesign" / "database" / "schema_v2.sql",
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=repo_root / "weltdesign" / "ddd_world_editor" / "secrets.json",
    )
    parser.add_argument("--no-replace-world", action="store_true")
    parser.add_argument("--no-ensure-schema", action="store_true")
    parser.add_argument("--wipe-existing-schema", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--schema-chunk-size", type=int, default=20)
    parser.add_argument("--insert-chunk-size", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = import_bundle_to_bunny(
        bundle_path=args.bundle,
        schema_path=args.schema,
        secrets_path=args.secrets,
        replace_world=not args.no_replace_world,
        ensure_schema=not args.no_ensure_schema,
        wipe_existing_schema=args.wipe_existing_schema,
        timeout_s=args.timeout,
        schema_chunk_size=args.schema_chunk_size,
        insert_chunk_size=args.insert_chunk_size,
    )
    print(f"Imported into Bunny DB using secrets from {args.secrets}")
    for table, count in counts.items():
        print(f"{table}={count}")


if __name__ == "__main__":
    main()
