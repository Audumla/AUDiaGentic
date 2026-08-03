"""Durable AG to provider session binding index (AS30).

The protected session record owns the raw provider ref. This module owns the
project-local index over a redacted hash so callers never use the ref as a path
or public identifier.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_session_binding_index_path,
    gateway_session_binding_lock_path,
    gateway_sessions_root,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.transports.session_binding import (
    BindingRelation,
    SessionOwnership,
)

DEFAULT_SURFACE_ID = "acp-session"
DEFAULT_REF_NAMESPACE = "provider-session-ref"
DEFAULT_IDENTITY_CONTEXT = "unknown"
DEFAULT_EXECUTION_CONTEXT = "unknown"


def provider_ref_key(
    *,
    provider_id: str | None,
    surface_id: str | None,
    ref_namespace: str | None,
    identity_context_fingerprint: str | None,
    provider_session_ref: str,
) -> str:
    hasher = hashlib.sha256()
    for part in (
        provider_id or "unknown-provider",
        surface_id or DEFAULT_SURFACE_ID,
        ref_namespace or DEFAULT_REF_NAMESPACE,
        identity_context_fingerprint or DEFAULT_IDENTITY_CONTEXT,
        provider_session_ref,
    ):
        # Length-prefixed fields: provider refs are opaque and may contain any
        # byte (including NUL), so delimiter-based encoding would be ambiguous.
        encoded = part.encode("utf-8")
        hasher.update(str(len(encoded)).encode("ascii"))
        hasher.update(b":")
        hasher.update(encoded)
    return hasher.hexdigest()


def build_binding(
    *,
    provider_id: str | None,
    provider_session_ref: str | None,
    generation: int = 1,
    relation: BindingRelation = BindingRelation.OPENED,
    ownership: SessionOwnership = SessionOwnership.OWNED,
    surface_id: str | None = None,
    surface_version: str | None = None,
    ref_namespace: str | None = None,
    predecessor_binding_id: str | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    if provider_session_ref is None:
        return None
    key = provider_ref_key(
        provider_id=provider_id,
        surface_id=surface_id,
        ref_namespace=ref_namespace,
        identity_context_fingerprint=identity_context_fingerprint,
        provider_session_ref=provider_session_ref,
    )
    return {
        "binding-id": f"sbind_{uuid.uuid4().hex[:16]}",
        "generation": generation,
        "provider-id": provider_id,
        "surface-id": surface_id or DEFAULT_SURFACE_ID,
        "surface-version": surface_version,
        "ref-namespace": ref_namespace or DEFAULT_REF_NAMESPACE,
        "provider-session-ref": provider_session_ref,
        "provider-ref-key": key,
        "relation": relation.value,
        "ownership": ownership.value,
        "predecessor-binding-id": predecessor_binding_id,
        "identity-context-fingerprint": identity_context_fingerprint or DEFAULT_IDENTITY_CONTEXT,
        "execution-context-fingerprint": execution_context_fingerprint or DEFAULT_EXECUTION_CONTEXT,
        "created-at": now_iso_z(),
    }


def build_migrated_v1_binding(
    *,
    session_id: str,
    provider_id: str | None,
    provider_session_ref: str | None,
    created_at: str,
) -> dict[str, Any] | None:
    """Build the v2 binding for a legacy v1 record, deterministically.

    A v1 record is only migrated in memory on read, so every field must be a
    pure function of the legacy record: re-reading the same file must yield
    the identical binding (identity, timestamp, key). No random binding-id,
    no read-time clock.
    """
    if provider_session_ref is None:
        return None
    seed = hashlib.sha256()
    for part in ("v1-migration", session_id, provider_id or "", provider_session_ref):
        encoded = part.encode("utf-8")
        seed.update(str(len(encoded)).encode("ascii"))
        seed.update(b":")
        seed.update(encoded)
    key = provider_ref_key(
        provider_id=provider_id,
        surface_id=None,
        ref_namespace=None,
        identity_context_fingerprint=None,
        provider_session_ref=provider_session_ref,
    )
    return {
        "binding-id": f"sbind_{seed.hexdigest()[:16]}",
        "generation": 1,
        "provider-id": provider_id,
        "surface-id": DEFAULT_SURFACE_ID,
        "surface-version": None,
        "ref-namespace": DEFAULT_REF_NAMESPACE,
        "provider-session-ref": provider_session_ref,
        "provider-ref-key": key,
        "relation": BindingRelation.OPENED.value,
        "ownership": SessionOwnership.OWNED.value,
        "predecessor-binding-id": None,
        "identity-context-fingerprint": DEFAULT_IDENTITY_CONTEXT,
        "execution-context-fingerprint": DEFAULT_EXECUTION_CONTEXT,
        "created-at": created_at,
    }


def public_binding_projection(binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if not binding:
        return None
    key = str(binding.get("provider-ref-key") or "")
    return {
        "binding-id": binding.get("binding-id"),
        "generation": binding.get("generation"),
        "provider-id": binding.get("provider-id"),
        "surface-id": binding.get("surface-id"),
        "surface-version": binding.get("surface-version"),
        "relation": binding.get("relation"),
        "ownership": binding.get("ownership"),
        "predecessor-binding-id": binding.get("predecessor-binding-id"),
        "provider-ref-key-prefix": key[:12] if key else None,
    }


def project_public_session(record: dict[str, Any]) -> dict[str, Any]:
    """Project a session record to its public shape: redacted binding, no
    protected provider refs. Used by both list_execution_sessions and close_execution_session
    so public surfaces are consistent (AS35)."""
    projected = dict(record)
    projected["binding"] = public_binding_projection(record.get("binding"))
    projected.pop("provider-session-ref", None)
    return projected


# AS33: capability-snapshot projection helpers.

# Keys that must never reach public diagnostics: provider refs, raw payloads,
# prompts, outputs, and tool arguments are not capability facts.
_CAPABILITIES_FORBIDDEN_KEYS = frozenset(
    {
        "provider-session-ref",
        "raw-payload",
        "prompt",
        "output",
        "tool-args",
        "tool_args",
        "tool-calls",
        "tool_calls",
        "tool-arguments",
        "provider-surface",
        "surface-ref",
        "native-ref",
    }
)

# Whitelist of safe capability-snapshot keys (enum/id/scalar only).
_CAPABILITIES_SAFE_KEYS = frozenset(
    {
        "surface-id",
        "surface-version",
        "declared-controls",
        "observation-mechanism",
        "observation-source",
        "supported-statuses",
        "evidence-tier",
    }
)

# Recognized session-record keys for the capability snapshot.
_CAPABILITIES_SNAPSHOT_KEYS = (
    "capability-snapshot",
    "resolved-capabilities",
    "session-capabilities",
)


def _is_safe_scalar(value: Any) -> bool:
    """Return True for strings, bools, and numbers (safe enum-like values)."""
    return isinstance(value, (str, bool, int, float)) and not isinstance(value, complex)


def _redact_capabilities_value(value: Any, *, key: str | None = None) -> Any | None:
    """Recursively redact a capability-snapshot value to safe scalars only."""
    if key in _CAPABILITIES_FORBIDDEN_KEYS:
        return None
    if _is_safe_scalar(value):
        return value
    if isinstance(value, list):
        filtered = []
        for item in value:
            redacted = _redact_capabilities_value(item)
            if redacted is not None:
                filtered.append(redacted)
        return filtered if filtered else None
    if isinstance(value, dict):
        filtered = {}
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            redacted = _redact_capabilities_value(v, key=k)
            if redacted is not None:
                filtered[k] = redacted
        return filtered if filtered else None
    # Complex types (sets, tuples, custom objects) are dropped.
    return None


def project_session_capabilities(
    session_record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project a redacted capabilities object from an explicit capability-snapshot.

    If the session record does not carry a recognized capability snapshot, or
    the projection yields nothing after redaction, return None so the caller
    omits the field entirely. Never infers capabilities from provider id,
    model id, adapter behavior, runtime liveness, or queue state.

    Recognized snapshot keys: "capability-snapshot", "resolved-capabilities",
    "session-capabilities".
    """
    if not session_record or not isinstance(session_record, dict):
        return None

    raw = (
        session_record.get("capability-snapshot")
        or session_record.get("resolved-capabilities")
        or session_record.get("session-capabilities")
    )
    if not raw or not isinstance(raw, dict):
        return None

    projected: dict[str, Any] = {}

    # Only whitelist keys; drop forbidden keys and anything else.
    for key in _CAPABILITIES_SAFE_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if key in _CAPABILITIES_FORBIDDEN_KEYS:
            continue
        redacted = _redact_capabilities_value(value, key=key)
        if redacted is not None:
            projected[key] = redacted

    return projected if projected else None


