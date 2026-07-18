"""Agent LLM Gateway request/result contract and persisted state store.

Owns the gateway's own record shape and lifecycle — deliberately not built on
agent_jobs.records.JobRecord (packet/workflow-profile/approvals/review-policy
do not fit a gateway request; see AG07 notes for the reuse-vs-parallel
decision). Reuses only the generic, already-shared primitives: atomic JSON
persistence (foundation.io), schema validation (foundation.contracts.schema_registry,
same "<stem>.schema.json" convention as job-record), and the workflow transition
engine (foundation.workflow) driven by this component's own workflows.yaml.

SH02: records now carry ExecutionManifest fields (manifest_id, context_fingerprint,
prompt_digest). The raw prompt_body is NEVER persisted — only its digest survives.
The in-memory record dict may temporarily carry prompt-body for dispatch use, but
write_record redacts it before persistence.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_admission_lock_path,
    gateway_idempotency_index_path,
    gateway_request_path,
    gateway_root,
    gateway_timeline_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json, load_ndjson, read_text_with_retry
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)

logger = logging.getLogger(__name__)

_SCHEMA_STEM = "agent-llm-record"
_CONTRACT_VERSION = "v2"
_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "gateway-request")
TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

_COMPONENT_ID = "agents"
_RESOURCE_KIND = "agent-llm-gateway-request"
ACTIVE_WORK_DIR = "active-work"


def record_gateway_timeline(
    project_root: Path,
    request_id: str,
    event: str,
    *,
    state: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return record_timeline_event(
        gateway_timeline_path(project_root, request_id),
        component=_COMPONENT_ID,
        resource_kind=_RESOURCE_KIND,
        resource_id=request_id,
        event=event,
        state=state,
        attributes=attributes,
        correlation_id=(attributes or {}).get("correlation_id") or (attributes or {}).get("correlation-id"),
    )


def _request_lock(project_root: Path, request_id: str) -> StartupLock:
    """Return the foundation cross-process lock for one request record."""
    return StartupLock(gateway_request_path(project_root, request_id).with_name("mutation.lock"))


def _admission_lock(project_root: Path) -> StartupLock:
    """Serialize project-local idempotency reservation and record creation."""
    return StartupLock(gateway_admission_lock_path(project_root))


def active_work_path(service_root: Path, request_id: str) -> Path:
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return service_root / ACTIVE_WORK_DIR / f"{digest}.json"


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
    """Hash fields that can change provider execution, never raw prompt/key data."""
    intent = {
        "agent-profile-id": record["agent-profile-id"],
        "context-fingerprint": record.get("context-fingerprint"),
        "prompt-digest": record.get("prompt-digest"),
        "mode": record["mode"],
        "timeout-seconds": record.get("timeout-seconds"),
        "source": record.get("source"),
        "session-id": record.get("session-id"),
        "session-keep-alive": record.get("session-keep-alive"),
        "session-idle-timeout-seconds": record.get("session-idle-timeout-seconds"),
        "session-max-lifetime-seconds": record.get("session-max-lifetime-seconds"),
        "metadata": record.get("metadata", {}),
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
        for record in list_records(project_root)
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
) -> tuple[dict[str, Any], bool]:
    """Atomically reserve an idempotency key and persist its request record.

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
                original = read_record(project_root, index["request-id"])
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

        write_record(project_root, candidate)
        atomic_write_json(index_path, {
            "key-digest": key_digest,
            "intent-digest": intent_digest,
            "request-id": candidate["request-id"],
        })
        return candidate, True


def generate_request_id() -> str:
    """Return a new request ID.

    UUID-based (not a sequential directory scan like agent-jobs' job IDs)
    because requests are created concurrently by queue workers across
    profiles — a scan-and-increment generator would race under concurrency.
    """
    return f"req_{uuid.uuid4().hex[:16]}"


