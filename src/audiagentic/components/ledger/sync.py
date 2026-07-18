"""Sync current release ledger from fragments."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.paths import (
    current_ledger_path,
    ledger_fragments_dir,
    ledger_manifest_path,
    ledger_sync_dir,
    safe_json_load,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_ndjson, atomic_write_text
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SyncResult:
    ledger_path: Path
    manifest_path: Path
    fragment_count: int
    purged_fragment_count: int
    warning: str | None


def _purge_synced_fragments(project_root: Path, synced_ids: set[str]) -> int:
    """Delete synced fragment files and clean up stale entries."""
    fragments_dir = ledger_fragments_dir(project_root)
    if not fragments_dir.exists():
        return 0

    removed = 0
    for entry in fragments_dir.iterdir():
        if entry.is_file() and entry.suffix == ".json":
            try:
                eid = json.loads(entry.read_text(encoding="utf-8")).get("event-id") or entry.stem
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to parse fragment %s for purge", entry, exc_info=True)
                eid = entry.stem
            if eid in synced_ids:
                entry.unlink()
                removed += 1
        elif entry.is_file():
            if not entry.stat().st_size:
                entry.unlink()
                removed += 1
            else:
                logger.warning("Non-JSON stale file in fragments: %s", entry.name)
        elif entry.is_dir():
            try:
                entry.rmdir()
                removed += 1
            except OSError:
                logger.warning("Non-empty stray directory in fragments: %s", entry)

    return removed


def _lock_path(project_root: Path) -> Path:
    return ledger_sync_dir(project_root) / "lock.json"


def _manifest_path(project_root: Path) -> Path:
    return ledger_manifest_path(project_root)


def _acquire_lock(project_root: Path) -> tuple[StartupLock, str | None]:
    lock_path = _lock_path(project_root)
    warning = "stale-lock-replaced" if lock_path.exists() else None
    lock = StartupLock(lock_path, timeout=0.1)
    try:
        lock.__enter__()
    except AudiaGenticError as exc:
        if exc.code == "TO-PROC-002":
            raise AudiaGenticError(
                code="CON-SYNCL-001",
                kind="release",
                message="sync lock already held",
                details={"path": str(lock_path)},
            ) from exc
        raise
    return lock, warning


def _release_lock(lock: StartupLock) -> None:
    lock.__exit__()


def _fragment_dir(project_root: Path) -> Path:
    return ledger_fragments_dir(project_root)


def _load_fragments(project_root: Path) -> list[dict[str, Any]]:
    fragments_dir = _fragment_dir(project_root)
    if not fragments_dir.exists():
        return []
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(fragments_dir.glob("*.json"))
    ]


def _load_manifest(project_root: Path) -> dict[str, Any]:
    manifest_path = _manifest_path(project_root)
    if not manifest_path.exists():
        return {}
    result = safe_json_load(manifest_path)
    if result is None:
        logger.warning("Corrupt manifest, falling back to full sync", exc_info=True)
        return {}
    return result


def sync_current_release_ledger(project_root: Path) -> SyncResult:
    lock, warning = _acquire_lock(project_root)
    try:
        fragments = _load_fragments(project_root)
        current_ids = {f["event-id"] for f in fragments}
        manifest = _load_manifest(project_root)
        synced_ids = set(manifest.get("fragment-ids", []))

        if not fragments or (synced_ids and synced_ids == current_ids):
            atomic_write_text(ledger_manifest_path(project_root), json.dumps({
                "synced-at": now_iso_z(),
                "fragment-count": len(fragments),
                "fragment-ids": sorted(current_ids),
                "ledger-path": str(current_ledger_path(project_root)),
            }, indent=2))
        else:
            new_ids = current_ids - synced_ids
            if new_ids and synced_ids:
                new_fragments = [f for f in fragments if f["event-id"] in new_ids]
                atomic_write_ndjson(current_ledger_path(project_root), new_fragments, append=True)
            else:
                atomic_write_ndjson(current_ledger_path(project_root), fragments)

            atomic_write_text(ledger_manifest_path(project_root), json.dumps({
                "synced-at": now_iso_z(),
                "fragment-count": len(fragments),
                "fragment-ids": sorted(current_ids),
                "ledger-path": str(current_ledger_path(project_root)),
            }, indent=2))

        purged = _purge_synced_fragments(project_root, current_ids)
    finally:
        _release_lock(lock)

    return SyncResult(
        ledger_path=current_ledger_path(project_root),
        manifest_path=ledger_manifest_path(project_root),
        fragment_count=len(fragments),
        purged_fragment_count=purged,
        warning=warning,
    )
