from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


METADATA_PATTERN = re.compile(
    r"<!--\s*TTS_(SOURCE|SOURCE_SHA256|APPROVED):\s*(.*?)\s*-->",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(script_text: str) -> dict[str, str]:
    return {
        key.upper(): value.strip()
        for key, value in METADATA_PATTERN.findall(script_text)
    }


def headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in HEADING_PATTERN.finditer(text)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Block TTS production unless its approved source is unchanged."
    )
    parser.add_argument("script", type=Path, help="Eleven-v3 script Markdown file")
    parser.add_argument(
        "--source",
        type=Path,
        help="Approved Romanprosa source Markdown file; overrides TTS_SOURCE metadata.",
    )
    args = parser.parse_args()

    script_path = args.script.resolve()
    if not script_path.is_file():
        print(f"ERROR: TTS script not found: {script_path}")
        return 1

    script_text = script_path.read_text(encoding="utf-8")
    script_metadata = metadata(script_text)
    source_value = args.source or script_metadata.get("SOURCE")
    approved = script_metadata.get("APPROVED", "").lower()
    expected_hash = script_metadata.get("SOURCE_SHA256", "")

    errors: list[str] = []
    if source_value is None:
        errors.append("missing TTS_SOURCE metadata")
    if approved != "yes":
        errors.append("TTS_APPROVED must be yes")
    if not expected_hash:
        errors.append("missing TTS_SOURCE_SHA256 metadata")

    source_path: Path | None = None
    if source_value is not None:
        source_path = Path(source_value)
        if not source_path.is_absolute():
            source_path = (script_path.parent / source_path).resolve()
        if not source_path.is_file():
            errors.append(f"source not found: {source_path}")

    if source_path is not None and source_path.is_file() and expected_hash:
        actual_hash = sha256(source_path)
        if actual_hash != expected_hash:
            errors.append(
                "source hash mismatch: review and approve a fresh TTS script before generation"
            )

        source_headings = headings(source_path.read_text(encoding="utf-8"))
        script_headings = headings(script_text)
        missing_headings = [heading for heading in source_headings if heading not in script_headings]
        if missing_headings:
            errors.append(
                "source headings missing from TTS script: " + "; ".join(missing_headings)
            )

    if errors:
        for error in errors:
            print(f"TTS_NOT_READY: {error}")
        return 1

    print(f"TTS_READY: {script_path}")
    print(f"SOURCE: {source_path}")
    print(f"SOURCE_SHA256: {expected_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
