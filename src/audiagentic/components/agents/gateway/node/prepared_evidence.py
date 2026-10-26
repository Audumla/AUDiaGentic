"""Private per-command accepted preparation evidence, never an authorization.

Persist before canonical binding. Orphans remain non-authoritative; reads require
an original matching canonical bind, and publication requires original durable
authorization. Current central ownership, terminal receipts and publication state
remain the publication owner's checks under its request/owner locks. This module
writes no canonical record, response, transition or node-native state.

Owner storage directories must be protected from hostile replacement. Detected
symlinks/junctions/reparse points fail closed before and after I/O; this is not a
portable descriptor-relative sandbox against concurrent hostile filesystem edits.
Foundation atomic I/O protects exact bytes; Windows ACLs remain deployment-owned.
"""
from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_node_prepared_evidence_path,
    gateway_request_maintenance_lock_path,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_bytes, read_bytes_with_retry
from audiagentic.foundation.system.process import StartupLock

from .contracts import (
    MAX_FRAME_BYTES,
    CommandIdentity,
    _freeze,
    _identifier,
    canonical_json,
    conflict,
    invalid,
)
from .preparation import PreparationAttestation, validate_final_command_payload

_MAX_PREPARED_BYTES = 2 * MAX_FRAME_BYTES


@dataclass(frozen=True, slots=True)
class RetainedPreparedEvidence:
    """Self-consistent private bytes; construction alone conveys no authority."""

    attestation: PreparationAttestation
    final_command_payload: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.attestation) is not PreparationAttestation:
            raise invalid(1, "Prepared evidence requires a typed accepted attestation")
        attestation = PreparationAttestation.from_mapping(self.attestation.to_mapping())
        payload = _freeze(self.final_command_payload)
        if not isinstance(payload, Mapping):
            raise invalid(1, "Prepared evidence requires a final command object")
        # Derivation checks internal consistency only. Persist/read separately
        # validate against the trusted expected command/canonical record.
        binding = attestation.binding
        import hashlib

        identity = CommandIdentity(
            binding.command_id, binding.request_id, binding.node_id, binding.node_epoch,
            binding.gateway_owner_epoch, binding.connection_generation, binding.workspace_id,
            binding.grant_revision, binding.binding_generation,
            hashlib.sha256(canonical_json(payload)).hexdigest(), attestation.semantic.execution_profile_id,
        )
        validate_final_command_payload(payload, identity, accepted_attestation=attestation)
        object.__setattr__(self, "attestation", attestation)
        object.__setattr__(self, "final_command_payload", payload)


def _checked_path(root: Path, identity: CommandIdentity) -> Path:
    if (not isinstance(root, Path) or not root.is_absolute()
            or os.path.normcase(str(root)) != os.path.normcase(os.path.abspath(root))
            or type(identity) is not CommandIdentity):
        raise invalid(1, "Prepared evidence requires a canonical owner root and typed command")
    try:
        path = gateway_node_prepared_evidence_path(root, identity)
    except ValueError:
        raise invalid(1, "Prepared evidence request identity is invalid") from None
    _check_path(path)
    return path


def _check_path(path: Path) -> None:
    # Check parents first: do not knowingly traverse an existing redirected
    # parent just to inspect its child. Also catches dangling links via lstat.
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode)
                or getattr(part, "is_junction", lambda: False)()
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise conflict(1, "Prepared evidence paths must not contain links or reparse points")
        if not (stat.S_ISREG(info.st_mode) if part == path else stat.S_ISDIR(info.st_mode)):
            raise conflict(1, "Prepared evidence path has an unsupported file type")


def _encode(evidence: RetainedPreparedEvidence) -> bytes:
    raw = canonical_json({
        "version": 1, "kind": "node-prepared-v1",
        "attestation": evidence.attestation.to_mapping(),
        "final-command-payload": evidence.final_command_payload,
    })
    if len(raw) > _MAX_PREPARED_BYTES:
        raise invalid(1, "Prepared evidence exceeds the supported private size")
    return raw


