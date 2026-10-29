"""Canonical registry of external (EXTERNAL-owned) provider sessions (SH50a).

An external session is a native session a human already runs. The gateway may
drive it but never owns its process (SH49), so what the gateway must own is
the *claim to write to it*: which node locator it is reached by, which join
basis (SH48 registration) justified that, and which single gateway writer
currently holds it. This module persists exactly that, keyed by the existing
provider-ref key, one schema-validated record per file.

- ``register`` creates the record, or is idempotent for an unchanged
  locator/basis. A changed locator or basis supersedes it: the binding
  generation increases and any writer claim is dropped, so a holder from the
  previous generation can no longer write.
- ``claim_writer`` is a compare-and-swap on the binding generation: it fails
  if the generation moved or another writer holds the session. Re-claiming by
  the same writer is a no-op.
- ``release_writer`` only the holder can release; releasing nothing is a no-op.
- ``assert_writer`` is the check dispatch makes immediately before an effect.

Each operation runs under one lock per ref key and writes atomically. The
registry takes no other gateway lock, so it adds no lock-order edge. Durable
pre-effect intent and node receipts are SH51; owner-epoch fencing is SH50b.
A registration is not an authorization grant, and nothing here can start,
close or kill a provider process.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.components.agents.agents_paths import gateway_external_sessions_root
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z

registry_error = make_error_factory("VAL", "XSR", "agents")
conflict_error = make_error_factory("CON", "XSR", "agents")

SCHEMA_STEM = "external-session-registration"
_REF_KEY = re.compile(r"[0-9a-f]{64}")
_BASIS_FIELDS = ("evidence-id", "executable-digest", "executable-version", "instance-generation")


def _paths(project_root: Path, ref_key: str) -> tuple[Path, Path]:
    if not isinstance(ref_key, str) or not _REF_KEY.fullmatch(ref_key):
        raise registry_error(4, "Invalid provider ref key")
    root = gateway_external_sessions_root(project_root)
    return root / f"{ref_key}.json", root / f"{ref_key}.lock"


def _validate(record: Any) -> dict[str, Any]:
    errors = sorted(Draft202012Validator(read_schema(SCHEMA_STEM)).iter_errors(record),
                    key=lambda error: list(error.absolute_path))
    if errors:
        raise registry_error(1, f"Invalid external session registration: {errors[0].message}",
                             pointer="/" + "/".join(str(part) for part in errors[0].absolute_path), issues=len(errors))
    return record


def _load(path: Path, ref_key: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        record = _validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise registry_error(2, "External session registration is unreadable; refusing to use it") from error
    if record["ref-key"] != ref_key:
        raise registry_error(3, "External session registration does not match its location")
    return record


def _store(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    record["updated-at"] = now_iso_z()
    atomic_write_json(path, _validate(record))
    return record


def get_registration(project_root: Path, ref_key: str) -> dict[str, Any] | None:
    """The current registration, or None. A corrupt record raises, never reads as absent."""
    path, lock = _paths(project_root, ref_key)
    if not path.exists():
        return None
    with StartupLock(lock):
        return _load(path, ref_key)


def register(project_root: Path, *, ref_key: str, provider_id: str, surface_id: str,
             node_locator: str, basis: dict[str, str]) -> dict[str, Any]:
    """Create the registration, or supersede it when the locator or basis changed."""
    if set(basis) != set(_BASIS_FIELDS):
        raise registry_error(5, "Registration basis must carry exactly the proven join facts",
                             fields=sorted(set(basis) ^ set(_BASIS_FIELDS)))
    path, lock = _paths(project_root, ref_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with StartupLock(lock):
        current = _load(path, ref_key)
        if current is not None and (current["provider-id"], current["surface-id"]) != (provider_id, surface_id):
            raise conflict_error(6, "Provider ref is already registered for a different provider surface")
        if current is not None and current["node-locator"] == node_locator and current["basis"] == basis:
            return current
        now = now_iso_z()
        record = {
            "schema-version": 1, "ref-key": ref_key, "provider-id": provider_id, "surface-id": surface_id,
            "node-locator": node_locator, "basis": dict(basis), "writer": None,
            "generation": 1 if current is None else current["generation"] + 1,
            "created-at": now if current is None else current["created-at"], "updated-at": now,
        }
        return _store(path, record)


def claim_writer(project_root: Path, ref_key: str, *, writer_id: str, generation: int) -> dict[str, Any]:
    """Take the single writer claim if the generation is current and no other writer holds it."""
    path, lock = _paths(project_root, ref_key)
    with StartupLock(lock):
        record = _require(path, ref_key)
        if record["generation"] != generation:
            raise conflict_error(7, "Binding generation is stale; re-register before claiming",
                                 current=record["generation"], given=generation)
        holder = record["writer"]
        if holder is not None:
            if holder["writer-id"] == writer_id:
                return record
            raise conflict_error(8, "Another writer already holds this external session")
        record["writer"] = {"writer-id": writer_id, "claimed-at": now_iso_z()}
        return _store(path, record)


def release_writer(project_root: Path, ref_key: str, *, writer_id: str, generation: int) -> dict[str, Any]:
    """Release the claim; only the holder at the current generation may, and no claim is a no-op."""
    path, lock = _paths(project_root, ref_key)
    with StartupLock(lock):
        record = _require(path, ref_key)
        holder = record["writer"]
        if holder is None:
            return record
        if holder["writer-id"] != writer_id or record["generation"] != generation:
            raise conflict_error(9, "Only the current writer at the current generation can release the claim")
        record["writer"] = None
        return _store(path, record)


def assert_writer(project_root: Path, ref_key: str, *, writer_id: str, generation: int) -> dict[str, Any]:
    """Immediately-before-effect check: this writer holds the claim at this generation."""
    path, lock = _paths(project_root, ref_key)
    with StartupLock(lock):
        record = _require(path, ref_key)
    holder = record["writer"]
    if record["generation"] != generation:
        raise conflict_error(7, "Binding generation is stale", current=record["generation"], given=generation)
    if holder is None or holder["writer-id"] != writer_id:
        raise conflict_error(10, "This writer does not hold the external session")
    return record


def _require(path: Path, ref_key: str) -> dict[str, Any]:
    record = _load(path, ref_key)
    if record is None:
        raise registry_error(11, "External session is not registered")
    return record
