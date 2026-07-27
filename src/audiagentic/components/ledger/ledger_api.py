"""Public API surface for the agent-ledger component.

All inter-component callers and MCP wrappers import only from here.
Internal modules (fragments, sync, audit, etc.) are implementation details.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.archive import archive_current_ledger
from audiagentic.components.ledger.audit import generate_audit_and_checkin
from audiagentic.components.ledger.current_summary import regenerate_current_release
from audiagentic.components.ledger.fragments import record_change_event as _record
from audiagentic.components.ledger.paths import (
    current_ledger_path,
    ledger_component_marker,
    ledger_fragments_dir,
    ledger_manifest_path,
    releases_dir,
)
from audiagentic.components.ledger.sync import sync_current_release_ledger
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_ndjson


def record_change(project_root: Path, event: dict[str, Any], *, sync: bool = False) -> dict[str, Any]:
    """Validate and record a change event fragment, optionally syncing the current ledger."""
    result = _record(project_root, event)
    if not sync:
        return result
    sync_result = sync_current_release_ledger(project_root)
    return {**result, "ledger-count": sync_result.fragment_count, "purged-fragments": sync_result.purged_fragment_count}


def record_changes(project_root: Path, events: list[dict[str, Any]], *, sync: bool = False) -> dict[str, Any]:
    """Record multiple change event fragments, optionally syncing once at the end."""
    results = [_record(project_root, event) for event in events]
    payload: dict[str, Any] = {
        "count": len(results),
        "results": results,
    }
    if not sync:
        return payload
    sync_result = sync_current_release_ledger(project_root)
    return {**payload, "ledger-count": sync_result.fragment_count, "purged-fragments": sync_result.purged_fragment_count}


def refresh_current_summary(project_root: Path) -> str:
    """Regenerate the current release summary markdown and return its content."""
    path = regenerate_current_release(project_root)
    return path.read_text(encoding="utf-8")


def get_current_summary(project_root: Path) -> str:
    """Return current release summary markdown, regenerating only if missing."""
    path = releases_dir(project_root) / "CURRENT_RELEASE.md"
    if not path.exists():
        return refresh_current_summary(project_root)
    return path.read_text(encoding="utf-8")


def sync(project_root: Path) -> dict[str, Any]:
    """Merge all fragments into the current release ledger."""
    result = sync_current_release_ledger(project_root)
    return {
        "fragment-count": result.fragment_count,
        "purged-fragment-count": result.purged_fragment_count,
        "ledger-path": str(result.ledger_path),
        "warning": result.warning,
    }


def generate_audit(project_root: Path) -> dict[str, Any]:
    """Regenerate audit summary and check-in docs from the current ledger."""
    audit_path, checkin_path = generate_audit_and_checkin(project_root)
    return {
        "audit-path": str(audit_path),
        "checkin-path": str(checkin_path),
    }


def archive_current(project_root: Path, release_id: str) -> dict[str, Any]:
    """Merge current ledger into historical and reset current. Called before release finalization."""
    return archive_current_ledger(project_root, release_id)


def archive_for_release(project_root: Path, release_id: str) -> dict[str, Any]:
    """Sync and archive the current ledger for a release finalization request."""
    sync(project_root)
    try:
        return archive_current(project_root, release_id)
    except AudiaGenticError as exc:
        if exc.code not in {"RLS-BUSINESS-020", "CON-ARCHIVE-001"}:
            raise
        historical_path = project_root / "docs" / "releases" / "LEDGER.ndjson"
        historical = load_ndjson(historical_path)
        if not any(event.get("release-id") == release_id for event in historical):
            raise
        return {
            "release-id": release_id,
            "archived-events": 0,
            "purged-fragments": 0,
            "historical-ledger": str(historical_path),
            "released-event-ids": [],
        }


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

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if keys[i] & keys[j]:  # non-empty intersection
                union(i, j)

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
    entries = load_ndjson(current_ledger_path(project_root))
    pending = [e for e in entries if e.get("status") == "unreleased"]

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
    """Retrieve a single change event by event-id.

    Looks in the current ledger NDJSON.  Returns the full event dict or
    raises AudiaGenticError (CON-LEDGER-001) if not found.
    """
    entries = load_ndjson(current_ledger_path(project_root))
    for entry in entries:
        if entry.get("event-id") == event_id:
            return entry
    raise AudiaGenticError(
        code="CON-LEDGER-001",
        kind="release",
        message=f"no event found with id '{event_id}'",
        details={"event-id": event_id},
    )


def get_status(project_root: Path) -> dict[str, Any]:
    """Return ledger installation state and current fragment/sync status."""
    marker = ledger_component_marker(project_root)
    manifest = ledger_manifest_path(project_root)
    fragments_dir = ledger_fragments_dir(project_root)

    fragment_count = len(list(fragments_dir.glob("*.json"))) if fragments_dir.exists() else 0
    last_synced: str | None = None
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        last_synced = data.get("synced-at")

    return {
        "installed": marker.exists(),
        "fragment-count": fragment_count,
        "last-synced": last_synced,
        "current-ledger": str(current_ledger_path(project_root)),
    }
