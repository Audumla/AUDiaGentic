"""Admission-side operations for the gateway store (SH18).

Owns idempotency key reservation, record admission, and the active-work
tracking functions. Imports _records for write_record/read_record/list_records
and _shared for constants — one-way edges only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from collections.abc import Callable
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_idempotency_index_path,
)
from audiagentic.components.agents.gateway.queue.work_index import (
    write_work_index_entry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z

from . import _records, _shared

# Re-export from _shared so callers using store.record_gateway_timeline work
record_gateway_timeline = _shared.record_gateway_timeline

logger = logging.getLogger(__name__)


# Re-export from _shared so callers using store._request_lock work
_request_lock = _shared._request_lock
_admission_lock = _shared._admission_lock


def active_work_path(service_root: Path, request_id: str) -> Path:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return service_root / _shared.ACTIVE_WORK_DIR / f"{digest}.json"


def record_active_work(service_root: Path | None, project_root: Path, request_id: str, *, owner_epoch: str) -> None:
    if service_root is None:
        return
    payload = {
        "contract-version": "v1",
        "request-id": request_id,
        "project-root": str(project_root),
        "owner-epoch": owner_epoch,
        "recorded-at": now_iso_z(),
    }
    atomic_write_json(active_work_path(service_root, request_id), payload)


def clear_active_work(service_root: Path | None, request_id: str) -> None:
    if service_root is None:
        return
    active_work_path(service_root, request_id).unlink(missing_ok=True)


def hash_idempotency_key(idempotency_key: str) -> str:
    """Return the only form of an idempotency key allowed on disk."""
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def _intent_digest(record: dict[str, Any]) -> str:
    """Hash ONLY fields that change provider execution, never raw prompt/key data.

    Provenance (source, correlation IDs, subject metadata) is deliberately
    excluded: an identical execution intent retried with different audit
    metadata must match its original key, not raise a false CON-AGW-081
    conflict.
    """
    intent = {
        "execution-profile-id": record["execution-profile-id"],
        "context-fingerprint": record.get("context-fingerprint"),
        "prompt-digest": record.get("prompt-digest"),
        "mode": record["mode"],
        "timeout-seconds": record.get("timeout-seconds"),
        # Automatically allocated gateway-session IDs group a request but do
        # not alter its execution intent. Only an explicit continuation ID is
        # semantically significant for an idempotency replay.
        "continuation-session-id": record.get("continuation-session-id"),
        "provider-transport-kind": record.get("provider-transport-kind"),
        "session-keep-alive": record.get("session-keep-alive"),
        "session-idle-timeout-seconds": record.get("session-idle-timeout-seconds"),
        "session-max-lifetime-seconds": record.get("session-max-lifetime-seconds"),
    }
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_idempotency_index(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("discarding unreadable gateway idempotency index", extra={"index": path.name})
        return None
    if not isinstance(value, dict) or not all(
        isinstance(value.get(field), str)
        for field in ("key-digest", "intent-digest", "request-id")
    ):
        logger.warning("discarding malformed gateway idempotency index", extra={"index": path.name})
        return None
    return value


def _matching_persisted_record(
    project_root: Path, key_digest: str, intent_digest: str
) -> dict[str, Any] | None:
    matches = [
        record
        for record in _records.list_records(project_root)
        if record.get("idempotency-key") == key_digest
    ]
    if not matches:
        return None
    matching_intent = [record for record in matches if _intent_digest(record) == intent_digest]
    if len(matches) == 1 and matching_intent:
        return matching_intent[0]
    raise AudiaGenticError(
        code="CON-AGW-081",
        kind="agents",
        message="idempotency key was already used for a different gateway request",
        details={},
    )


def admit_record(
    project_root: Path,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    service_root: Path | None = None,
    before_write: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Atomically reserve an idempotency key and persist its request record.

    When *service_root* is provided, a work-index entry (phase="admitted") is
    written **before** the record is returned so recovery can discover admitted
   -but-unclaimed requests after a crash.  The index write is best-effort:
    failure logs a warning and does not invalidate admission.

    Returns ``(record, created)``. A replay returns the original persisted
    record and never reaches the queue. The index contains only digests, and
    a missing half of a record/index write is repaired deterministically while
    the same project-local admission lock is held.
    """
    key_digest = hash_idempotency_key(idempotency_key)
    candidate = dict(payload)
    candidate["idempotency-key"] = key_digest
    intent_digest = _intent_digest(candidate)
    index_path = gateway_idempotency_index_path(project_root, key_digest)

    with _admission_lock(project_root):
        index = _read_idempotency_index(index_path)
        if index is not None:
            if index["key-digest"] != key_digest:
                index_path.unlink(missing_ok=True)
                index = None
        if index is not None:
            try:
                original = _records.read_record(project_root, index["request-id"])
            except AudiaGenticError as exc:
                if exc.code != "RES-AGW-001":
                    raise
                # The process stopped after its index write but before the
                # record became durable. No raw prompt exists to revive it.
                index_path.unlink(missing_ok=True)
            else:
                # The index is only a crash-recovery accelerator.  The
                # project-local record is the durable authority, so never
                # trust a syntactically valid index without deriving intent
                # again from its referenced record.  This keeps an old or
                # externally-corrupted index from returning a request whose
                # immutable execution intent differs from the replay.
                if original.get("idempotency-key") != key_digest:
                    logger.warning(
                        "discarding gateway idempotency index with mismatched record",
                        extra={"index": index_path.name},
                    )
                    index_path.unlink(missing_ok=True)
                else:
                    persisted_intent_digest = _intent_digest(original)
                    if index["intent-digest"] != persisted_intent_digest:
                        logger.warning(
                            "repairing stale gateway idempotency index",
                            extra={"index": index_path.name},
                        )
                        atomic_write_json(index_path, {
                            "key-digest": key_digest,
                            "intent-digest": persisted_intent_digest,
                            "request-id": original["request-id"],
                        })
                    if persisted_intent_digest != intent_digest:
                        raise AudiaGenticError(
                            code="CON-AGW-081",
                            kind="agents",
                            message="idempotency key was already used for a different gateway request",
                            details={},
                        )
                    return original, False

        recovered = _matching_persisted_record(project_root, key_digest, intent_digest)
        if recovered is not None:
            atomic_write_json(index_path, {
                "key-digest": key_digest,
                "intent-digest": intent_digest,
                "request-id": recovered["request-id"],
            })
            return recovered, False

        if before_write is not None:
            before_write()
        _records.write_record(project_root, candidate)
        atomic_write_json(index_path, {
            "key-digest": key_digest,
            "intent-digest": intent_digest,
            "request-id": candidate["request-id"],
        })
        # C7: write work-index entry at admission (before return) so recovery
        # can discover admitted-but-unclaimed requests after a crash.
        if service_root is not None:
            try:
                write_work_index_entry(
                    service_root, project_root, candidate["request-id"],
                    phase="admitted",
                )
            except OSError:
                logger.warning(
                    "work-index write failed at admission (non-fatal)",
                    extra={"request-id": candidate["request-id"]},
                )
        return candidate, True


def generate_request_id() -> str:
    """Return a new request ID.

    UUID-based (not a sequential directory scan like agent-jobs' job IDs)
    because requests are created concurrently by queue workers across
    profiles — a scan-and-increment generator would race under concurrency.
    """
    return f"req_{uuid.uuid4().hex[:16]}"