def _redact_error(error: BaseException | dict[str, Any] | None) -> dict[str, Any] | None:
    """Reduce any error to a safe {code, message, kind} summary.

    Never persists raw stdout/stderr, prompts, tokens, or exception args that
    might carry them (Standard 8 — error details must not leak sensitive data).

    Only AudiaGenticError's own ``.message`` (never ``.details``, which is
    where redaction-worthy blobs like stdout/stderr live) is trusted verbatim.
    An arbitrary BaseException's ``str(error)`` is NOT persisted — exception
    args can carry the same sensitive content (a subprocess wrapper exception
    embedding stdout, a request exception embedding a URL with a token in it)
    with none of AudiaGenticError's redaction guarantees.
    """
    if error is None:
        return None
    if isinstance(error, AudiaGenticError):
        return {"code": error.code, "message": error.message, "kind": error.kind}
    if isinstance(error, BaseException):
        return {"code": "UNKNOWN", "message": "unexpected error (see server logs)", "kind": type(error).__name__}
    return {k: v for k, v in error.items() if k in _REDACTED_ERROR_KEYS}


def build_record(
    *,
    request_id: str | None = None,
    agent_profile_id: str,
    prompt_body: str | None,
    mode: str = "async",
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool = False,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
    # SH02: ExecutionManifest fields — always present when called from the
    # envelope-wired admission boundary.
    manifest_id: str | None = None,
    context_fingerprint: str | None = None,
    prompt_digest: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Build a new gateway request record in the initial 'queued' state.

    The single choke point for record construction — validating here (rather
    than only in agents_gateway_api) catches malformed requests from every
    caller, including any future direct callers of this module (RV30).

    SH02: prompt_body is carried in the returned dict ONLY for dispatch use
    and is redacted before persistence (write_record strips it, keeping only
    prompt_digest). The manifest fields are persisted alongside the record.
    """
    if mode not in ("async", "blocking"):
        raise AudiaGenticError(
            code="VAL-AGW-001",
            kind="agents",
            message="mode must be 'async' or 'blocking'",
            details={"mode": mode},
        )
    if not prompt_body or not prompt_body.strip():
        raise AudiaGenticError(
            code="VAL-AGW-007",
            kind="agents",
            message="prompt_body is required and must not be empty",
            details={},
        )
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise AudiaGenticError(
            code="VAL-AGW-008",
            kind="agents",
            message="timeout_seconds must be positive",
            details={"timeout_seconds": timeout_seconds},
        )
    if session_id is not None and session_keep_alive:
        raise AudiaGenticError(
            code="VAL-AGW-057",
            kind="agents",
            message="session_id (continue an existing session) and session_keep_alive "
                    "(open a new one) are mutually exclusive",
            details={"session_id": session_id},
        )
    # Session bounds are fixed when the session is opened, so they are only
    # valid with keep-alive. 0 disables that bound (RV513 — remote-control
    # sessions opt out of idle/lifetime caps); negatives are invalid.
    if session_idle_timeout_seconds is not None:
        if not session_keep_alive:
            raise AudiaGenticError(
                code="VAL-AGW-059",
                kind="agents",
                message="session_idle_timeout_seconds is only valid with session_keep_alive "
                        "(the timeout is fixed when the session is opened)",
                details={},
            )
        if session_idle_timeout_seconds < 0:
            raise AudiaGenticError(
                code="VAL-AGW-059",
                kind="agents",
                message="session_idle_timeout_seconds must be positive, or 0 to disable the idle timeout",
                details={"session_idle_timeout_seconds": session_idle_timeout_seconds},
            )
    if session_max_lifetime_seconds is not None:
        if not session_keep_alive:
            raise AudiaGenticError(
                code="VAL-AGW-061",
                kind="agents",
                message="session_max_lifetime_seconds is only valid with session_keep_alive "
                        "(the cap is fixed when the session is opened)",
                details={},
            )
        if session_max_lifetime_seconds < 0:
            raise AudiaGenticError(
                code="VAL-AGW-061",
                kind="agents",
                message="session_max_lifetime_seconds must be positive, or 0 to disable the lifetime cap",
                details={"session_max_lifetime_seconds": session_max_lifetime_seconds},
            )
    timestamp = now_iso_z()
    payload: dict[str, Any] = {
        "contract-version": _CONTRACT_VERSION,
        "request-id": request_id or generate_request_id(),
        "agent-profile-id": agent_profile_id,
        # SH02: prompt_body carried in-memory for dispatch; redacted before
        # persistence (write_record strips it). Only digest is persisted.
        "prompt-body": prompt_body,
        "prompt-digest": prompt_digest,
        "manifest-id": manifest_id,
        "context-fingerprint": context_fingerprint,
        "idempotency-key": idempotency_key,
        "correlation-id": correlation_id,
        "mode": mode,
        "timeout-seconds": timeout_seconds,
        "source": source,
        "session-id": session_id,
        "session-keep-alive": bool(session_keep_alive),
        "session-idle-timeout-seconds": session_idle_timeout_seconds,
        "session-max-lifetime-seconds": session_max_lifetime_seconds,
        "metadata": dict(metadata or {}),
        "state": "queued",
        "cancel-requested": False,
        "cancel-acknowledged-at": None,
        "cancel-acknowledged-by": None,
        "revision": 0,
        "worker-id": None,
        "attempt-epoch": 0,
        "dispatch-owner-epoch": None,
        "dispatch-claimed-at": None,
        "dispatch-service-root": None,
        "recovery": None,
        "provider-id": None,
        "model-id": None,
        "output": None,
        "completion": None,
        "usage": None,
        "error": None,
        "attempts": [],
        "created-at": timestamp,
        "updated-at": timestamp,
        "started-at": None,
        "finished-at": None,
    }
    return _validate(payload, code="VAL-AGW-002")


def _validate(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
    issues = validate_with_schema(_SCHEMA_STEM, payload)
    if issues:
        raise AudiaGenticError(
            code=code,
            kind="agents",
            message="gateway request record failed schema validation",
            details={"issues": issues},
        )
    return payload


def _redact_for_persistence(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove raw prompt-body before persistence.

    SH02: the raw prompt is used for dispatch only and never persisted (design doc §5.2).
    The prompt_digest field survives; prompt-body is set to None in the persisted record.
    """
    redacted = dict(payload)
    redacted["prompt-body"] = None
    return redacted


def write_record(project_root: Path, payload: dict[str, Any]) -> Path:
    request_id = payload.get("request-id")
    if not request_id:
        raise AudiaGenticError(
            code="VAL-AGW-003",
            kind="agents",
            message="gateway request record missing request-id",
            details={},
        )
    _validate(payload, code="VAL-AGW-004")
    target = gateway_request_path(project_root, request_id)
    # SH02: redact raw prompt-body before persistence; dispatch gets it from the
    # in-memory copy passed through the queue manager.
    redacted = _redact_for_persistence(payload)
    atomic_write_json(target, redacted)
    return target


def _read_record_payload(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read JSON only; callers decide whether the record needs migration."""
    path = gateway_request_path(project_root, request_id)
    try:
        payload = json.loads(read_text_with_retry(path))
    except OSError as exc:
        raise AudiaGenticError(
            code="RES-AGW-001",
            kind="agents",
            message="gateway request not found",
            details={"request-id": request_id},
        ) from exc
    except ValueError as exc:
        logger.warning("failed to parse gateway request record", extra={"request-id": request_id}, exc_info=True)
        raise AudiaGenticError(
            code="IO-AGW-001",
            kind="agents",
            message="failed to read gateway request record",
            details={"request-id": request_id},
        ) from exc
    if not isinstance(payload, dict):
        raise AudiaGenticError(
            code="VAL-AGW-005",
            kind="agents",
            message="gateway request record failed schema validation",
            details={"issues": ["record must be an object"]},
        )
    return payload


def _migrate_v1_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Make the only supported legacy record shape explicit and forward-only."""
    migrated = dict(payload)
    migrated.setdefault("cancel-acknowledged-at", None)
    migrated.setdefault("cancel-acknowledged-by", None)
    migrated.setdefault("dispatch-service-root", None)
    if payload.get("contract-version") != "v1":
        return _validate(migrated, code="VAL-AGW-005")
    migrated.update({
        "contract-version": _CONTRACT_VERSION,
        "dispatch-owner-epoch": None,
        "dispatch-claimed-at": None,
        "recovery": None,
    })
    return _validate(migrated, code="VAL-AGW-005")


def _read_record_locked(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read and, while the request lock is held, migrate a v1 record safely."""
    payload = _read_record_payload(project_root, request_id)
    migrated = _migrate_v1_payload(payload)
    if migrated != payload:
        atomic_write_json(gateway_request_path(project_root, request_id), _redact_for_persistence(migrated))
        record_gateway_timeline(
            project_root,
            request_id,
            "record.migrated",
            state=migrated["state"],
            attributes={
                "from-contract-version": payload.get("contract-version"),
                "to-contract-version": _CONTRACT_VERSION,
            },
        )
        return migrated
    return migrated


def read_record(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read a durable request, upgrading a v1 payload under its mutation lock."""
    payload = _read_record_payload(project_root, request_id)
    if (
        payload.get("contract-version") != "v1"
        and "cancel-acknowledged-at" in payload
        and "cancel-acknowledged-by" in payload
    ):
        return _validate(payload, code="VAL-AGW-005")
    with _request_lock(project_root, request_id):
        return _read_record_locked(project_root, request_id)


def latest_transition_projection(project_root: Path, request_id: str) -> dict[str, str | None] | None:
    """Return the last durable timeline milestone without its attributes.

    Timeline attributes intentionally carry operator-only correlation and
    attempt context.  A status response needs only the durable transition
    identity, state, and timestamp, so it must never copy that free-form
    mapping into a public projection.
    """
    try:
        entries = load_ndjson(gateway_timeline_path(project_root, request_id))
    except (OSError, ValueError):
        logger.warning("failed to read gateway request timeline", extra={"request-id": request_id})
        return None
    for entry in reversed(entries):
        event = entry.get("event")
        timestamp = entry.get("timestamp")
        state = entry.get("state")
        if isinstance(event, str) and isinstance(timestamp, str) and (state is None or isinstance(state, str)):
            return {"event": event, "state": state, "timestamp": timestamp}
    return None


def project_public_status(
    record: dict[str, Any],
    *,
    latest_transition: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return safe durable status without submission secrets or prompt material."""
    visible = (
        "contract-version", "request-id", "agent-profile-id", "mode", "state",
        "cancel-requested", "revision", "dispatch-owner-epoch", "dispatch-claimed-at",
        "cancel-acknowledged-at", "cancel-acknowledged-by",
        "recovery", "worker-id", "attempt-epoch", "provider-id", "model-id",
        "session-id", "session-keep-alive", "output", "completion", "usage", "error", "attempts", "created-at",
        "updated-at", "started-at", "finished-at",
    )
    status = {field: record.get(field) for field in visible}
    status["latest-transition"] = latest_transition
    return status


def read_public_status(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read a safe request status with its bounded last transition."""
    record = read_record(project_root, request_id)
    return project_public_status(
        record,
        latest_transition=latest_transition_projection(project_root, request_id),
    )


def list_records(project_root: Path) -> list[dict[str, Any]]:
    root = gateway_root(project_root)
    if not root.exists():
        return []
    records = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name == "idempotency":
            continue
        try:
            records.append(read_record(project_root, entry.name))
        except AudiaGenticError:
            logger.warning("skipping unreadable gateway request", extra={"request-id": entry.name}, exc_info=True)
    return records


def ensure_transition(current_state: str, new_state: str) -> None:
    if not is_known_state(_WORKFLOW, current_state):
        raise AudiaGenticError(
            code="VAL-AGW-006",
            kind="agents",
            message="unknown gateway request state",
            details={"state": current_state},
        )
    if not transition_allowed(_WORKFLOW, current_state, new_state):
        raise AudiaGenticError(
            code="CON-AGW-001",
            kind="agents",
            message="illegal gateway request state transition",
            details={"from": current_state, "to": new_state},
        )


def transition_record(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    updates: dict[str, Any] | None = None,
    expected_revision: int | None = None,
    expected_dispatch_owner_epoch: str | None = None,
    expected_worker_id: str | None = None,
    expected_attempt_epoch: int | None = None,
) -> dict[str, Any]:
    """Transition a request record to a new state and persist it.

    ``updates`` may set any of the mutable result fields (provider-id,
    model-id, output, completion, usage, error, started-at, finished-at).
    ``error`` is redacted through ``_redact_error`` before persisting.
    """
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=expected_dispatch_owner_epoch,
            expected_worker_id=expected_worker_id,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        ensure_transition(record["state"], new_state)
        updated = dict(record)
        updated["state"] = new_state
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        if updates:
            for key, value in updates.items():
                updated[key.replace("_", "-")] = _redact_error(value) if key in ("error",) else value
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "state.changed",
            state=new_state,
            attributes={
                "from": record["state"],
                "to": new_state,
                "updated-keys": sorted((updates or {}).keys()),
            },
        )
        return updated


def mark_cancel_requested(project_root: Path, request_id: str) -> dict[str, Any]:
    """Persist cancel-requested=true without changing state.

    Observable via read_record/wait/get_llm_request regardless of whether the
    in-process GatewayQueueManager that owns the running worker is still
    around — the flag survives independently of the in-memory cancel set.
    Idempotent.
    """
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["cancel-requested"]:
            return record
        updated = dict(record)
        updated["cancel-requested"] = True
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "cancel.requested",
            state=updated["state"],
        )
        return updated


def acknowledge_cancel(project_root: Path, request_id: str, *, by: str) -> dict[str, Any]:
    """Record the first component that observed a cancel request.

    First writer wins so a later session/runtime acknowledgement cannot erase
    the recovery or queue evidence that actually won the race.
    """
    if not by:
        raise AudiaGenticError(
            code="VAL-AGW-086",
            kind="agents",
            message="cancel acknowledgement actor is required",
            details={},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record.get("cancel-acknowledged-by"):
            return record
        updated = dict(record)
        updated["cancel-acknowledged-at"] = now_iso_z()
        updated["cancel-acknowledged-by"] = by
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "cancel.acknowledged",
            state=updated["state"],
            attributes={"by": by},
        )
        return updated


def append_attempt(
    project_root: Path,
    request_id: str,
    *,
    agent_profile_id: str,
    provider_id: str | None,
    model_id: str | None,
    state: str,
    error: BaseException | dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    expected_dispatch_owner_epoch: str | None = None,
    expected_worker_id: str | None = None,
    expected_attempt_epoch: int | None = None,
) -> dict[str, Any]:
    """Append an attempt entry (one per profile/provider try) without changing request state."""
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=None,
            expected_dispatch_owner_epoch=expected_dispatch_owner_epoch,
            expected_worker_id=expected_worker_id,
            expected_attempt_epoch=expected_attempt_epoch,
        )
        attempts = list(record.get("attempts") or [])
        attempts.append({
            "agent-profile-id": agent_profile_id,
            "provider-id": provider_id,
            "model-id": model_id,
            "state": state,
            "error": _redact_error(error),
            "started-at": started_at or now_iso_z(),
            "finished-at": finished_at,
            "worker-id": record["worker-id"],
            "attempt-epoch": record["attempt-epoch"],
        })
        updated = dict(record)
        updated["attempts"] = attempts
        updated["updated-at"] = now_iso_z()
        updated["revision"] = record["revision"] + 1
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "attempt.recorded",
            state=record["state"],
            attributes={
                "agent-profile-id": agent_profile_id,
                "provider-id": provider_id,
                "model-id": model_id,
                "attempt-state": state,
                "attempt-count": len(attempts),
                "error": _redact_error(error),
            },
        )
        return updated