# Binding index persistence.


def _read_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"contract-version": "v1", "bindings": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AudiaGenticError(
            code="IO-AGW-096",
            kind="agents",
            message="gateway session binding index is unreadable",
            details={"path": str(path)},
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("bindings"), dict):
        raise AudiaGenticError(
            code="VAL-AGW-096",
            kind="agents",
            message="gateway session binding index failed validation",
            details={"path": str(path)},
        )
    return payload


def register_open_binding(project_root: Path, session_record: dict[str, Any]) -> None:
    binding = session_record.get("binding")
    if not isinstance(binding, dict):
        return
    key = binding.get("provider-ref-key")
    binding_id = binding.get("binding-id")
    if not key or not binding_id:
        return
    with StartupLock(gateway_session_binding_lock_path(project_root)):
        index_path = gateway_session_binding_index_path(project_root)
        payload = _read_index(index_path)
        entries = list(payload["bindings"].get(key) or [])
        incoming_ownership = binding.get("ownership", "owned")  # default: owned
        for entry in entries:
            # Skip if already registered by the same session (idempotent).
            if entry.get("session-id") == session_record["session-id"]:
                continue
            # Only block duplicate OWNED bindings from a different session.
            # EXTERNAL bindings never block, and an OWNED binding is blocked
            # only by another active OWNED binding (not by EXTERNAL ones).
            if (
                entry.get("ownership") == "owned"
                and entry.get("state") == "active"
                and incoming_ownership == "owned"
            ):
                raise AudiaGenticError(
                    code="CON-AGW-096",
                    kind="agents",
                    message="duplicate owned provider session binding",
                    details={"provider-ref-key-prefix": str(key)[:12]},
                )
        # Idempotent: skip adding a duplicate entry for the same session.
        if not any(e.get("session-id") == session_record["session-id"] for e in entries):
            entries.append(
                {
                    "binding-id": binding_id,
                    "session-id": session_record["session-id"],
                    "ownership": binding.get("ownership"),
                    "relation": binding.get("relation"),
                    "state": session_record.get("state"),
                    "created-at": binding.get("created-at"),
                }
            )
        payload["bindings"][key] = entries
        atomic_write_json(index_path, payload)


