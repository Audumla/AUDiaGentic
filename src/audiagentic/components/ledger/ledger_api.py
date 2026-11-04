"""Public API surface for the agent-ledger component.

All inter-component callers and MCP wrappers import only from here.
Internal modules (fragments, sync, audit, etc.) are implementation details.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger.archive import archive_current_ledger
from audiagentic.components.ledger.audit import generate_audit_and_checkin
from audiagentic.components.ledger.current_events import iter_events, pending_events
from audiagentic.components.ledger.current_summary import regenerate_current_release
from audiagentic.components.ledger.event_outbox import drain as drain_event_outbox
from audiagentic.components.ledger.paths import (
    ledger_component_marker,
    ledger_events_dir,
    ledger_generated_dir,
)
from audiagentic.components.ledger.recorder import record_change_event as _record
from audiagentic.components.ledger.sync import check_current_ledger
from audiagentic.foundation.contracts.errors import AudiaGenticError


def record_change(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Validate and record one change event as its own tracked, write-once event file."""
    drain_event_outbox(project_root)
    result = _record(project_root, event)
    return {**result, "pending-count": len(pending_events(project_root))}


def record_changes(project_root: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    """Record multiple change events."""
    drain_event_outbox(project_root)
    results = [_record(project_root, event) for event in events]
    return {"count": len(results), "results": results, "pending-count": len(pending_events(project_root))}


def refresh_current_summary(project_root: Path) -> str:
    """Regenerate the current release summary markdown and return its content."""
    path = regenerate_current_release(project_root)
    return path.read_text(encoding="utf-8")


def get_current_summary(project_root: Path) -> str:
    """Return the current release summary, rendered from the pending events (an untracked projection)."""
    return refresh_current_summary(project_root)


def sync(project_root: Path) -> dict[str, Any]:
    """Validate every current ledger source through the one loader and report the pending count."""
    result = check_current_ledger(project_root)
    return {"pending-count": result.pending_count, "warning": result.warning}


def generate_audit(project_root: Path) -> dict[str, Any]:
    """Regenerate audit summary and check-in docs from the current ledger."""
    audit_path, checkin_path = generate_audit_and_checkin(project_root)
    return {
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }


def archive_current(project_root: Path, release_id: str) -> dict[str, Any]:
    """Release the pending events into the historical ledger. Called before release finalization."""
    return archive_current_ledger(project_root, release_id)


def archive_for_release(project_root: Path, release_id: str) -> dict[str, Any]:
    """Release every pending event under ``release_id`` (idempotent), writing only the historical ledger."""
    return archive_current_ledger(project_root, release_id)


def release_events(
    historical: list[dict[str, Any]],
    release_id: str,
    released_event_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Select released events for the release component's standard templates."""
    if released_event_ids:
        selected_ids = set(released_event_ids)
        return sorted(
            (event for event in historical if event.get("event-id") in selected_ids
             and event.get("release-id") == release_id and event.get("status") == "released"),
            key=lambda event: event.get("event-id", ""),
        )
    return sorted(
        (
            event for event in historical
            if event.get("release-id") == release_id and event.get("status") == "released"
        ),
        key=lambda event: event.get("event-id", ""),
    )


def _union_find_cluster(keys: list[frozenset[str]]) -> list[list[int]]:
    """Cluster indices by transitive key overlap (union-find).

    Returns groups of indices whose keys share at least one element,
    merged transitively.  e.g. [0:{A}, 1:{B}, 2:{A,B}] → [[0,1,2]].
    """
    parent: list[int] = list(range(len(keys)))  # noqa: C416

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]  # path compression
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    first_with_key: dict[str, int] = {}
    for i, event_keys in enumerate(keys):
        for key in event_keys:
            if key in first_with_key:
                union(i, first_with_key[key])  # shares this key with an earlier event
            else:
                first_with_key[key] = i

    groups: dict[int, list[int]] = {}
    for i in range(len(keys)):
        groups.setdefault(find(i), []).append(i)
    return [sorted(indices) for indices in groups.values()]


def _compact_event(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a compact view of one ledger event."""
    return {
        "event-id": entry.get("event-id", ""),
        "change-class": entry.get("change-class", ""),
        "user-summary-candidate": entry.get("user-summary-candidate", ""),
        "plan-item-ids": entry.get("plan-item-ids") or [],
        "files": entry.get("files") or [],
    }


def get_pending_events(
    project_root: Path,
    group_by: str = "plan-items",
) -> dict[str, Any]:
    """Return pending (unreleased) events grouped for commit decisions.

    group_by:
      - "plan-items" (default): cluster by shared plan-item-ids via union-find.
      - "files": cluster by file overlap via union-find.
      - "flat": no grouping, raw list.
    """
    pending = pending_events(project_root)

    if not pending:
        return {"groups": [], "ungrouped": []} if group_by != "flat" else {"events": []}

    # Flat mode — no clustering
    if group_by == "flat":
        return {"events": [_compact_event(e) for e in pending]}

    # Build cluster keys per event
    if group_by == "plan-items":
        keys = [frozenset(e.get("plan-item-ids") or []) for e in pending]
    else:  # files
        keys = [frozenset(e.get("files") or []) for e in pending]

    cluster_indices = _union_find_cluster(keys)

    groups: list[dict[str, Any]] = []
    ungrouped: list[dict[str, Any]] = []

    for indices in cluster_indices:
        group_events = [pending[i] for i in indices]
        if len(indices) == 1:
            # Single event — ungrouped (no overlap with anything else)
            compact = _compact_event(group_events[0])
            ungrouped.append({
                "event-id": compact["event-id"],
                "change-class": compact["change-class"],
                "files": compact["files"],
                "user-summary-candidate": compact["user-summary-candidate"],
            })
        else:
            all_files: set[str] = set()
            for e in group_events:
                all_files.update(e.get("files") or [])
            groups.append({
                "event-count": len(group_events),
                "files": sorted(all_files),
                "summaries": [
                    {
                        "event-id": e.get("event-id", ""),
                        "change-class": e.get("change-class", ""),
                        "user-summary-candidate": e.get("user-summary-candidate", ""),
                        "plan-item-ids": e.get("plan-item-ids") or [],
                    }
                    for e in group_events
                ],
            })

    return {"groups": groups, "ungrouped": ungrouped}


def get_fragment(event_id: str, project_root: Path) -> dict[str, Any]:
    """Retrieve a single recorded change event by event-id.

    Searches every recorded event (working tree). Returns the full event dict or raises
    AudiaGenticError (CON-LEDGER-001) if not found.
    """
    for entry in iter_events(project_root):
        if entry.get("event-id") == event_id:
            return entry
    raise AudiaGenticError(
        code="CON-LEDGER-001",
        kind="release",
        message=f"no event found with id '{event_id}'",
        details={"event-id": event_id},
    )


def get_status(project_root: Path) -> dict[str, Any]:
    """Return ledger installation state and the recorded-event counts."""
    drain_event_outbox(project_root)
    marker = ledger_component_marker(project_root)
    events_dir = ledger_events_dir(project_root)
    return {
        "installed": marker.exists(),
        "event-file-count": len(list(events_dir.glob("*.json"))) if events_dir.exists() else 0,
        "pending-count": len(pending_events(project_root)),
        "events-dir": str(events_dir),
        "generated-dir": str(ledger_generated_dir(project_root)),
    }
