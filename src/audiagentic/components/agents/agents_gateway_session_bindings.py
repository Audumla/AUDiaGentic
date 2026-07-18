"""Durable AG ↔ provider session binding index (AS30).

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
        hasher.update(part.encode("utf-8"))
        hasher.update(b"\0")
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
        for entry in entries:
            if entry.get("ownership") == "owned" and entry.get("state") == "active":
                raise AudiaGenticError(
                    code="CON-AGW-096",
                    kind="agents",
                    message="duplicate owned provider session binding",
                    details={"provider-ref-key-prefix": str(key)[:12]},
                )
        entries.append({
            "binding-id": binding_id,
            "session-id": session_record["session-id"],
            "ownership": binding.get("ownership"),
            "relation": binding.get("relation"),
            "state": session_record.get("state"),
            "created-at": binding.get("created-at"),
        })
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


def rebuild_index(project_root: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {"contract-version": "v1", "bindings": {}}
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
            if not isinstance(binding, dict) or record.get("state") in {"closed", "expired", "failed"}:
                continue
            key = binding.get("provider-ref-key")
            if not key:
                continue
            payload["bindings"].setdefault(key, []).append({
                "binding-id": binding.get("binding-id"),
                "session-id": record.get("session-id"),
                "ownership": binding.get("ownership"),
                "relation": binding.get("relation"),
                "state": record.get("state"),
                "created-at": binding.get("created-at"),
            })
    with StartupLock(gateway_session_binding_lock_path(project_root)):
        atomic_write_json(gateway_session_binding_index_path(project_root), payload)
    return payload
