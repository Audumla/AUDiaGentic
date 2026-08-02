"""AS49: explicit resume-after-death eligibility checks and idempotency.

Pure validation (`validate_resume_eligibility`) plus a small idempotency
record scoped to one source session (`agents_paths.gateway_session_resume_*`)
so a repeated client resume request with the same control id returns the
original result instead of creating a second successor generation.

Deliberately NOT the full two-phase reservation algorithm
`agents_gateway_store._admission.admit_record` uses (index-lookup +
intent-redigest-against-persisted-target before ANY dispatch begins) — this
is a simpler check-then-act version. It closes the common case (a client
retries after a timeout/dropped response) but does not fully protect two
concurrent requests with the same control id racing past the initial lookup
before either has written its result. Whoever hardens AS49 for the
shared-service architecture (SH04+) should either lift the two-phase
reservation pattern from `_admission.py` here, or fold resume idempotency
into that module directly. Flagged, not fixed, per this session's scope.

Error codes (AGW component, -110 and up; see agents_gateway_session_bindings.py
for the -09x/-10x band already in use):
    CON-AGW-110 — source session is not terminal
    RES-AGW-111 — source session has no usable provider binding
    UNS-AGW-112 — resolved surface does not support resume-by-ref
    VER-AGW-113 — surface id or ref namespace incompatible with the source binding
    CON-AGW-114 — identity context fingerprint unknown or mismatched
    CON-AGW-115 — execution context fingerprint unknown or mismatched
    CON-AGW-116 — idempotent replay of a request that previously failed
    UNS-AGW-117 — surface declares resume-by-ref but evidence.validated is False
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_gateway_session_bindings import (
    DEFAULT_EXECUTION_CONTEXT,
    DEFAULT_IDENTITY_CONTEXT,
)
from audiagentic.components.agents.agents_gateway_store import hash_idempotency_key
from audiagentic.components.agents.agents_paths import (
    gateway_session_resume_idempotency_path,
    gateway_session_resume_lock_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.session_surface import (
    ResolvedSessionSurface,
    SessionIdentityOperation,
)

ERR_SOURCE_NOT_TERMINAL = "CON-AGW-110"
ERR_STALE_OR_MISSING_BINDING = "RES-AGW-111"
ERR_UNSUPPORTED_CAPABILITY = "UNS-AGW-112"
ERR_VERSION_OR_REF_INCOMPATIBLE = "VER-AGW-113"
ERR_IDENTITY_MISMATCH = "CON-AGW-114"
ERR_EXECUTION_CONTEXT_MISMATCH = "CON-AGW-115"
ERR_IDEMPOTENT_REPLAY_OF_FAILURE = "CON-AGW-116"
# AS29's declaration schema only requires evidence.validated=True for
# controls/content_channels (session_surface_declarations.py rule 2) — it
# never gates identity_operations (open/attach-existing/resume-by-ref/
# discover) the same way, in either the old O-ladder model or AS67's
# ValidationEvidence collapse. A YAML can legally declare
# resume-by-ref: supported with evidence.validated=False. Resume is the one
# operation where treating an unproven capability as real is worst, so this
# module enforces evidence.validated=True itself rather than trusting the
# identity_operations flag alone (defense in depth, not a schema change).
ERR_UNVALIDATED_SURFACE = "UNS-AGW-117"


def validate_resume_eligibility(
    *,
    source_session_id: str,
    source_state: str,
    source_binding: dict[str, Any] | None,
    surface: ResolvedSessionSurface,
    identity_context_fingerprint: str | None,
    execution_context_fingerprint: str | None,
) -> dict[str, Any]:
    """Validate an explicit resume request. Returns the source binding on
    success. Pure — no I/O, no provider dispatch. Raises AudiaGenticError for
    every distinct AS49 rejection reason (never a generic catch-all)."""
    if source_state not in session_store.SESSION_TERMINAL_STATES:
        raise AudiaGenticError(
            code=ERR_SOURCE_NOT_TERMINAL,
            kind="agents",
            message="explicit resume requires a terminal source session",
            details={"session-id": source_session_id, "state": source_state},
        )
    if not isinstance(source_binding, dict) or not source_binding.get("provider-session-ref"):
        raise AudiaGenticError(
            code=ERR_STALE_OR_MISSING_BINDING,
            kind="agents",
            message="source session has no usable provider binding to resume",
            details={"session-id": source_session_id},
        )
    if not surface.identity.operation_supported(SessionIdentityOperation.RESUME_BY_REF):
        raise AudiaGenticError(
            code=ERR_UNSUPPORTED_CAPABILITY,
            kind="agents",
            message="resolved session surface does not support resume-by-ref",
            details={
                "provider-id": source_binding.get("provider-id"),
                "surface-id": source_binding.get("surface-id"),
            },
        )
    if not surface.validation.evidence.validated:
        raise AudiaGenticError(
            code=ERR_UNVALIDATED_SURFACE,
            kind="agents",
            message=(
                "resolved session surface declares resume-by-ref but its "
                "evidence is not validated — refusing to treat an unproven "
                "capability claim as real"
            ),
            details={
                "provider-id": source_binding.get("provider-id"),
                "surface-id": source_binding.get("surface-id"),
            },
        )
    if surface.ref.surface_id != source_binding.get("surface-id"):
        raise AudiaGenticError(
            code=ERR_VERSION_OR_REF_INCOMPATIBLE,
            kind="agents",
            message="current surface id does not match the source binding's surface",
            details={
                "session-id": source_session_id,
                "source-surface-id": source_binding.get("surface-id"),
                "resolved-surface-id": surface.ref.surface_id,
            },
        )
    current_ref_namespace = surface.identity.mapping_facts.ref_namespace
    source_ref_namespace = source_binding.get("ref-namespace")
    if source_ref_namespace and current_ref_namespace != source_ref_namespace:
        raise AudiaGenticError(
            code=ERR_VERSION_OR_REF_INCOMPATIBLE,
            kind="agents",
            message="current surface ref namespace does not match the source binding's ref namespace",
            details={
                "session-id": source_session_id,
                "source-ref-namespace": source_ref_namespace,
                "resolved-ref-namespace": current_ref_namespace,
            },
        )
    stored_identity_fp = source_binding.get("identity-context-fingerprint")
    if (
        not identity_context_fingerprint
        or not stored_identity_fp
        or stored_identity_fp == DEFAULT_IDENTITY_CONTEXT
        or identity_context_fingerprint != stored_identity_fp
    ):
        raise AudiaGenticError(
            code=ERR_IDENTITY_MISMATCH,
            kind="agents",
            message="provider identity context fingerprint is unknown or does not match the source binding",
            details={"session-id": source_session_id},
        )
    stored_execution_fp = source_binding.get("execution-context-fingerprint")
    if (
        not execution_context_fingerprint
        or not stored_execution_fp
        or stored_execution_fp == DEFAULT_EXECUTION_CONTEXT
        or execution_context_fingerprint != stored_execution_fp
    ):
        raise AudiaGenticError(
            code=ERR_EXECUTION_CONTEXT_MISMATCH,
            kind="agents",
            message="execution context fingerprint is unknown or does not match the source binding",
            details={"session-id": source_session_id},
        )
    return source_binding


# ── Idempotency (see module docstring for the known concurrency gap) ───────


def lookup_resume_attempt(
    project_root: Path,
    source_session_id: str,
    control_id: str,
) -> dict[str, Any] | None:
    """Return a previously recorded attempt for this (source, control-id), or None."""
    path = gateway_session_resume_idempotency_path(project_root, source_session_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return None
    entry = entries.get(hash_idempotency_key(control_id))
    return entry if isinstance(entry, dict) else None


def record_resume_attempt(
    project_root: Path,
    source_session_id: str,
    control_id: str,
    *,
    outcome: str,
    new_session_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    """Persist the outcome of a resume attempt, keyed by hashed control id.

    ``outcome`` is "succeeded" or "failed". Never raises — a failure to
    record idempotency state must not mask the real resume outcome; the
    caller has already committed (or failed) the actual resume by this point.
    """
    try:
        with StartupLock(gateway_session_resume_lock_path(project_root, source_session_id)):
            path = gateway_session_resume_idempotency_path(project_root, source_session_id)
            payload: dict[str, Any] = {"contract-version": "v1", "entries": {}}
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
                        payload = loaded
                except (OSError, ValueError):
                    pass
            payload["entries"][hash_idempotency_key(control_id)] = {
                "outcome": outcome,
                "new-session-id": new_session_id,
                "error-code": error_code,
                "error-message": error_message,
                "recorded-at": now_iso_z(),
            }
            atomic_write_json(path, payload)
    except OSError:
        import logging

        logging.getLogger(__name__).warning(
            "failed to persist resume idempotency record",
            extra={"session-id": source_session_id},
            exc_info=True,
        )
