"""Durable provider-neutral ownership registry for relocated session roots."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_session_root_registry_lock_path,
    gateway_session_root_registry_path,
)
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock


def _read(project_root: Path) -> dict[str, Any]:
    path = gateway_session_root_registry_path(project_root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "entries": []}
    return value if isinstance(value, dict) and isinstance(value.get("entries"), list) else {"version": 1, "entries": []}


def register_session_root(project_root: Path, *, session_id: str, request_ids: tuple[str, ...], root: Path) -> None:
    """Atomically publish one session root and its opening request lineage."""
    if not session_id or not request_ids:
        raise ValueError("session_id and request_ids are required")
    with StartupLock(gateway_session_root_registry_lock_path(project_root)):
        data = _read(project_root)
        entries = [entry for entry in data["entries"] if entry.get("session-id") != session_id]
        entries.append({"session-id": session_id, "request-ids": sorted(set(request_ids)), "root": str(root)})
        atomic_write_json(gateway_session_root_registry_path(project_root), {"version": 1, "entries": entries})


def unregister_session_root(project_root: Path, *, session_id: str) -> None:
    """Release a root only through explicit durable lineage cleanup."""
    with StartupLock(gateway_session_root_registry_lock_path(project_root)):
        data = _read(project_root)
        entries = [entry for entry in data["entries"] if entry.get("session-id") != session_id]
        atomic_write_json(gateway_session_root_registry_path(project_root), {"version": 1, "entries": entries})


def request_ids_for_registered_roots(project_root: Path, request_id: str) -> tuple[str, ...]:
    """Return registered session ids that retain ``request_id``."""
    with StartupLock(gateway_session_root_registry_lock_path(project_root)):
        data = _read(project_root)
    return tuple(sorted({str(entry["session-id"]) for entry in data["entries"] if request_id in entry.get("request-ids", [])}))


__all__ = ["register_session_root", "unregister_session_root", "request_ids_for_registered_roots"]
