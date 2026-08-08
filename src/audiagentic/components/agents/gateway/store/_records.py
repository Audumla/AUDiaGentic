"""Record CRUD operations for the gateway store (SH18).

Owns building, reading, writing, validating, and listing gateway request
records. Imports _shared for constants — one-way edges only.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_request_path,
    gateway_root,
    gateway_timeline_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, load_ndjson, read_text_with_retry
from audiagentic.foundation.time import now_iso_z

from . import _shared

logger = logging.getLogger(__name__)


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
    return {k: v for k, v in error.items() if k in _shared._REDACTED_ERROR_KEYS}


def build_record(
    *,
    request_id: str | None = None,
    execution_profile_id: str,
    prompt_body: str | None,
    mode: str = "async",
    timeout_seconds: float | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    session_keep_alive: bool | None = None,
    session_idle_timeout_seconds: float | None = None,
    session_max_lifetime_seconds: float | None = None,
    # SH02: ExecutionManifest fields — always present when called from the
    # envelope-wired admission boundary.
    manifest_id: str | None = None,
    context_fingerprint: str | None = None,
    prompt_digest: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    # SH07 C2: gateway profile snapshot identity — resolved at admission
    gateway_profile_id: str | None = None,
    gateway_profile_generation: str | None = None,
    gateway_profile_config_digest: str | None = None,
    gateway_execution_lane_key: str | None = None,
    resolved_provider_id: str | None = None,
    resolved_model_id: str | None = None,
    resolved_queue_limits: dict[str, int] | None = None,
    admission_policy_digest: str | None = None,
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
    # Session bounds (idle/max lifetime) are only meaningful when
    # session_keep_alive is explicitly True — that's when a lifetime policy
    # is being set. session_keep_alive=None means preserve existing behavior
    # (no new policy). session_keep_alive=False means close-after-turn if
    # quiescent (no policy to update). 0 disables that bound (RV513 —
    # remote-control sessions opt out of idle/lifetime caps); negatives
    # are invalid.
    if session_idle_timeout_seconds is not None:
        # session_keep_alive must be explicitly True for bounds to apply;
        # None means preserve existing behavior, False means close-after-turn.
        if not session_keep_alive:
            raise AudiaGenticError(
                code="VAL-AGW-059",
                kind="agents",
                message="session_idle_timeout_seconds requires session_keep_alive=true "
                        "(the timeout applies to the session's lifetime policy)",
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
        # session_keep_alive must be explicitly True for bounds to apply.
        if not session_keep_alive:
            raise AudiaGenticError(
                code="VAL-AGW-061",
                kind="agents",
                message="session_max_lifetime_seconds requires session_keep_alive=true "
                        "(the cap applies to the session's lifetime policy)",
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
        "contract-version": _shared._CONTRACT_VERSION,
        "request-id": request_id or generate_request_id(),
        "execution-profile-id": execution_profile_id,
        # SH02: prompt_body carried in-memory for dispatch; redacted before
        # persistence (write_record strips it). Only digest is persisted.
        "prompt-body": prompt_body,
        "prompt-digest": prompt_digest,
        "manifest-id": manifest_id,
        "context-fingerprint": context_fingerprint,
        "idempotency-key": idempotency_key,
        "correlation-id": correlation_id,
        # SH07 C2: gateway profile snapshot identity — resolved at admission
        "gateway-profile-id": gateway_profile_id,
        "gateway-profile-generation": gateway_profile_generation,
        "gateway-profile-config-digest": gateway_profile_config_digest,
        "gateway-execution-lane-key": gateway_execution_lane_key,
        "resolved-provider-id": resolved_provider_id,
        "resolved-model-id": resolved_model_id,
        "resolved-queue-limits": resolved_queue_limits,
        "admission-policy-digest": admission_policy_digest,
        "mode": mode,
        "timeout-seconds": timeout_seconds,
        "source": source,
        "session-id": session_id,
        "session-keep-alive": session_keep_alive,
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
        "replay-required": None,
        "replay-reason": None,
        "replayed-by-request-id": None,
        "resumed-from-request-id": None,
        "provider-id": None,
        "model-id": None,
        "output": None,
        "completion": None,
        "usage": None,
        "error": None,
        "worker-evidence": None,
        "attempts": [],
        "created-at": timestamp,
        "updated-at": timestamp,
        "started-at": None,
        "finished-at": None,
    }
    return _validate(payload, code="VAL-AGW-002")


def generate_request_id() -> str:
    """Return a new request ID (thin re-export for build_record use)."""
    from ._admission import generate_request_id as _gen
    return _gen()


def _validate(payload: dict[str, Any], *, code: str) -> dict[str, Any]:
    issues = _shared.validate_with_schema_fn(payload)
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


import json  # noqa: E402


def _migrate_v1_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Make the only supported legacy record shape explicit and forward-only."""
    migrated = dict(payload)
    migrated.setdefault("cancel-acknowledged-at", None)
    migrated.setdefault("cancel-acknowledged-by", None)
    migrated.setdefault("dispatch-service-root", None)
    if payload.get("contract-version") != "v1":
        return _validate(migrated, code="VAL-AGW-005")
    migrated.update({
        "contract-version": _shared._CONTRACT_VERSION,
        "dispatch-owner-epoch": None,
        "dispatch-claimed-at": None,
        "recovery": None,
        "replay-required": None,
        "replay-reason": None,
        "replayed-by-request-id": None,
        "resumed-from-request-id": None,
    })
    return _validate(migrated, code="VAL-AGW-005")


def _read_record_locked(project_root: Path, request_id: str) -> dict[str, Any]:
    """Read and, while the request lock is held, migrate a v1 record safely."""
    payload = _read_record_payload(project_root, request_id)
    migrated = _migrate_v1_payload(payload)
    if migrated != payload:
        atomic_write_json(gateway_request_path(project_root, request_id), _redact_for_persistence(migrated))
        _shared.record_gateway_timeline(
            project_root,
            request_id,
            "record.migrated",
            state=migrated["state"],
            attributes={
                "from-contract-version": payload.get("contract-version"),
                "to-contract-version": _shared._CONTRACT_VERSION,
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
    with _shared._request_lock(project_root, request_id):
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
        "contract-version", "request-id", "execution-profile-id", "mode", "state",
        "cancel-requested", "revision", "dispatch-owner-epoch", "dispatch-claimed-at",
        "cancel-acknowledged-at", "cancel-acknowledged-by",
        "recovery", "worker-id", "attempt-epoch", "provider-id", "model-id",
        "session-id", "session-keep-alive", "output", "completion", "usage", "error", "attempts", "created-at",
        "updated-at", "started-at", "finished-at",
        "replay-required", "replay-reason", "replayed-by-request-id", "resumed-from-request-id",
        "metadata",
        # SH07 C2: gateway profile snapshot identity — redacted (no secrets)
        "gateway-profile-id", "gateway-profile-generation", "gateway-profile-config-digest",
        "gateway-execution-lane-key", "resolved-provider-id", "resolved-model-id",
        "resolved-queue-limits", "admission-policy-digest",
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
        if not entry.is_dir() or entry.name in {"idempotency", "sessions"}:
            continue
        try:
            records.append(read_record(project_root, entry.name))
        except AudiaGenticError:
            logger.warning("skipping unreadable gateway request", extra={"request-id": entry.name}, exc_info=True)
    return records
