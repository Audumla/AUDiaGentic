"""Sync current release ledger from fragments."""
from __future__ import annotations

import json
import os
import socket
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

LOCK_TIMEOUT_SECONDS = 60
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
        if acquired_at:
            try:
                acquired_dt = datetime.fromisoformat(acquired_at.replace("Z", "+00:00"))
            except ValueError:
                acquired_dt = datetime.now(timezone.utc)
        else:
            acquired_dt = datetime.now(timezone.utc)
        age = (datetime.now(timezone.utc) - acquired_dt).total_seconds()

        pid_alive = False
        if pid:
            try:
                os.kill(pid, 0)
                pid_alive = True
            except Exception:
                pid_alive = False

        if age <= STALE_AFTER_SECONDS and pid_alive:
            raise AudiaGenticError(
                code="RLS-BUSINESS-010",
                kind="business-rule",
                message="sync lock already held",
                details={"pid": pid},
            )
        warning = "stale-lock-replaced"

    payload = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "acquired-at": _now(),
        "command": "sync-current-release-ledger",
    }
    lock_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
    events = []
    for fragment_path in sorted(fragments_dir.glob("*.json")):
        events.append(json.loads(fragment_path.read_text(encoding="utf-8")))
    return events


def _load_current_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    entries = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _merge_by_event_id(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {entry["event-id"]: entry for entry in current}
    for event in incoming:
        by_id.setdefault(event["event-id"], event)
    return [by_id[key] for key in sorted(by_id.keys())]


def _write_ndjson(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True))
                handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def sync_current_release_ledger(project_root: Path) -> SyncResult:
    ledger_path = project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    lock_path, warning = _acquire_lock(project_root)
    try:
        fragments = _load_fragments(project_root)
        current = _load_current_ledger(ledger_path)
        merged = _merge_by_event_id(current, fragments)
        _write_ndjson(ledger_path, merged)

        manifest = {
            "synced-at": _now(),
            "fragment-count": len(fragments),
            "ledger-path": str(ledger_path),
        }
        manifest_path = _manifest_path(project_root)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        _release_lock(lock_path)

    return SyncResult(
        ledger_path=ledger_path,
        manifest_path=_manifest_path(project_root),
        fragment_count=len(fragments),
        warning=warning,
    )