def cancel_queued_or_mark_requested(project_root: Path, request_id: str) -> dict[str, Any]:
    """Linearize cancellation with the queued-to-running dispatch boundary.

    A queue thread can remove an item from its in-memory pending deque before
    it durably claims the request.  Cancelling in that interval must make the
    queued record terminal, not merely set an intent flag that no worker can
    observe after the deque entry disappears.  Once the record is running,
    preserve the established cooperative-cancellation behaviour instead.
    """
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["state"] != "queued":
            if record["state"] == "running" and not record["cancel-requested"]:
                updated = dict(record)
                updated["cancel-requested"] = True
                updated["updated-at"] = now_iso_z()
                updated["revision"] = record["revision"] + 1
                write_record(project_root, updated)
                record_gateway_timeline(
                    project_root,
                    request_id,
                    "cancel.requested",
                    state=updated["state"],
                )
                return updated
            return record

        updated = dict(record)
        updated.update({
            "state": "cancelled",
            "cancel-requested": True,
            "cancel-acknowledged-at": now_iso_z(),
            "cancel-acknowledged-by": "queue-worker",
            "updated-at": now_iso_z(),
            "finished-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "state.changed",
            state="cancelled",
            attributes={"from": "queued", "to": "cancelled", "updated-keys": []},
        )
        return updated


def release_stale_claim(project_root: Path, request_id: str, *, stale_epoch: str) -> dict[str, Any]:
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record.get("dispatch-owner-epoch") != stale_epoch:
            raise AudiaGenticError(
                code="CON-AGW-083",
                kind="agents",
                message="gateway request dispatch ownership changed",
                details={},
            )
        if record["state"] != "queued":
            raise AudiaGenticError(
                code="CON-AGW-083",
                kind="agents",
                message="gateway request is not a stale queued claim",
                details={"state": record["state"]},
            )
        updated = dict(record)
        updated.update({
            "dispatch-owner-epoch": None,
            "dispatch-claimed-at": None,
            "dispatch-service-root": None,
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
            "recovery": {"reason": "service-restart", "outcome": "resubmit-required"},
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "dispatch.claim.released",
            state="queued",
            attributes={"stale-owner-epoch": stale_epoch},
        )
        return updated


def transition_recovered_terminal(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    error: BaseException | dict[str, Any] | None,
    stale_epoch: str,
) -> dict[str, Any]:
    if new_state not in TERMINAL_STATES:
        raise AudiaGenticError("VAL-AGW-084", "agents", "recovered transition must be terminal", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record.get("dispatch-owner-epoch") != stale_epoch:
            raise AudiaGenticError(
                code="CON-AGW-083",
                kind="agents",
                message="gateway request dispatch ownership changed",
                details={},
            )
        ensure_transition(record["state"], new_state)
        timestamp = now_iso_z()
        updated = dict(record)
        updated.update({
            "state": new_state,
            "error": _redact_error(error),
            "finished-at": timestamp,
            "dispatch-service-root": None,
            "updated-at": timestamp,
            "revision": record["revision"] + 1,
            "recovery": {"reason": "service-restart", "outcome": "resubmit-required"},
        })
        if updated.get("cancel-requested") and not updated.get("cancel-acknowledged-by"):
            updated["cancel-acknowledged-at"] = timestamp
            updated["cancel-acknowledged-by"] = "recovery"
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "recovery.terminalized",
            state=new_state,
            attributes={"stale-owner-epoch": stale_epoch},
        )
        return updated


def start_attempt(project_root: Path, request_id: str, worker_id: str) -> dict[str, Any]:
    """Atomically assign a new worker/attempt epoch and enter running state."""
    if not worker_id:
        raise AudiaGenticError(
            code="VAL-AGW-070",
            kind="agents",
            message="worker_id is required",
            details={},
        )
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        ensure_transition(record["state"], "running")
        updated = dict(record)
        updated.update({
            "state": "running",
            "worker-id": worker_id,
            "attempt-epoch": record["attempt-epoch"] + 1,
            "started-at": now_iso_z(),
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root,
            request_id,
            "attempt.started",
            state="running",
            attributes={
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
                "context-fingerprint": updated.get("context-fingerprint"),
            },
        )
        return updated


def claim_dispatch(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    expected_revision: int,
    service_root: Path | None = None,
) -> dict[str, Any]:
    """Fence a queued request to one service owner before it starts work.

    Claiming is intentionally separate from starting a provider attempt: a
    service crash between them stays visibly queued-but-claimed, rather than
    looking as though execution definitely began.
    """
    if not owner_epoch:
        raise AudiaGenticError("VAL-AGW-083", "agents", "dispatch owner epoch is required", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        if record["revision"] != expected_revision:
            raise AudiaGenticError(
                "CON-AGW-071", "agents", "gateway request revision changed",
                {"expected": expected_revision, "actual": record["revision"]},
            )
        if record["state"] != "queued":
            raise AudiaGenticError("CON-AGW-083", "agents", "gateway request is not available for dispatch claim", {})
        current_owner = record.get("dispatch-owner-epoch")
        if current_owner not in (None, owner_epoch):
            raise AudiaGenticError("CON-AGW-083", "agents", "gateway request dispatch ownership changed", {})
        if current_owner == owner_epoch:
            record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
            return record
        updated = dict(record)
        updated.update({
            "dispatch-owner-epoch": owner_epoch,
            "dispatch-claimed-at": now_iso_z(),
            "dispatch-service-root": str(service_root) if service_root is not None else None,
            "updated-at": now_iso_z(),
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_active_work(service_root, project_root, request_id, owner_epoch=owner_epoch)
        record_gateway_timeline(
            project_root, request_id, "dispatch.claimed", state="queued",
            attributes={"dispatch-owner-epoch": owner_epoch},
        )
        return updated


def start_owned_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Start an attempt only from a current owner claim and exact revision."""
    if not owner_epoch or not worker_id:
        raise AudiaGenticError("VAL-AGW-070", "agents", "owner epoch and worker_id are required", {})
    with _request_lock(project_root, request_id):
        record = _read_record_locked(project_root, request_id)
        _check_expected_identity(
            record,
            expected_revision=expected_revision,
            expected_dispatch_owner_epoch=owner_epoch,
            expected_worker_id=None,
            expected_attempt_epoch=None,
        )
        ensure_transition(record["state"], "running")
        updated = dict(record)
        timestamp = now_iso_z()
        updated.update({
            "state": "running", "worker-id": worker_id,
            "attempt-epoch": record["attempt-epoch"] + 1,
            "started-at": timestamp, "updated-at": timestamp,
            "revision": record["revision"] + 1,
        })
        write_record(project_root, updated)
        record_gateway_timeline(
            project_root, request_id, "attempt.started", state="running",
            attributes={
                "dispatch-owner-epoch": owner_epoch,
                "worker-id": worker_id,
                "attempt-epoch": updated["attempt-epoch"],
                "context-fingerprint": updated.get("context-fingerprint"),
            },
        )
        return updated


def append_owned_attempt(
    project_root: Path,
    request_id: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """Append evidence only while the same service/worker/attempt still owns it."""
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    return append_attempt(
        project_root, request_id,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
        **kwargs,
    )


def transition_owned_terminal(
    project_root: Path,
    request_id: str,
    new_state: str,
    *,
    owner_epoch: str,
    worker_id: str,
    attempt_epoch: int,
    updates: dict[str, Any] | None = None,
    service_root: Path | None = None,
) -> dict[str, Any]:
    """Write a terminal result only with the complete dispatch fence."""
    if new_state not in TERMINAL_STATES:
        raise AudiaGenticError("VAL-AGW-084", "agents", "owned transition must be terminal", {})
    _require_owned_identity(owner_epoch, worker_id, attempt_epoch)
    updated = transition_record(
        project_root, request_id, new_state, updates=updates,
        expected_dispatch_owner_epoch=owner_epoch,
        expected_worker_id=worker_id,
        expected_attempt_epoch=attempt_epoch,
    )
    service_root_for_cleanup = service_root
    if service_root_for_cleanup is None:
        stored_root = updated.get("dispatch-service-root")
        service_root_for_cleanup = Path(stored_root) if isinstance(stored_root, str) and stored_root else None
    clear_active_work(service_root_for_cleanup, request_id)
    return updated


def _require_owned_identity(owner_epoch: str | None, worker_id: str | None, attempt_epoch: int) -> None:
    """Reject the ``None`` sentinel before it can weaken an owned mutation."""
    if not owner_epoch or not worker_id or attempt_epoch < 1:
        raise AudiaGenticError(
            "VAL-AGW-085",
            "agents",
            "owned mutation requires dispatch owner, worker, and attempt identity",
            {},
        )


def _check_expected_identity(
    record: dict[str, Any],
    *,
    expected_revision: int | None,
    expected_dispatch_owner_epoch: str | None,
    expected_worker_id: str | None,
    expected_attempt_epoch: int | None,
) -> None:
    if expected_revision is not None and record["revision"] != expected_revision:
        raise AudiaGenticError(
            code="CON-AGW-071",
            kind="agents",
            message="gateway request revision changed",
            details={"expected": expected_revision, "actual": record["revision"]},
        )
    if (
        expected_dispatch_owner_epoch is not None
        and record.get("dispatch-owner-epoch") != expected_dispatch_owner_epoch
    ):
        raise AudiaGenticError(
            code="CON-AGW-083",
            kind="agents",
            message="gateway request dispatch ownership changed",
            details={},
        )
    if expected_worker_id is not None and record["worker-id"] != expected_worker_id:
        raise AudiaGenticError(
            code="CON-AGW-072",
            kind="agents",
            message="gateway request worker ownership changed",
            details={},
        )
    if expected_attempt_epoch is not None and record["attempt-epoch"] != expected_attempt_epoch:
        raise AudiaGenticError(
            code="CON-AGW-073",
            kind="agents",
            message="gateway request attempt epoch changed",
            details={"expected": expected_attempt_epoch, "actual": record["attempt-epoch"]},
        )
