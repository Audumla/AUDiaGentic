"""Ledger archive — merge current release into historical ledger and reset current."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, atomic_write_text, load_ndjson

_CURRENT_LEDGER = "CURRENT_RELEASE_LEDGER.ndjson"
_HISTORICAL_LEDGER = "LEDGER.ndjson"
_CURRENT_SUMMARY = "CURRENT_RELEASE.md"
_RELEASES_DIR = ("docs", "releases")


def archive_current_ledger(project_root: Path, release_id: str) -> dict[str, Any]:
    releases = project_root.joinpath(*_RELEASES_DIR)
    current_path = releases / _CURRENT_LEDGER
    historical_path = releases / _HISTORICAL_LEDGER

    events = load_ndjson(current_path)
    if not events:
        raise AudiaGenticError(
            code="RLS-BUSINESS-020",
            kind="business-rule",
            message="no events in current ledger to archive",
            details={"release-id": release_id},
        )

    historical = load_ndjson(historical_path)
    by_id = {e["event-id"]: e for e in historical}
    for event in events:
        by_id.setdefault(event["event-id"], event)
    merged = [by_id[k] for k in sorted(by_id.keys())]

    atomic_write_ndjson(historical_path, merged)
    atomic_write_ndjson(current_path, [])
    atomic_write_text(releases / _CURRENT_SUMMARY, "# Current Release\n\n## Changes\n\n")

    return {
        "release-id": release_id,
        "archived-events": len(events),
        "historical-ledger": str(historical_path),
    }
