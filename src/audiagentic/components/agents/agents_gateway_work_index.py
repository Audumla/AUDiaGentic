"""Transactional active/admitted work index for gateway control-plane recovery (SH07 C7).

This is a references-only index: each entry carries bounded scalar metadata about a
gateway request's dispatch lifecycle phase.  The durable request record remains the
single source of truth; this index exists so that recovery can discover admitted
work even when the service crashes before it has claimed the dispatch (admission-before-claim
window).

Rules:
- No prompt bodies, outputs, raw provider refs, auth tokens, tool payloads, or stack traces.
- Malformed entries are quarantined, never silently deleted.
- Cleanup after terminalization is non-throwing; cleanup failure must not undo terminal state.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_utc_epoch_s

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "v1"
_INDEX_DIR = "active-work"
_QUARANTINE_SUBDIR = "quarantine"

_PHASE_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "admitted": frozenset({"claimed", "terminal-cleanup"}),
    "claimed": frozenset({"running", "terminal-cleanup"}),
    "running": frozenset({"terminal-cleanup"}),
}


class Phase(str, Enum):
    """Phases of work tracked by the control-plane index."""

    ADMITTED = "admitted"
    CLAIMED = "claimed"
    RUNNING = "running"
    TERMINAL_CLEANUP = "terminal-cleanup"


@dataclass(frozen=True)
class WorkIndexEntry:
    """Parsed and validated index entry.

    All fields are bounded scalars — no prompt material, provider refs, auth, or stack traces.
    """

    request_id: str
    project_root: Path
    project_root_digest: str
    phase: Literal["admitted", "claimed", "running", "terminal-cleanup"]
    owner_epoch: str | None = None
    lane_key: str | None = None
    admitted_at: str | None = None
    claimed_at: str | None = None
    schema_version: str = _SCHEMA_VERSION


@dataclass(frozen=True)
class InvalidEntry:
    """Represents an entry that failed validation."""

    path: Path
    reason_code: str  # e.g. "unreadable", "not-object", "missing-fields", "digest-mismatch"
    payload: dict[str, Any] | None = None


def _project_root_digest(project_root: Path) -> str:
    """Produce a short digest of the canonical project root path."""
    return hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:16]


def _index_dir(service_root: Path) -> Path:
    return service_root / _INDEX_DIR


def _quarantine_dir(service_root: Path) -> Path:
    return _index_dir(service_root) / _QUARANTINE_SUBDIR


def _entry_path(service_root: Path, request_id: str) -> Path:
    """Path for one work-index entry file.

    Filename encodes the request-id so recovery can correlate entries with
    request records without parsing the JSON body first.
    """
    return _index_dir(service_root) / f"{request_id}.json"


def quarantine_work_index_entry(
    service_root: Path,
    path: Path,
    *,
    reason_code: str,
) -> None:
    """Move a malformed index entry to the quarantine subdirectory.

    Never raises — quarantine move failure falls back to deletion as a last resort.
    """
    qdir = _quarantine_dir(service_root)
    qdir.mkdir(parents=True, exist_ok=True)
    import shutil  # noqa: PLC0414

    dest = qdir / f"{path.stem}_{reason_code}.json"
    try:
        shutil.move(str(path), str(dest))
    except OSError:
        logger.warning("quarantine move failed, unlinking", extra={"entry": path.name})
        path.unlink(missing_ok=True)


def _read_raw_entry(
    path: Path,
    *,
    service_root: Path | None = None,
) -> dict[str, Any] | None:
    """Read and parse one index entry file. Quarantines on any structural error.

    When *service_root* is provided, quarantine moves use the correct base
    directory.  When omitted, the service root is inferred from the path's
    parent chain (works for standard layouts).
    """
    if service_root is None:
        service_root = path.parent / ".."

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("quarantining unreadable work-index entry", extra={"entry": path.name})
        quarantine_work_index_entry(service_root, path, reason_code="unreadable")
        return None
    if not isinstance(value, dict):
        quarantine_work_index_entry(service_root, path, reason_code="not-object")
        return None
    required = ("request-id", "project-root", "phase")
    if not all(isinstance(value.get(k), str) and value[k] for k in required):
        quarantine_work_index_entry(service_root, path, reason_code="missing-fields")
        return None
    return value


def validate_work_index_entry(
    path_or_payload: Path | dict[str, Any],
) -> WorkIndexEntry | InvalidEntry:
    """Validate an index entry and return a parsed object or an InvalidEntry.

    Accepts either a file path (reads + validates) or a pre-parsed dict.
    When given a Path, enforces filename/body identity: the file stem must match
    the request-id in the body.  Does NOT quarantine — the caller decides
    disposition (quarantine vs skip).
    """
    if isinstance(path_or_payload, Path):
        raw = _read_raw_entry(path_or_payload)
        if raw is None:
            return InvalidEntry(path=path_or_payload, reason_code="already-quarantined")
    else:
        raw = path_or_payload

    request_id = raw.get("request-id")

    # Filename/body identity: when given a file path, the stem must match
    # the request-id in the body.  Tampered filenames indicate corruption.
    if isinstance(path_or_payload, Path) and request_id:
        expected_stem = f"{request_id}"
        if path_or_payload.stem != expected_stem:
            return InvalidEntry(
                path=path_or_payload,
                reason_code="filename-mismatch",
                payload=raw,
            )
    project_root_str = raw.get("project-root")
    phase = raw.get("phase")

    if not request_id or not isinstance(request_id, str):
        return InvalidEntry(
            path=path_or_payload if isinstance(path_or_payload, Path) else Path("inline"),
            reason_code="missing-request-id",
            payload=raw,
        )
    if not project_root_str or not isinstance(project_root_str, str):
        return InvalidEntry(
            path=path_or_payload if isinstance(path_or_payload, Path) else Path("inline"),
            reason_code="missing-project-root",
            payload=raw,
        )
    if phase not in _PHASE_LEGAL_TRANSITIONS:
        return InvalidEntry(
            path=path_or_payload if isinstance(path_or_payload, Path) else Path("inline"),
            reason_code="invalid-phase",
            payload=raw,
        )

    project_root = Path(project_root_str)
    expected_digest = _project_root_digest(project_root)
    stored_digest = raw.get("project-root-digest")

    if stored_digest and stored_digest != expected_digest:
        return InvalidEntry(
            path=path_or_payload if isinstance(path_or_payload, Path) else Path("inline"),
            reason_code="digest-mismatch",
            payload=raw,
        )

    return WorkIndexEntry(
        request_id=request_id,
        project_root=project_root,
        project_root_digest=expected_digest,
        phase=phase,
        owner_epoch=raw.get("owner-epoch"),
        lane_key=raw.get("lane-key"),
        admitted_at=raw.get("admitted-at"),
        claimed_at=raw.get("claimed-at"),
        schema_version=raw.get("schema-version", _SCHEMA_VERSION),
    )


def write_work_index_entry(
    service_root: Path,
    project_root: Path,
    request_id: str,
    *,
    phase: Literal["admitted", "claimed", "running", "terminal-cleanup"] = "admitted",
    owner_epoch: str | None = None,
    lane_key: str | None = None,
) -> None:
    """Write a new work-index entry for an admitted/claimed/running request.

    The entry is references-only: request-id, project-root digest, phase, owner epoch,
    and timing markers.  No prompt material, provider refs, or secrets.

    Raises only on I/O errors (atomic_write_json propagates OSError).
    """
    from audiagentic.foundation.time import now_iso_z

    idx_dir = _index_dir(service_root)
    idx_dir.mkdir(parents=True, exist_ok=True)

    digest = _project_root_digest(project_root)
    timestamp = now_iso_z()

    payload: dict[str, Any] = {
        "schema-version": _SCHEMA_VERSION,
        "request-id": request_id,
        "project-root": str(project_root),
        "project-root-digest": digest,
        "phase": phase,
        "owner-epoch": owner_epoch,
        "lane-key": lane_key,
        "admitted-at": timestamp,
        "claimed-at": None,
    }

    atomic_write_json(_entry_path(service_root, request_id), payload)


def update_work_index_phase(
    service_root: Path,
    request_id: str,
    *,
    from_phase: str,
    to_phase: str,
    owner_epoch: str | None = None,
) -> bool:
    """Transition a work-index entry's phase. Returns True on success, False if entry not found.

    Phase transitions must follow the legal transition graph:
      admitted -> claimed | terminal-cleanup
      claimed  -> running | terminal-cleanup
      running  -> terminal-cleanup

    Owner fencing: when transitioning from "claimed" or "running", the caller's
    owner_epoch must match the stored epoch.  The initial "admitted" phase carries
    no owner, so fencing is only enforced once ownership is established.

    Raises AudiaGenticError on illegal transitions or owner-mismatch.
    """
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.time import now_iso_z

    path = _entry_path(service_root, request_id)
    if not path.exists():
        return False

    raw = _read_raw_entry(path, service_root=service_root)
    if raw is None:
        return False

    entry = validate_work_index_entry(raw)
    if isinstance(entry, InvalidEntry):
        logger.warning(
            "work-index entry failed validation during phase update",
            extra={"request-id": request_id, "reason": entry.reason_code},
        )
        quarantine_work_index_entry(service_root, path, reason_code=entry.reason_code)
        return False

    if entry.phase != from_phase:
        raise AudiaGenticError(
            code="CON-AGW-104",
            kind="agents",
            message="work-index phase mismatch on update",
            details={
                "request-id": request_id,
                "expected-from-phase": from_phase,
                "actual-phase": entry.phase,
            },
        )

    # Owner fencing: once ownership is established (claimed), subsequent
    # transitions require the same owner epoch.
    if from_phase in ("claimed", "running"):
        stored_epoch = entry.owner_epoch
        if stored_epoch and owner_epoch and stored_epoch != owner_epoch:
            raise AudiaGenticError(
                code="CON-AGW-106",
                kind="agents",
                message="work-index owner-epoch mismatch on phase transition",
                details={
                    "request-id": request_id,
                    "stored-owner-epoch": stored_epoch,
                    "caller-owner-epoch": owner_epoch,
                },
            )

    legal = _PHASE_LEGAL_TRANSITIONS.get(from_phase)
    if to_phase not in (legal or frozenset()):
        raise AudiaGenticError(
            code="CON-AGW-105",
            kind="agents",
            message="illegal work-index phase transition",
            details={
                "request-id": request_id,
                "from-phase": from_phase,
                "to-phase": to_phase,
                "legal-targets": sorted(legal or []),
            },
        )

    updated = dict(raw)
    updated["phase"] = to_phase
    if to_phase == "claimed" and owner_epoch:
        updated["owner-epoch"] = owner_epoch
        updated["claimed-at"] = now_iso_z()

    atomic_write_json(path, updated)
    return True


def clear_work_index_entry(
    service_root: Path,
    request_id: str,
) -> bool:
    """Remove a work-index entry. Never raises. Returns True if the entry existed."""
    path = _entry_path(service_root, request_id)
    if not path.exists():
        return False
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        logger.warning(
            "failed to clear work-index entry (non-fatal)",
            extra={"request-id": request_id},
        )
        return False


def recover_work_index_entries(
    service_root: Path,
    *,
    live_owner_epoch: str,
) -> tuple[list[WorkIndexEntry], int]:
    """Read all work-index entries for recovery.

    Returns (valid_entries, quarantined_count).  Malformed entries are quarantined.
    """
    idx_dir = _index_dir(service_root)
    if not idx_dir.exists():
        return [], 0

    valid: list[WorkIndexEntry] = []
    quarantined = 0

    for entry_path in sorted(idx_dir.glob("req_*.json")):
        raw = _read_raw_entry(entry_path, service_root=service_root)
        if raw is None:
            quarantined += 1
            continue

        result = validate_work_index_entry(raw)
        if isinstance(result, InvalidEntry):
            quarantine_work_index_entry(service_root, entry_path, reason_code=result.reason_code)
            quarantined += 1
            continue

        valid.append(result)

    return valid, quarantined


def clear_expired_quarantine_entries(
    service_root: Path,
    *,
    max_age_seconds: float = 7 * 24 * 3600,  # 7 days default
) -> int:
    """Remove quarantine entries older than *max_age_seconds*.

    Uses filesystem mtime to determine age.  Only touches files in the
    quarantine subdirectory — active work-index entries are never deleted.

    Returns the number of entries removed.  Never raises; I/O errors for
    individual files are logged and skipped.
    """
    qdir = _quarantine_dir(service_root)
    if not qdir.exists():
        return 0

    now_epoch = now_utc_epoch_s()
    removed = 0

    for entry_path in sorted(qdir.glob("*.json")):
        try:
            mtime = os.stat(str(entry_path)).st_mtime
            age_seconds = now_epoch - mtime
            if age_seconds > max_age_seconds:
                entry_path.unlink()
                removed += 1
                logger.debug(
                    "removed expired quarantine entry",
                    extra={
                        "entry": entry_path.name,
                        "age_seconds": age_seconds,
                        "max_age_seconds": max_age_seconds,
                    },
                )
        except OSError:
            logger.warning(
                "failed to remove quarantine entry (non-fatal)",
                extra={"entry": entry_path.name},
            )

    return removed


def clear_stale_terminal_index(
    service_root: Path,
    request_id: str,
) -> None:
    """Best-effort removal of a work-index entry for a terminalized request.

    This is the safe cleanup path: never raises to the caller, so terminal state
    transitions remain durable even if the index file is locked or corrupted.
    If the entry is malformed, it is quarantined rather than deleted.
    """
    path = _entry_path(service_root, request_id)
    if not path.exists():
        return

    raw = _read_raw_entry(path, service_root=service_root)
    if raw is None:
        return  # already quarantined by _read_raw_entry

    result = validate_work_index_entry(raw)
    if isinstance(result, InvalidEntry):
        quarantine_work_index_entry(service_root, path, reason_code=result.reason_code)
        return

    try:
        path.unlink(missing_ok=True)
    except OSError:
        quarantine_work_index_entry(service_root, path, reason_code="cleanup-failed")
