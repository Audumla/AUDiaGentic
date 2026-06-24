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
    return {**result, "ledger-count": sync_result.fragment_count}


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
    return {**payload, "ledger-count": sync_result.fragment_count}


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
