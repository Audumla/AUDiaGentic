"""Sparse best-effort node milestones over existing request-owned journals.

Call ONLY after releasing service-owner/grant/request locks, with a canonical
record snapshot. This helper validates/project facts; it grants no authority,
changes no work state and cannot prove callers released their locks. Preparation
requested is intent only; command-sent means local send returned, not native
acceptance. No heartbeat/poll loop or append retry belongs here.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from audiagentic.components.agents.gateway import observability as observations
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.diagnostics import SideEffectState
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .admission_contract import NodeAdmissionDescriptor
from .authority import NodeConnectionIdentity
from .contracts import CommandIdentity, _identifier, _integer
from .diagnostics import sanitize_node_error
from .placement import NodeAdmissionPlacement
from .receipts import Receipt

logger = logging.getLogger(__name__)
_failure_lock = threading.Lock()
_failures = 0
_STAGES = frozenset({
    "admission-validated", "connection-qualified", "prepare-requested", "prepare-accepted", "prepared-retained",
    "command-bound", "command-delivery-requested", "command-sent", "effect-authorized", "effect-denied",
    "reconciliation-started", "reconciliation-deferred", "reconciliation-completed", "failed",
})
_RECEIPTS = frozenset({"prepared", "effect-intent", "native-accepted", "terminal"})
_AUTHORIZATION = frozenset({"not-authorized", "authorized", "uncertain", "effect-observed", "terminal"})


def node_observation_failure_count() -> int:
    """Failed validation/sink operations, never canonical work or logger faults."""
    with _failure_lock:
        return _failures


def _failure():
    global _failures
    with _failure_lock:
        _failures += 1
        first = _failures == 1
    if first:
        try:
            # No identifiers, exception text, traceback or private payload.
            logger.warning("Node observation unavailable; canonical work unchanged")
        except Exception:
            pass


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("invalid canonical digest")
    return value


def _facts(root, record, milestone, started_ns, connection, error):
    if not isinstance(root, Path) or not root.is_absolute() or not isinstance(record, dict) or milestone not in _STAGES:
        raise ValueError("invalid node observation input")
    request_id = _identifier(record["request-id"])
    profile_id = _identifier(record["execution-profile-id"])
    descriptor = NodeAdmissionDescriptor.from_mapping(record["node-admission"])
    if descriptor.semantic.execution_profile_id != profile_id:
        raise ValueError("canonical profile mismatch")
    placement = record["node-placement"]
    if not isinstance(placement, Mapping) or set(placement) != {
            "node-id", "workspace-id", "principal-id", "server-project-id", "grant-revision"}:
        raise ValueError("invalid canonical placement")
    typed = NodeAdmissionPlacement(descriptor.server_id, placement["node-id"], placement["workspace-id"],
        placement["principal-id"], placement["server-project-id"], placement["grant-revision"])
    attempt = _integer(record["attempt-epoch"], 0)
    state = record["state"]
    if state not in {"queued", "running"} | store.TERMINAL_STATES:
        raise ValueError("invalid canonical state")
    owner = record.get("dispatch-owner-epoch")
    if owner is not None:
        _identifier(owner)
        if owner == "unbound":
            raise ValueError("unbound owner is not current authority")
    worker = record.get("worker-id")
    if worker is not None:
        _identifier(worker)
    facts = {"node-stage": milestone, "stage": milestone, "state": state, "attempt-epoch": attempt,
             "grant-revision": typed.grant_revision, "node": {"id": typed.node_id},
             "workspace": {"id": typed.workspace_id}, "principal": {"id": typed.principal_id},
             "server": {"id": typed.server_id}, "project": {"id": typed.server_project_id},
             "request": {"id": request_id}, "profile": {"id": profile_id}}
    if worker is not None:
        facts["worker"] = {"id": worker}
    if owner is not None:
        facts["gateway-owner-epoch"] = owner
    if connection is not None:
        if type(connection) is not NodeConnectionIdentity:
            raise ValueError("typed current connection is required")
        for value in (connection.node_id, connection.node_epoch, connection.gateway_owner_epoch):
            _identifier(value)
            if value == "unbound":
                raise ValueError("unbound connection")
        _integer(connection.connection_generation)
        if connection.node_id != typed.node_id or (owner is not None and connection.gateway_owner_epoch != owner):
            raise ValueError("connection differs from current canonical owner")
        facts["gateway-owner-epoch"] = connection.gateway_owner_epoch
        facts["connection-generation"] = connection.connection_generation
        facts["node"]["current-epoch"] = {"id": connection.node_epoch}
    dispatch = record.get("node-dispatch")
    side_effect = SideEffectState.NOT_STARTED
    if dispatch is not None:
        if not isinstance(dispatch, Mapping) or owner is None or worker is None or attempt < 1:
            raise ValueError("invalid bound canonical attempt")
        command = CommandIdentity.from_mapping(dispatch["identity"])
        if (command.request_id != request_id or command.execution_profile_id != profile_id
                or command.node_id != typed.node_id or command.workspace_id != typed.workspace_id
                or command.grant_revision != typed.grant_revision):
            raise ValueError("bound command differs from placement")
        authorization = dispatch["authorization-state"]
        if authorization not in _AUTHORIZATION:
            raise ValueError("invalid authorization state")
        auth_id = dispatch["authorization-id"]
        if auth_id is not None:
            _identifier(auth_id)
        if (authorization == "not-authorized") != (auth_id is None):
            raise ValueError("authorization evidence mismatch")
        if dispatch.get("attestation-sha256") is not None:
            _sha(dispatch["attestation-sha256"])
        receipt_stage, sequence = dispatch["receipt-stage"], _integer(dispatch["receipt-sequence"], 0)
        receipt_hash, output_hash = dispatch["receipt-sha256"], dispatch["output-sha256"]
        if receipt_stage is None:
            if sequence != 0 or receipt_hash is not None or output_hash is not None:
                raise ValueError("absent receipt has evidence")
        else:
            if receipt_stage not in _RECEIPTS or sequence < 1:
                raise ValueError("invalid receipt stage/sequence")
            _sha(receipt_hash)
            if receipt_stage == "terminal":
                _sha(output_hash)
            elif output_hash is not None:
                raise ValueError("nonterminal output digest")
            if Receipt(command, receipt_stage, sequence, output_hash).digest != receipt_hash:
                raise ValueError("receipt digest differs from canonical identity")
            if authorization == "not-authorized" and receipt_stage != "prepared":
                raise ValueError("receipt has no effect authorization")
            if (receipt_stage == "terminal") != (authorization == "terminal"):
                raise ValueError("terminal receipt/authorization mismatch")
            facts.update({"receipt-stage": receipt_stage, "receipt-sequence": sequence})
        side_effect = (SideEffectState.TERMINAL_EVIDENCE_SEEN if receipt_stage == "terminal"
                       else SideEffectState.MAY_HAVE_STARTED)
        # The generic journal's existing hash-safe key preserves exact command
        # payload SHA256 without bypassing redaction or adding another schema.
        facts["command"] = {"id": command.command_id, "artifact-sha256": command.payload_sha256}
        facts["command-epoch"] = command.gateway_owner_epoch
        facts["node"]["command-epoch"] = {"id": command.node_epoch}
        if output_hash is not None:
            facts["artifact-sha256"] = output_hash
    facts["side-effect-state"] = side_effect.value
    if started_ns is not None:
        now = time.monotonic_ns()
        if type(started_ns) is not int or not 0 <= started_ns <= now:
            raise ValueError("elapsed time requires a local monotonic start")
        facts["elapsed-ms"] = min((now - started_ns) // 1_000_000, 2**63 - 1)
        facts["timing-event"] = ("effect-authorization" if milestone in {"effect-authorized", "effect-denied"}
                                  else "runner-invocation")
    if error is not None:
        if not isinstance(error, AudiaGenticError):
            raise ValueError("registered typed error required")
        safe = sanitize_node_error(error)
        facts.update({"stage": safe.details["stage"], "phase": safe.details["phase"],
                      "reason-code": safe.details["reason-code"], "failure-code": safe.code})
    return facts


def emit_node_stage(root: Path, record: dict, stage: str, *, started_ns: int | None = None,
                    connection: NodeConnectionIdentity | None = None, error: AudiaGenticError | None = None) -> None:
    """Emit after authority locks; diagnostic Exceptions never undo canonical work.

    Each failed validation/sink operation increments the process-local scalar
    before its once-only warning; logger faults do not add another lost event.
    KeyboardInterrupt/SystemExit/control-flow BaseExceptions propagate. Partial
    writes are never retried.
    Missing historical admission identity skips emission instead of inventing a
    server ID. Artifact kind and ACK custody are not inferred from output hashes.
    started_ns belongs to this invocation (or effect-handler operation); never
    compare elapsed durations across operations/processes or gateway restarts.
    """
    try:
        facts = _facts(root, record, stage, started_ns, connection, error)
    except Exception:
        _failure()
        return
    try:
        store.record_gateway_timeline(root, record["request-id"], f"node.{stage}",
                                      state=record["state"], attributes=facts)
    except Exception:
        _failure()
    try:
        observations.append_observation(root, record["request-id"], event_kind="node-stage-observed",
            source="node-runtime", force_flush=True, attempt_epoch=max(1, record["attempt-epoch"]), diagnostic_facts=facts)
    except Exception:
        _failure()
