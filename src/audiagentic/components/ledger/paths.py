"""Path constants for the ledger component.

All ledger-specific paths are loaded from the component configuration file
(agent-ledger.yaml) and resolved relative to the project root.
"""
from __future__ import annotations

from pathlib import Path

# Component config path
_COMPONENT_CONFIG = ".audiagentic/components/agent-ledger.yaml"

# Defaults (used when config is not yet installed)
_DEFAULT_PATHS = {
    "ledger-runtime": ".audiagentic/runtime/ledger",
    "sync-dir": ".audiagentic/runtime/ledger/sync",
    "lock-file": "lock.json",
    "events-dir": "docs/releases/events",
    "generated-dir": ".audiagentic/runtime/ledger/generated",
    "releases-dir": "docs/releases",
    "current-ledger": "CURRENT_RELEASE_LEDGER.ndjson",
    "historical-ledger": "LEDGER.ndjson",
    "current-summary": "CURRENT_RELEASE.md",
    "audit-summary": "AUDIT_SUMMARY.md",
    "checkin": "CHECKIN.md",
}


def _load_paths(project_root: Path) -> dict[str, str]:
    """Load path constants from component config, falling back to defaults."""
    from audiagentic.foundation.paths import load_component_paths

    return load_component_paths(project_root, "agent-ledger", _DEFAULT_PATHS)


def _resolve(project_root: Path, key: str) -> Path:
    """Resolve a named path constant relative to project root."""
    from audiagentic.foundation.paths import resolve_component_path

    return resolve_component_path(project_root, "agent-ledger", key, _DEFAULT_PATHS)


def ledger_sync_dir(project_root: Path) -> Path:
    """Return .audiagentic/runtime/ledger/sync."""
    return _resolve(project_root, "sync-dir")


def ledger_lock_path(project_root: Path) -> Path:
    """Return .audiagentic/runtime/ledger/sync/lock.json."""
    return ledger_sync_dir(project_root) / _load_paths(project_root).get("lock-file", "lock.json")


def ledger_events_dir(project_root: Path) -> Path:
    """Return docs/releases/events: one tracked, write-once file per recorded event."""
    return _resolve(project_root, "events-dir")


def ledger_generated_dir(project_root: Path) -> Path:
    """Return the untracked directory for derived projections (summaries, audit, check-in)."""
    return _resolve(project_root, "generated-dir")


def releases_dir(project_root: Path) -> Path:
    """Return docs/releases."""
    return _resolve(project_root, "releases-dir")


def current_ledger_path(project_root: Path) -> Path:
    """Return docs/releases/CURRENT_RELEASE_LEDGER.ndjson: the frozen, read-only legacy baseline."""
    return releases_dir(project_root) / _load_paths(project_root).get("current-ledger", "CURRENT_RELEASE_LEDGER.ndjson")


def historical_ledger_path(project_root: Path) -> Path:
    """Return docs/releases/LEDGER.ndjson."""
    return releases_dir(project_root) / _load_paths(project_root).get("historical-ledger", "LEDGER.ndjson")


def current_release_md_path(project_root: Path) -> Path:
    """Return docs/releases/CURRENT_RELEASE.md: the tracked release document, written only at release finalize."""
    return releases_dir(project_root) / _load_paths(project_root).get("current-summary", "CURRENT_RELEASE.md")


def generated_current_summary_path(project_root: Path) -> Path:
    """Return the untracked current-release summary projection."""
    return ledger_generated_dir(project_root) / _load_paths(project_root).get("current-summary", "CURRENT_RELEASE.md")


def audit_summary_md_path(project_root: Path) -> Path:
    """Return the untracked audit summary projection."""
    return ledger_generated_dir(project_root) / _load_paths(project_root).get("audit-summary", "AUDIT_SUMMARY.md")


def checkin_md_path(project_root: Path) -> Path:
    """Return the untracked check-in projection."""
    return ledger_generated_dir(project_root) / _load_paths(project_root).get("checkin", "CHECKIN.md")


def ledger_component_marker(project_root: Path) -> Path:
    """Return .audiagentic/components/agent-ledger.yaml."""
    return project_root / _COMPONENT_CONFIG
