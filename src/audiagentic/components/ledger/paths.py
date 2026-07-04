"""Path constants for the ledger component.

All ledger-specific paths are loaded from the component configuration file
(agent-ledger.yaml) and resolved relative to the project root.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Component config path
_COMPONENT_CONFIG = ".audiagentic/components/agent-ledger.yaml"

# Defaults (used when config is not yet installed)
_DEFAULT_PATHS = {
    "ledger-runtime": ".audiagentic/runtime/ledger",
    "sync-dir": ".audiagentic/runtime/ledger/sync",
    "lock-file": "lock.json",
    "manifest-file": "manifest.json",
    "fragments-dir": ".audiagentic/runtime/ledger/fragments",
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


def ledger_manifest_path(project_root: Path) -> Path:
    """Return .audiagentic/runtime/ledger/sync/manifest.json."""
    return ledger_sync_dir(project_root) / _load_paths(project_root).get("manifest-file", "manifest.json")


def ledger_fragments_dir(project_root: Path) -> Path:
    """Return .audiagentic/runtime/ledger/fragments."""
    return _resolve(project_root, "fragments-dir")


def releases_dir(project_root: Path) -> Path:
    """Return docs/releases."""
    return _resolve(project_root, "releases-dir")


def current_ledger_path(project_root: Path) -> Path:
    """Return docs/releases/CURRENT_RELEASE_LEDGER.ndjson."""
    return releases_dir(project_root) / _load_paths(project_root).get("current-ledger", "CURRENT_RELEASE_LEDGER.ndjson")


def historical_ledger_path(project_root: Path) -> Path:
    """Return docs/releases/LEDGER.ndjson."""
    return releases_dir(project_root) / _load_paths(project_root).get("historical-ledger", "LEDGER.ndjson")


def current_release_md_path(project_root: Path) -> Path:
    """Return docs/releases/CURRENT_RELEASE.md."""
    return releases_dir(project_root) / _load_paths(project_root).get("current-summary", "CURRENT_RELEASE.md")


def audit_summary_md_path(project_root: Path) -> Path:
    """Return docs/releases/AUDIT_SUMMARY.md."""
    return releases_dir(project_root) / _load_paths(project_root).get("audit-summary", "AUDIT_SUMMARY.md")


def checkin_md_path(project_root: Path) -> Path:
    """Return docs/releases/CHECKIN.md."""
    return releases_dir(project_root) / _load_paths(project_root).get("checkin", "CHECKIN.md")


def ledger_component_marker(project_root: Path) -> Path:
    """Return .audiagentic/components/agent-ledger.yaml."""
    return project_root / _COMPONENT_CONFIG


def safe_json_load(path: Path) -> Any:
    """Load JSON from a file, returning None on any error.

    Logs a warning on failure for observability.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load JSON from %s: %s", path, exc)
        return None
