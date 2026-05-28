"""Sync current release ledger from fragments."""
from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, load_ndjson

STALE_AFTER_SECONDS = 300


@dataclass(frozen=True)
class SyncResult:
    ledger_path: Path
    manifest_path: Path
    fragment_count: int
    warning: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _lock_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"


def _manifest_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "sync" / "manifest.json"


def _acquire_lock(project_root: Path) -> tuple[Path, str | None]:
    lock_path = _lock_path(project_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    warning = None

    if lock_path.exists():
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        acquired_at = payload.get("acquired-at")
        pid = int(payload.get("pid", 0))
        try:
            acquired_dt = datetime.fromisoformat(acquired_at.replace("Z", "+00:00")) if acquired_at else datetime.now(timezone.utc)
        except ValueError:
            acquired_dt = datetime.now(timezone.utc)
        age = (datetime.now(timezone.utc) - acquired_dt).total_seconds()

        pid_alive = False
        if pid:
            try:
                os.kill(pid, 0)
                pid_alive = True
            except Exception:
                pass

        if age <= STALE_AFTER_SECONDS and pid_alive:
            raise AudiaGenticError(
                code="RLS-BUSINESS-010",
                kind="business-rule",
                message="sync lock already held",
                details={"pid": pid},
            )
        warning = "stale-lock-replaced"

    lock_path.write_text(json.dumps({
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "acquired-at": _now(),
        "command": "sync-current-release-ledger",
    }, indent=2), encoding="utf-8")
    return lock_path, warning


def _release_lock(lock_path: Path) -> None:
    if lock_path.exists():
        lock_path.unlink()


def _fragment_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"


def _load_fragments(project_root: Path) -> list[dict[str, Any]]:
    fragments_dir = _fragment_dir(project_root)
    if not fragments_dir.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(fragments_dir.glob("*.json"))
    ]


def _merge_by_event_id(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {e["event-id"]: e for e in current}
    for event in incoming:
        by_id.setdefault(event["event-id"], event)
    return [by_id[k] for k in sorted(by_id.keys())]


def sync_current_release_ledger(project_root: Path) -> SyncResult:
    ledger_path = project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lock_path, warning = _acquire_lock(project_root)
    try:
        fragments = _load_fragments(project_root)
        merged = _merge_by_event_id(load_ndjson(ledger_path), fragments)
        atomic_write_ndjson(ledger_path, merged)

        manifest_path = _manifest_path(project_root)
        manifest_path.write_text(json.dumps({
            "synced-at": _now(),
            "fragment-count": len(fragments),
            "ledger-path": str(ledger_path),
        }, indent=2), encoding="utf-8")
    finally:
        _release_lock(lock_path)

    return SyncResult(
        ledger_path=ledger_path,
        manifest_path=_manifest_path(project_root),
        fragment_count=len(fragments),
        warning=warning,
    )
