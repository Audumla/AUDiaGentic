"""Public API surface for the agent-ledger component.

All inter-component callers and MCP wrappers import only from here.
Internal modules (fragments, sync, audit, etc.) are implementation details.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.optional.ledger.archive import archive_current_ledger
from audiagentic.components.optional.ledger.audit import generate_audit_and_checkin
from audiagentic.components.optional.ledger.current_summary import regenerate_current_release
from audiagentic.components.optional.ledger.fragments import record_change_event as _record
from audiagentic.components.optional.ledger.sync import sync_current_release_ledger


def record_change(project_root: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Validate and record a change event fragment, then sync to current ledger."""
    result = _record(project_root, event)
    sync_result = sync_current_release_ledger(project_root)
    return {**result, "ledger-count": sync_result.fragment_count}


def get_current_summary(project_root: Path) -> str:
    """Return the current release summary markdown content."""
    path = regenerate_current_release(project_root)
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


def get_status(project_root: Path) -> dict[str, Any]:
    """Return ledger installation state and current fragment/sync status."""
    marker = project_root / ".audiagentic" / "components" / "agent-ledger.yaml"
    manifest = project_root / ".audiagentic" / "runtime" / "ledger" / "sync" / "manifest.json"
    fragments_dir = project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"

    fragment_count = len(list(fragments_dir.glob("*.json"))) if fragments_dir.exists() else 0
    last_synced: str | None = None
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        last_synced = data.get("synced-at")

    return {
        "installed": marker.exists(),
        "fragment-count": fragment_count,
        "last-synced": last_synced,
        "current-ledger": str(project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"),
    }
