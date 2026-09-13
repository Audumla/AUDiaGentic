"""Ledger archive — merge current release into historical ledger and reset current."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.paths import (
    current_ledger_path,
    historical_ledger_path,
    releases_dir,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, atomic_write_text, load_ndjson

logger = logging.getLogger(__name__)

_CURRENT_LEDGER = "CURRENT_RELEASE_LEDGER.ndjson"
_HISTORICAL_LEDGER = "LEDGER.ndjson"
_CURRENT_SUMMARY = "CURRENT_RELEASE.md"
_RELEASES_DIR = ("docs", "releases")


def _archive_identity(event: dict[str, Any]) -> dict[str, Any]:
    """Return immutable event content, excluding lifecycle annotations."""
    return {
        key: value
        for key, value in event.items()
        if key not in {"status", "release-id", "git-commits"}
    }


def _merge_historical_events(
    historical: list[dict[str, Any]], released: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge by identity without silently overwriting conflicting history."""
    by_id: dict[str, dict[str, Any]] = {}
    for event in [*historical, *released]:
        event_id = event.get("event-id")
        if not isinstance(event_id, str) or not event_id:
            raise AudiaGenticError(
                code="CON-ARCHIVE-002", kind="release",
                message="historical ledger contains an event without a valid event-id",
            )
        existing = by_id.get(event_id)
        if existing is None:
            by_id[event_id] = event
            continue
        if _archive_identity(existing) != _archive_identity(event):
            raise AudiaGenticError(
                code="CON-ARCHIVE-003", kind="release",
                message="historical ledger contains conflicting content for an event-id",
                details={"event-id": event_id},
            )
        existing_release = existing.get("release-id")
        incoming_release = event.get("release-id")
        if existing_release and incoming_release and existing_release != incoming_release:
            raise AudiaGenticError(
                code="CON-ARCHIVE-004", kind="release",
                message="event-id is already assigned to a different release",
                details={"event-id": event_id, "existing-release-id": existing_release,
                         "release-id": incoming_release},
            )
        # A released record is the strongest lifecycle state; otherwise retain
        # the newer annotation supplied by the archive operation.
        if event.get("status") == "released" or existing.get("status") != "released":
            by_id[event_id] = event
    # Preserve historical order so release diffs remain stable; new events are
    # appended in current-ledger order.
    return list(by_id.values())


def _purge_fragments(project_root: Path, event_ids: set[str]) -> int:
    fragments_dir = project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"
    if not fragments_dir.exists():
        return 0
    removed = 0
    for path in fragments_dir.glob("*.json"):
        # fragment filename is either <event-id>.json or uses the event-id field
        try:
            eid = json.loads(path.read_text(encoding="utf-8")).get("event-id")
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse fragment %s", path, exc_info=True)
            eid = path.stem
        if eid in event_ids:
            path.unlink()
            removed += 1
    return removed


def archive_current_ledger(project_root: Path, release_id: str) -> dict[str, Any]:
    # Direct archive callers must observe the same authoritative outbox and
    # fragment-sync boundary as sync/archive-for-release.
    from audiagentic.components.ledger.event_outbox import drain as drain_event_outbox
    from audiagentic.components.ledger.sync import (
        _sync_current_release_ledger_locked,
        ledger_write_lock,
    )

    with ledger_write_lock(project_root) as warning:
        drain_event_outbox(project_root)
        _sync_current_release_ledger_locked(project_root, warning)
        return _archive_current_ledger_locked(project_root, release_id)


def _archive_current_ledger_locked(project_root: Path, release_id: str) -> dict[str, Any]:
    """Archive while the shared ledger write lock is already held."""
    current_path = current_ledger_path(project_root)
    historical_path = historical_ledger_path(project_root)

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
    merged = _merge_historical_events(historical, released_events)

    atomic_write_ndjson(historical_path, merged)
    # Keep the established empty-array sentinel.  It is accepted by the
    # NDJSON loader and avoids needless format churn in release commits.
    atomic_write_text(current_path, "[]\n")
    atomic_write_text(releases_dir(project_root) / "CURRENT_RELEASE.md", "# Current Release\n\n## Changes\n\n")
    purged = _purge_fragments(project_root, released_ids)

    return {
        "release-id": release_id,
        "archived-events": len(released_events),
        "purged-fragments": purged,
        "historical-ledger": str(historical_path),
        "released-event-ids": sorted(released_ids),
    }
