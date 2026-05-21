#!/usr/bin/env python3
"""Sync ledger fragments and archive the current release.

Stdlib-only — no audiagentic package install required.

Usage:
    python scripts/components/optional/ledger/finalize_ledger.py --release-id v1.2.0

What it does:
  1. Syncs pending fragment JSON files into CURRENT_RELEASE_LEDGER.ndjson
  2. Stamps each event: status=released, release-id=<release_id>
  3. Appends stamped events to LEDGER.ndjson
  4. Clears CURRENT_RELEASE_LEDGER.ndjson
  5. Renders CHANGELOG.md, RELEASE_NOTES.md, VERSION_HISTORY.md
  6. Resets CURRENT_RELEASE.md
  7. Removes processed fragment files
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_ndjson(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _write_ndjson(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in events) + ("\n" if events else ""),
        encoding="utf-8",
    )


def _load_fragments(fragments_dir: Path) -> list[dict]:
    if not fragments_dir.exists():
        return []
    fragments = []
    for p in sorted(fragments_dir.glob("*.json")):
        try:
            fragments.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return fragments


def _merge_by_id(base: list[dict], incoming: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {e["event-id"]: e for e in base}
    for e in incoming:
        by_id.setdefault(e["event-id"], e)
    return [by_id[k] for k in sorted(by_id.keys())]


def _render_change_block(release_id: str, events: list[dict]) -> str:
    lines = [f"## {release_id}"]
    for e in sorted(events, key=lambda x: x.get("event-id", "")):
        summary = e.get("user-summary-candidate") or e.get("technical-summary") or ""
        if summary:
            lines.append(f"- {summary}")
    return "\n".join(lines) + "\n"


def _append_to_doc(path: Path, default_header: str, block: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else default_header + "\n"
    path.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")


def finalize(project_root: Path, release_id: str) -> dict:
    releases = project_root / "docs" / "releases"
    current_path = releases / "CURRENT_RELEASE_LEDGER.ndjson"
    historical_path = releases / "LEDGER.ndjson"
    fragments_dir = project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"

    # 1. Sync fragments into current ledger
    fragments = _load_fragments(fragments_dir)
    current = _load_ndjson(current_path)
    synced = _merge_by_id(current, fragments)
    _write_ndjson(current_path, synced)

    if not synced:
        print("No events in current ledger — nothing to archive.", file=sys.stderr)
        sys.exit(1)

    # 2. Stamp events as released
    released = [{**e, "status": "released", "release-id": release_id} for e in synced]
    released_ids = {e["event-id"] for e in released}

    # 3. Merge into historical ledger (status upgrade always wins)
    historical = _load_ndjson(historical_path)
    by_id = {e["event-id"]: e for e in historical}
    for e in released:
        by_id[e["event-id"]] = e
    merged_historical = [by_id[k] for k in sorted(by_id.keys())]
    _write_ndjson(historical_path, merged_historical)

    # 4. Clear current ledger and reset summary
    _write_ndjson(current_path, [])
    (releases / "CURRENT_RELEASE.md").write_text(
        "# Current Release\n\n## Changes\n\n", encoding="utf-8"
    )

    # 5. Render release docs
    block = _render_change_block(release_id, released)
    _append_to_doc(releases / "CHANGELOG.md", "# Changelog", block)
    (releases / "RELEASE_NOTES.md").write_text(f"# Release Notes\n\n{block}", encoding="utf-8")
    _append_to_doc(releases / "VERSION_HISTORY.md", "# Version History", block)

    # 6. Purge processed fragments
    purged = 0
    for p in fragments_dir.glob("*.json") if fragments_dir.exists() else []:
        try:
            eid = json.loads(p.read_text(encoding="utf-8")).get("event-id", p.stem)
        except (json.JSONDecodeError, OSError):
            eid = p.stem
        if eid in released_ids:
            p.unlink()
            purged += 1

    return {
        "release-id": release_id,
        "archived-events": len(released),
        "purged-fragments": purged,
        "historical-ledger": str(historical_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize audiagentic ledger for a release.")
    parser.add_argument("--release-id", required=True, help="Release identifier (e.g. v1.2.0)")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    args = parser.parse_args()

    result = finalize(Path(args.project_root).resolve(), args.release_id)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
