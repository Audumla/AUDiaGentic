"""Ledger archive — merge current release into historical ledger and reset current."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, atomic_write_text, load_ndjson

_CURRENT_LEDGER = "CURRENT_RELEASE_LEDGER.ndjson"
_HISTORICAL_LEDGER = "LEDGER.ndjson"
_CURRENT_SUMMARY = "CURRENT_RELEASE.md"
_RELEASES_DIR = ("docs", "releases")


def _purge_fragments(project_root: Path, event_ids: set[str]) -> int:
    fragments_dir = project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"
    if not fragments_dir.exists():
        return 0
    removed = 0
    for path in fragments_dir.glob("*.json"):
        # fragment filename is either <event-id>.json or uses the event-id field
        try:
            import json as _json
            eid = _json.loads(path.read_text(encoding="utf-8")).get("event-id")
        except Exception:
            logger.warning("Failed to parse fragment %s", path, exc_info=True)
            eid = path.stem
        if eid in event_ids:
            path.unlink()
            removed += 1
    return removed


def archive_current_ledger(project_root: Path, release_id: str) -> dict[str, Any]:
    releases = project_root.joinpath(*_RELEASES_DIR)
    current_path = releases / _CURRENT_LEDGER
    historical_path = releases / _HISTORICAL_LEDGER

    events = load_ndjson(current_path)
    if not events:
        raise AudiaGenticError(
            code="CON-ARCHIVE-001",
            kind="release",
            message="no events in current ledger to archive",
            details={"release-id": release_id},
        )

    # Mark all current events as released before archiving
    released_events = [{**e, "status": "released", "release-id": release_id} for e in events]
    released_ids = {e["event-id"] for e in released_events}

    historical = load_ndjson(historical_path)
    by_id = {e["event-id"]: e for e in historical}
    for event in released_events:
        by_id[event["event-id"]] = event  # overwrite — status upgrade always wins
    merged = [by_id[k] for k in sorted(by_id.keys())]

    atomic_write_ndjson(historical_path, merged)
    atomic_write_ndjson(current_path, [])
    atomic_write_text(releases / _CURRENT_SUMMARY, "# Current Release\n\n## Changes\n\n")
    purged = _purge_fragments(project_root, released_ids)

    return {
        "release-id": release_id,
        "archived-events": len(released_events),
        "purged-fragments": purged,
        "historical-ledger": str(historical_path),
        "released-event-ids": sorted(released_ids),
    }
