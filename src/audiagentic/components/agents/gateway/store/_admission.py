"""Admission-side operations for the gateway store (SH18).

Owns idempotency key reservation, record admission, and the active-work
tracking functions. Imports _records for write_record/read_record/list_records
and _shared for constants — one-way edges only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_idempotency_index_path,
    gateway_root,
)
from audiagentic.components.agents.gateway.queue.work_index import (
    write_work_index_entry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, read_json_with_retry
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


def count_active_work(service_root: Path) -> int:
    """Count valid durable non-terminal work across all gateway projects."""
    count = 0
    active_root = service_root / _shared.ACTIVE_WORK_DIR
    if not active_root.exists():
        return 0
    for path in active_root.glob("req_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            project_value = payload.get("project-root")
            request_id = payload.get("request-id")
            if not isinstance(project_value, str) or not isinstance(request_id, str):
                continue
            record = _records.read_record(Path(project_value), request_id)
        except (OSError, ValueError, AudiaGenticError):
            continue
        if record.get("state") in {"queued", "running"}:
            count += 1
    return count


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
        # Automatically allocated gateway-session IDs group a request but do
        # not alter its execution intent. Only an explicit continuation ID is
        # semantically significant for an idempotency replay.
        "continuation-session-id": record.get("continuation-session-id"),
        "provider-transport-kind": record.get("provider-transport-kind"),
        "session-keep-alive": record.get("session-keep-alive"),
        "session-idle-timeout-seconds": record.get("session-idle-timeout-seconds"),
        "session-max-lifetime-seconds": record.get("session-max-lifetime-seconds"),
    }
    descriptor = record.get("node-admission")
    if record.get("node-placement") is not None or descriptor is not None:
        # Ordinary requests keep the historical encoded bytes exactly. A node
        # target is execution intent, not a second idempotency namespace.
        intent["node-placement"] = record.get("node-placement")
        intent["node-admission"] = (
            {key: descriptor[key] for key in ("version", "server-id", "semantic", "policy")}
            if descriptor is not None else None
        )
        if descriptor is not None and "source-workspace" in descriptor:
            intent["node-admission"]["source-workspace"] = descriptor["source-workspace"]
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
    on_admitted: Callable[[dict[str, Any]], None] | None = None,
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
    candidate = deepcopy(payload)
    if candidate.get("node-placement") is not None:
        from ..node.admission_contract import NodeAdmissionDescriptor

        if candidate.get("contract-version") != _shared._CONTRACT_VERSION:
            raise AudiaGenticError(code="VAL-AGW-002", kind="agents", message="Fresh node admission requires the current record contract")
        descriptor = NodeAdmissionDescriptor.from_mapping(candidate.get("node-admission"))
        if descriptor.source_workspace is None:
            raise AudiaGenticError(code="VAL-AGW-002", kind="agents", message="Fresh node admission requires caller workspace identity")
        if descriptor.policy.profile_id != candidate.get("execution-profile-id"):
            raise AudiaGenticError(code="VAL-AGW-002", kind="agents", message="Node admission profile mismatch")
        candidate["node-admission"] = descriptor.to_mapping()
    elif candidate.get("node-admission") is not None:
        raise AudiaGenticError(code="VAL-AGW-002", kind="agents", message="Node descriptor requires sealed placement")
    candidate = _records._validate(candidate, code="VAL-AGW-002")
    candidate["idempotency-key"] = key_digest
    intent_digest = _intent_digest(candidate)
    index_path = gateway_idempotency_index_path(project_root, key_digest)
    sequence_path = gateway_root(project_root) / "enqueue-sequence.json"
    # A missing sequence file (first provider-session admission, or recovery
    # from a lost file) forces a full project record scan to reconstruct the
    # next ordinal. Do that scan before taking the admission lock: it is
    # read-only, and running it while holding the lock would block every
    # other admission in the project for as long as the scan takes.
    # This pre-lock value is only safe to trust under the lock because
    # nothing in this codebase ever deletes sequence_path once written --
    # grep for "enqueue-sequence" before weakening that invariant, since a
    # delete-then-recreate race would let a stale pre-lock scan assign an
    # already-used ordinal.
    fallback_ordinal = None
    if candidate.get("provider-transport-kind") == "provider-session" and not sequence_path.exists():
        fallback_ordinal = max(
            (r["enqueue-ordinal"] for r in _records.list_records(project_root)
             if type(r.get("enqueue-ordinal")) is int), default=0,
        )

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
        if candidate.get("provider-transport-kind") == "provider-session":
            try:
                previous = read_json_with_retry(sequence_path)
                if type(previous) is not int or previous < 0:
                    raise ValueError("invalid gateway enqueue sequence")
            except FileNotFoundError:
                # The pre-lock scan above is only a hint, reused here rather
                # than rescanning under the lock. It stays correct only
                # because nothing deletes sequence_path once this function
                # writes it: a concurrent admitter racing for the same
                # missing file can only win by acquiring this same lock
                # first, and doing so always (over)writes sequence_path
                # before releasing it -- so reaching this branch at all
                # means no admitter has won that race since our scan ran.
                previous = fallback_ordinal if fallback_ordinal is not None else max(
                    (r["enqueue-ordinal"] for r in _records.list_records(project_root)
                     if type(r.get("enqueue-ordinal")) is int), default=0,
                )
            candidate["enqueue-ordinal"] = previous + 1
            # Persist the counter first. Crash gaps are harmless; reused order
            # identities are not. The existing admission lock serializes this.
            atomic_write_json(sequence_path, previous + 1)
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
        if on_admitted is not None:
            # Memory-only registration, before another admission can publish
            # its successor. Do not dispatch or do provider I/O in this hook.
            on_admitted(candidate)
        return candidate, True


def generate_request_id(project_root: Path | str | None = None) -> str:
    """Return a new project-scoped request ID.

    The bounded project slug is an operator-facing routing hint. The random
    suffix remains the uniqueness authority and is never used as a lookup key.
    """
    slug = "project"
    if project_root is not None:
        candidate = Path(project_root).name.lower()
        candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")
        if candidate:
            slug = candidate[:24]
    return f"req_{slug}_{uuid.uuid4().hex[:12]}"
