"""Ledger archive — merge current release into historical ledger and reset current."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.current_events import event_identity, pending_events
from audiagentic.components.ledger.paths import (
    current_release_md_path,
    historical_ledger_path,
)
from audiagentic.components.ledger.validation import (
    load_persisted_events,
    validate_persisted_event,
    validate_release_id,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, atomic_write_text

logger = logging.getLogger(__name__)



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
        if event_identity(existing) != event_identity(event):
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


def archive_current_ledger(project_root: Path, release_id: str) -> dict[str, Any]:
    validate_release_id(release_id)
    from audiagentic.components.ledger.legacy_runtime import migrate_legacy_runtime
    from audiagentic.components.ledger.sync import ledger_write_lock

    with ledger_write_lock(project_root):
        left = migrate_legacy_runtime(project_root)["left-in-place"]
        if left:
            # An event an older layout left behind must not silently miss the release.
            raise AudiaGenticError(
                code="CON-LEDGER-011", kind="release",
                message="retained events could not be migrated; release refused",
                details={"left-in-place": left},
            )
        return _archive_current_ledger_locked(project_root, release_id)


def _archive_current_ledger_locked(project_root: Path, release_id: str) -> dict[str, Any]:
    """Release every pending event while the shared ledger write lock is held.

    Pending means "not in the historical ledger", so the only file written is ``LEDGER.ndjson`` (plus the release
    summary reset): the baseline and the event files are never edited or deleted, a retry cannot double-release,
    and a stale branch carrying an already-released event cannot make it pending again.
    """
    historical_path = historical_ledger_path(project_root)
    historical = _merge_historical_events(load_persisted_events(historical_path, role="historical"), [])
    # Reading the pending set also proves no current event conflicts with a released identity.
    pending = pending_events(project_root)
    prior_ids = sorted(e["event-id"] for e in historical if e.get("release-id") == release_id)
    if prior_ids or not pending:
        # A retry of an already-archived release reports its events and never absorbs events recorded since for
        # the next release; with nothing pending and nothing archived the release simply has no ledger events.
        result: dict[str, Any] = {
            "release-id": release_id,
            "archived-events": len(prior_ids),
            "historical-ledger": str(historical_path),
            "released-event-ids": prior_ids,
        }
        return {**result, "idempotent-retry": True} if prior_ids else {**result, "empty": True}

    released_events = [{**e, "status": "released", "release-id": release_id} for e in pending]
    for event in released_events:
        # Fail closed before writing: a legacy row the strict contract rejects must be repaired, not archived
        # into a historical ledger that every later read would then refuse.
        validate_persisted_event(event, location=f"archive:{event['event-id']}", role="historical")

    merged = _merge_historical_events(historical, released_events)
    # The summary reset is idempotent and comes first: a crash after it leaves the release unarchived (a retry
    # redoes both), and the historical write is the single atomic commit point of the release.
    atomic_write_text(current_release_md_path(project_root), "# Current Release\n\n## Changes\n\n")
    atomic_write_ndjson(historical_path, merged)
    return {
        "release-id": release_id,
        "archived-events": len(released_events),
        "historical-ledger": str(historical_path),
        "released-event-ids": sorted(e["event-id"] for e in released_events),
    }
