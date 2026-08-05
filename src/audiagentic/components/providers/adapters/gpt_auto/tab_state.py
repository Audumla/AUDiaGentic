"""Persistent mapping of ChatGPT workspace/project -> open browser tab.

gpt-auto should reuse an existing ChatGPT tab instead of opening a fresh
/projects tab on every run.  Each tab has a stable puppeteer target id while
the browser is running.  We persist ``{project_name: {tab_id, workspace_url,
conversation_id, updated_at}}`` so a later run can re-activate the same tab.

The mapping is stored under ``<project_root>/.audiagentic/runtime/providers/
gpt-auto-state.json`` (runtime state, not provider config).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_STATE_PATH = Path(".audiagentic") / "runtime" / "providers" / "gpt-auto-state.json"


def state_path(project_root: Path | None = None) -> Path:
    if project_root is not None:
        return project_root / _DEFAULT_STATE_PATH
    # Fall back to CWD when the caller doesn't know the project root
    return Path.cwd() / _DEFAULT_STATE_PATH


def load_state(project_root: Path | None = None) -> dict[str, Any]:
    """Load the persisted tab mapping (empty mapping if missing/corrupt)."""
    path = state_path(project_root)
    if not path.exists():
        return {"tabs": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read gpt-auto state %s: %s", path, exc)
        return {"tabs": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("tabs"), dict):
        return {"tabs": {}}
    return payload


def save_state(payload: dict[str, Any], project_root: Path | None = None) -> None:
    """Persist the tab mapping atomically."""
    path = state_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Failed to write gpt-auto state %s: %s", path, exc)


def get_mapping(
    project_name: str,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the persisted tab mapping for *project_name*, or None."""
    return load_state(project_root).get("tabs", {}).get(project_name)


def update_mapping(
    project_name: str,
    *,
    tab_id: str = "",
    workspace_url: str = "",
    conversation_id: str = "",
    project_root: Path | None = None,
) -> None:
    """Merge fields into the persisted mapping entry for *project_name*."""
    payload = load_state(project_root)
    tabs = payload.setdefault("tabs", {})
    entry = tabs.setdefault(project_name, {})
    if tab_id:
        entry["tab_id"] = tab_id
    if workspace_url:
        entry["workspace_url"] = workspace_url
    if conversation_id:
        entry["conversation_id"] = conversation_id
    entry["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(payload, project_root)