def retire_binding(project_root: Path, session_record: dict[str, Any], *, state: str) -> None:
    binding = session_record.get("binding")
    if not isinstance(binding, dict):
        return
    key = binding.get("provider-ref-key")
    binding_id = binding.get("binding-id")
    if not key or not binding_id:
        return
    with StartupLock(gateway_session_binding_lock_path(project_root)):
        index_path = gateway_session_binding_index_path(project_root)
        payload = _read_index(index_path)
        entries = list(payload["bindings"].get(key) or [])
        changed = False
        for entry in entries:
            if entry.get("binding-id") == binding_id:
                entry["state"] = state
                entry["retired-at"] = now_iso_z()
                changed = True
        if changed:
            payload["bindings"][key] = entries
            atomic_write_json(index_path, payload)


# ── Convenience entry points (create / attach) ────────────────────


def create_open_binding(
    *,
    session_id: str,
    provider_id: str | None,
    surface_id: str | None,
    provider_ref: str,
    ref_namespace: str | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create an OPENED binding for a freshly opened provider session.

    Builds the binding dict with a fresh UUID and registers it in the project
    index. Returns the full binding record (including the opaque
    provider-session-ref that callers must not log).

    Raises AudiaGenticError if a duplicate owned active binding already exists
    for this provider ref key — cross-process lock guarantees atomicity.
    """
    binding = build_binding(
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        relation=BindingRelation.OPENED,
        surface_id=surface_id,
        ref_namespace=ref_namespace,
        identity_context_fingerprint=identity_context_fingerprint,
        execution_context_fingerprint=execution_context_fingerprint,
    )
    if binding is None:
        raise AudiaGenticError(
            code="VAL-AGW-098",
            kind="agents",
            message="provider ref is empty; cannot create open binding",
            details={},
        )
    return binding


def attach_binding(
    *,
    session_id: str,
    provider_id: str | None,
    surface_id: str | None,
    provider_ref: str,
    generation: int = 1,
    ownership: SessionOwnership = SessionOwnership.EXTERNAL,
    predecessor_binding_id: str | None = None,
    ref_namespace: str | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Attach to an existing provider session (ATTACHED relation).

    Unlike OPENED bindings which default to OWNED ownership, attached
    sessions default to EXTERNAL — the external system owns the lifecycle.

    Raises AudiaGenticError on duplicate owned active binding.
    """
    if not provider_ref:
        raise AudiaGenticError(
            code="VAL-AGW-099",
            kind="agents",
            message="provider ref is empty; cannot attach to existing session",
            details={},
        )
    binding = build_binding(
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        generation=generation,
        relation=BindingRelation.ATTACHED,
        ownership=ownership,
        surface_id=surface_id,
        ref_namespace=ref_namespace,
        predecessor_binding_id=predecessor_binding_id,
        identity_context_fingerprint=identity_context_fingerprint,
        execution_context_fingerprint=execution_context_fingerprint,
    )
    if binding is None:
        raise AudiaGenticError(
            code="VAL-AGW-099",
            kind="agents",
            message="provider ref is empty; cannot create attach binding",
            details={},
        )
    return binding


def resume_binding(
    *,
    session_id: str,
    provider_id: str | None,
    surface_id: str | None,
    provider_ref: str,
    predecessor_binding_id: str,
    ref_namespace: str | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create a RESUMED_FROM binding linked to a terminal predecessor.

    Per AS30 step 15: resume never mutates the source record back to active.
    Callers must pass the predecessor's OWN provider_ref_key-relevant fields
    unchanged (provider_id/surface_id/ref_namespace/identity_context) so the
    key stays comparable; only provider_ref and generation differ. Ownership
    defaults to OWNED — a resumed session is a fresh owned session, not an
    attachment. Callers are responsible for verifying AS29's resolved surface
    validates resume_by_ref for this exact provider/surface/identity/project
    BEFORE calling this — this function does not re-check capability, same
    as attach_binding does not.

    Raises AudiaGenticError if provider ref is empty or binding creation fails.
    """
    if not provider_ref:
        raise AudiaGenticError(
            code="VAL-AGW-100",
            kind="agents",
            message="provider ref is empty; cannot create resume binding",
            details={},
        )
    binding = build_binding(
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        relation=BindingRelation.RESUMED_FROM,
        ownership=SessionOwnership.OWNED,
        surface_id=surface_id,
        ref_namespace=ref_namespace,
        predecessor_binding_id=predecessor_binding_id,
        identity_context_fingerprint=identity_context_fingerprint,
        execution_context_fingerprint=execution_context_fingerprint,
    )
    if binding is None:
        raise AudiaGenticError(
            code="VAL-AGW-100",
            kind="agents",
            message="provider ref is empty; cannot create resume binding",
            details={},
        )
    return binding


def replace_binding(
    *,
    session_id: str,
    provider_id: str | None,
    surface_id: str | None,
    provider_ref: str,
    predecessor_binding_id: str,
    ref_namespace: str | None = None,
    identity_context_fingerprint: str | None = None,
    execution_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Create a REPLACED binding: AG deliberately opened a different provider
    session because the predecessor could not legally/safely continue.

    Distinct from resume_binding only in the relation value persisted —
    callers (not this function) are responsible for the policy distinction
    of WHY a replacement was chosen over a resume, and must never surface a
    REPLACED outcome to callers as if it were a successful resume (AS30
    acceptance_criteria).

    Raises AudiaGenticError if provider ref is empty or binding creation fails.
    """
    if not provider_ref:
        raise AudiaGenticError(
            code="VAL-AGW-101",
            kind="agents",
            message="provider ref is empty; cannot create replacement binding",
            details={},
        )
    binding = build_binding(
        provider_id=provider_id,
        provider_session_ref=provider_ref,
        relation=BindingRelation.REPLACED,
        ownership=SessionOwnership.OWNED,
        surface_id=surface_id,
        ref_namespace=ref_namespace,
        predecessor_binding_id=predecessor_binding_id,
        identity_context_fingerprint=identity_context_fingerprint,
        execution_context_fingerprint=execution_context_fingerprint,
    )
    if binding is None:
        raise AudiaGenticError(
            code="VAL-AGW-101",
            kind="agents",
            message="provider ref is empty; cannot create replacement binding",
            details={},
        )
    return binding


# Binding index persistence.


def rebuild_index(project_root: Path) -> dict[str, Any]:
    """Rebuild the binding index from all persisted session records.

    Scans every session directory under the gateway sessions root, extracts
    active bindings, and writes a fresh index. Detects duplicate active
    owned bindings as an error condition (two sessions claiming ownership
    of the same provider ref is invalid).

    Returns the rebuilt payload (for callers that need to inspect it).
    """
    import logging

    logger = logging.getLogger(__name__)
    payload: dict[str, Any] = {"contract-version": "v1", "bindings": {}}
    recovered_count = 0
    duplicate_keys: list[str] = []
    root = gateway_sessions_root(project_root)
    if root.exists():
        for session_dir in sorted(root.iterdir()):
            record_path = session_dir / "record.json"
            if not record_path.exists():
                continue
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            binding = record.get("binding")
            if not isinstance(binding, dict) or record.get("state") in {
                "closed",
                "expired",
                "failed",
            }:
                continue
            key = binding.get("provider-ref-key")
            if not key:
                continue
            recovered_count += 1
            payload["bindings"].setdefault(key, []).append(
                {
                    "binding-id": binding.get("binding-id"),
                    "session-id": record.get("session-id"),
                    "ownership": binding.get("ownership"),
                    "relation": binding.get("relation"),
                    "state": record.get("state"),
                    "created-at": binding.get("created-at"),
                }
            )

    # Detect duplicate active owned bindings (error condition).
    for key, entries in payload["bindings"].items():
        owned_active = [
            e
            for e in entries
            if e.get("ownership") == "owned"
            and e.get("state") not in {"closed", "expired", "failed"}
        ]
        if len(owned_active) > 1:
            duplicate_keys.append(str(key)[:12])
            logger.error(
                "duplicate active owned bindings detected during index rebuild",
                extra={
                    "provider-ref-key-prefix": str(key)[:12],
                    "binding-ids": [e["binding-id"] for e in owned_active],
                    "session-ids": [e["session-id"] for e in owned_active],
                },
            )

    with StartupLock(gateway_session_binding_lock_path(project_root)):
        atomic_write_json(gateway_session_binding_index_path(project_root), payload)

    logger.info(
        "binding index rebuilt",
        extra={
            "recovered-bindings": recovered_count,
            "total-keys": len(payload["bindings"]),
            "duplicate-owned-keys": len(duplicate_keys),
        },
    )
    return payload
