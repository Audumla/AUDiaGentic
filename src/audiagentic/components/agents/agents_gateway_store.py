"""Agent LLM Gateway request/result contract and persisted state store.

Owns the gateway's own record shape and lifecycle — deliberately not built on
agent_jobs.records.JobRecord (packet/workflow-profile/approvals/review-policy
do not fit a gateway request; see AG07 notes for the reuse-vs-parallel
decision). Reuses only the generic, already-shared primitives: atomic JSON
persistence (foundation.io), schema validation (foundation.contracts.schema_registry,
same "<stem>.schema.json" convention as job-record), and the workflow transition
engine (foundation.workflow) driven by this component's own workflows.yaml.
"""
from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_request_path,
    gateway_root,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import (
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)

logger = logging.getLogger(__name__)

_SCHEMA_STEM = "agent-llm-record"
_WORKFLOW = load_workflow(Path(__file__).with_name("workflows.yaml"), "gateway-request")
TERMINAL_STATES: set[str] = set(states_in_set(_WORKFLOW, "terminal"))

_REDACTED_ERROR_KEYS = {"code", "message", "kind"}

_request_locks: dict[str, threading.Lock] = {}
_request_locks_guard = threading.Lock()


def _request_lock(request_id: str) -> threading.Lock:
    """Per-request lock guarding read-modify-write record mutations.

    transition_record/mark_cancel_requested/append_attempt all read the
    current record, mutate a copy, then write the whole thing back — with no
    coordination, a cancel arriving concurrently with a dispatch worker's
    attempt/transition write is a lost-update race (whichever write lands
    last silently discards the other's change). RV31 finding.

    Lock objects are cheap (~56 bytes) and intentionally never removed —
    same pragmatic per-process-lifetime tradeoff already accepted for
    GatewayQueueManager._profiles (RV25).
    """
    with _request_locks_guard:
        lock = _request_locks.get(request_id)
        if lock is None:
            lock = threading.Lock()
            _request_locks[request_id] = lock
        return lock


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
    fallback_profile_ids: list[str] | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a new gateway request record in the initial 'queued' state.

    The single choke point for record construction — validating here (rather
    than only in agents_gateway_api) catches malformed requests from every
    caller, including any future direct callers of this module (RV30).
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
    if fallback_profile_ids is not None and (
        not isinstance(fallback_profile_ids, list)
        or not all(isinstance(item, str) for item in fallback_profile_ids)
    ):
        raise AudiaGenticError(
            code="VAL-AGW-009",
            kind="agents",
            message="fallback_profile_ids must be a list of strings",
            details={"fallback_profile_ids": fallback_profile_ids},
        )
    timestamp = now_iso_z()
    payload: dict[str, Any] = {
        "contract-version": "v1",
        "request-id": request_id or generate_request_id(),
        "agent-profile-id": agent_profile_id,
        "prompt-body": prompt_body,
        "mode": mode,
        "timeout-seconds": timeout_seconds,
        "fallback-profile-ids": list(fallback_profile_ids or []),
        "source": source,
        "metadata": dict(metadata or {}),
        "state": "queued",
        "cancel-requested": False,
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
    atomic_write_json(target, payload)
    return target


def read_record(project_root: Path, request_id: str) -> dict[str, Any]:
    import json

    path = gateway_request_path(project_root, request_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    return _validate(payload, code="VAL-AGW-005")


def list_records(project_root: Path) -> list[dict[str, Any]]:
    root = gateway_root(project_root)
    if not root.exists():
        return []
    records = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
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
) -> dict[str, Any]:
    """Transition a request record to a new state and persist it.

    ``updates`` may set any of the mutable result fields (provider-id,
    model-id, output, completion, usage, error, started-at, finished-at).
    ``error`` is redacted through ``_redact_error`` before persisting.
    """
    with _request_lock(request_id):
        record = read_record(project_root, request_id)
        ensure_transition(record["state"], new_state)
        updated = dict(record)
        updated["state"] = new_state
        updated["updated-at"] = now_iso_z()
        if updates:
            for key, value in updates.items():
                updated[key.replace("_", "-")] = _redact_error(value) if key in ("error",) else value
        write_record(project_root, updated)
        return updated


def mark_cancel_requested(project_root: Path, request_id: str) -> dict[str, Any]:
    """Persist cancel-requested=true without changing state.

    Observable via read_record/wait/get_llm_request regardless of whether the
    in-process GatewayQueueManager that owns the running worker is still
    around — the flag survives independently of the in-memory cancel set.
    Idempotent.
    """
    with _request_lock(request_id):
        record = read_record(project_root, request_id)
        if record["cancel-requested"]:
            return record
        updated = dict(record)
        updated["cancel-requested"] = True
        updated["updated-at"] = now_iso_z()
        write_record(project_root, updated)
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
) -> dict[str, Any]:
    """Append an attempt entry (one per profile/provider try) without changing request state."""
    with _request_lock(request_id):
        record = read_record(project_root, request_id)
        attempts = list(record.get("attempts") or [])
        attempts.append({
            "agent-profile-id": agent_profile_id,
            "provider-id": provider_id,
            "model-id": model_id,
            "state": state,
            "error": _redact_error(error),
            "started-at": started_at or now_iso_z(),
            "finished-at": finished_at,
        })
        updated = dict(record)
        updated["attempts"] = attempts
        updated["updated-at"] = now_iso_z()
        write_record(project_root, updated)
        return updated