def _read(path: Path, identity: CommandIdentity) -> RetainedPreparedEvidence:
    _check_path(path)
    info = path.stat()
    if info.st_size > _MAX_PREPARED_BYTES or (os.name == "posix" and info.st_mode & 0o077):
        raise conflict(1, "Prepared evidence is oversized or not private")
    raw = read_bytes_with_retry(path)
    _check_path(path)
    if len(raw) > _MAX_PREPARED_BYTES:
        raise conflict(1, "Prepared evidence exceeds the supported private size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):
        raise conflict(1, "Prepared evidence is not canonical UTF-8 JSON") from None
    if (not isinstance(value, dict)
            or set(value) != {"version", "kind", "attestation", "final-command-payload"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["kind"] != "node-prepared-v1"
            or not isinstance(value["attestation"], Mapping)
            or not isinstance(value["final-command-payload"], Mapping)
            or canonical_json(value) != raw):
        raise conflict(1, "Prepared evidence schema or canonical bytes changed")
    evidence = RetainedPreparedEvidence(
        PreparationAttestation.from_mapping(value["attestation"]), value["final-command-payload"],
    )
    validate_final_command_payload(
        evidence.final_command_payload, identity, accepted_attestation=evidence.attestation,
    )
    return evidence


def persist_prepared_once(
    root: Path, identity: CommandIdentity, attestation: PreparationAttestation,
    payload: Mapping[str, Any],
) -> RetainedPreparedEvidence:
    """Atomically retain accepted preparation before bind; never replace intent.

    Uses the existing request-maintenance fence. Call outside that fence and
    before the canonical bind. A matching replay is read-only. Orphan files are
    evidence only; this operation never binds, authorizes or publishes anything.
    """
    evidence = RetainedPreparedEvidence(attestation, payload)
    validate_final_command_payload(evidence.final_command_payload, identity, accepted_attestation=evidence.attestation)
    raw = _encode(evidence)
    try:
        path = _checked_path(root, identity)
        lock = gateway_request_maintenance_lock_path(root, identity.request_id)
        guard = lock.with_name(lock.name + ".guard")
        _check_path(lock)
        _check_path(guard)
        with StartupLock(lock):
            _check_path(lock)
            _check_path(guard)
            _check_path(path)
            if path.exists():
                existing = _read(path, identity)
                if _encode(existing) != raw:
                    raise conflict(1, "Existing prepared evidence differs from accepted preparation")
                return existing
            atomic_write_bytes(path, raw)
            retained = _read(path, identity)
            if _encode(retained) != raw:
                raise conflict(1, "Prepared evidence changed during persistence")
            return retained
    except (OSError, ValueError, AudiaGenticError):
        raise conflict(1, "Cannot retain matching immutable prepared evidence") from None


def _require_bound_record(
    record: Mapping[str, Any], identity: CommandIdentity,
    evidence: RetainedPreparedEvidence, *, require_authorized: bool,
) -> None:
    if not isinstance(record, Mapping) or type(require_authorized) is not bool:
        raise conflict(1, "Prepared evidence requires a canonical bound record")
    dispatch = record.get("node-dispatch")
    placement = record.get("node-placement")
    if not isinstance(dispatch, Mapping) or not isinstance(placement, Mapping):
        raise conflict(1, "Orphan prepared evidence has no canonical command binding")
    bound_identity = dispatch.get("identity")
    if not isinstance(bound_identity, Mapping) or CommandIdentity.from_mapping(bound_identity) != identity:
        raise conflict(1, "Prepared evidence does not match original bound command")
    accepted = evidence.attestation
    if (record.get("request-id") != identity.request_id
            or record.get("execution-profile-id") != identity.execution_profile_id
            or record.get("worker-id") != accepted.worker_id
            or type(record.get("attempt-epoch")) is not int
            or record["attempt-epoch"] != accepted.attempt_epoch
            or record.get("dispatch-owner-epoch") != identity.gateway_owner_epoch
            or dispatch.get("attestation-sha256") != accepted.digest
            or any(placement.get(key) != identity.to_mapping()[key]
                   for key in ("node-id", "workspace-id", "grant-revision"))):
        raise conflict(1, "Prepared evidence differs from canonical accepted attempt")
    if require_authorized:
        authorization = dispatch.get("authorization-id")
        if (not isinstance(authorization, str)
                or dispatch.get("authorization-state") not in {"authorized", "uncertain", "effect-observed", "terminal"}):
            raise conflict(1, "Prepared evidence has no original durable authorization")
        _identifier(authorization)


def read_prepared_evidence(
    root: Path, identity: CommandIdentity, record: Mapping[str, Any],
    require_authorized: bool = True,
) -> RetainedPreparedEvidence:
    """Read against the caller's trusted canonical record; never grant effects.

    Publication supplies its current locked record and checks owner/terminal
    state separately. False relaxes authorization only, never the canonical bind:
    it permits a bound pre-effect read, not an orphan or implicit grant. Missing,
    corrupt or mismatched evidence raises and must remain unresolved. No current
    grant lookup is performed for historically authorized work.
    """
    try:
        path = _checked_path(root, identity)
        evidence = _read(path, identity)
        _require_bound_record(record, identity, evidence, require_authorized=require_authorized)
        return evidence
    except (OSError, ValueError, TypeError, KeyError, AudiaGenticError):
        raise conflict(1, "Prepared evidence is missing, changed or not canonically authorized") from None


__all__ = ["RetainedPreparedEvidence", "persist_prepared_once", "read_prepared_evidence"]
