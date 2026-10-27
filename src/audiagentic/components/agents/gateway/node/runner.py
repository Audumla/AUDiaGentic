"""Finite central node dispatch, not a service enablement or recovery executor.

The queue calls synchronously off-loop. Network work is bridged to the supplied
existing loop; all disk I/O and owner/auth/canonical locks stay off that loop.
Bound commands are observer-only, never resent. A composed receipt/publication
waiter may finish canonical work; absence or uncertainty defers, never completes.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import uuid
from collections.abc import Callable
from pathlib import Path

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.diagnostics import SideEffectState
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .admission_owner import read_node_admission_snapshot
from .authority import SealedNodePlacement
from .contracts import CommandIdentity, canonical_json, conflict, invalid
from .diagnostics import sanitize_node_error
from .occupancy import NodeOccupancy, record_holds_node
from .preparation import (
    PreparationBinding,
    assemble_final_command_payload,
    validate_final_command_payload,
)
from .prepared_evidence import persist_prepared_once, read_prepared_evidence
from .work_protocol import EffectAuthorize, PreparationRejected, PreparedReply, parse_work_frame


class NodeRunner:
    def __init__(self, config, service_store, authority, connections, loop, *,
                 waiter: Callable[[Path, dict], object] | None = None, timeout: float = 15.0):
        if (authority.service_root != service_store.root.resolve() or connections.authority is not authority
                or config.config_path != authority.path):
            raise invalid(1, "Node runner requires the same configured service/auth/connection owners")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise invalid(1, "Node runner timeout must be positive and finite")
        self.config, self.service, self.authority = config, service_store, authority
        self.connections, self.loop, self.waiter, self.timeout = connections, loop, waiter, timeout
        self.owner_epoch = connections.gateway_owner_epoch
        self.occupancy = NodeOccupancy(tuple(config.projects.values()), server_id=config.server_id)

    def _bridge(self, coroutine):
        if not self.loop.is_running() or self.loop.is_closed():
            coroutine.close()
            raise conflict(1, "Node transport loop is unavailable", reason_code="transport-unavailable")
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        try:
            return future.result(timeout=self.timeout + 1)
        except BaseException:
            future.cancel()
            raise

    def _read(self, root, original):
        if root not in tuple(path.resolve() for path in self.config.projects.values()):
            raise conflict(1, "Node runner root is not configured canonical storage")
        current = store.read_record(root, original["request-id"])
        if (original.get("dispatch-owner-epoch") != self.owner_epoch
                or current.get("dispatch-owner-epoch") != self.owner_epoch
                or any(current.get(k) != original.get(k) for k in ("worker-id", "attempt-epoch"))):
            raise conflict(1, "Node runner does not own the queue-assigned attempt")
        if not isinstance(current.get("node-placement"), dict):
            raise conflict(1, "Node runner requires canonical node placement")
        return current

    def _defer(self, root, record, error=None, *, stage="observe", reason=None, phase=None):
        # A null canonical dispatch is positive no-effect proof. Failure to read
        # or a non-null bind stays uncertain, regardless of a send exception.
        side_effect = SideEffectState.MAY_HAVE_STARTED
        try:
            dispatch = store.read_record(root, record["request-id"]).get("node-dispatch")
            if dispatch is None:
                side_effect = SideEffectState.NOT_STARTED
            elif dispatch.get("receipt-stage") == "terminal":
                side_effect = SideEffectState.TERMINAL_EVIDENCE_SEEN
        except Exception:
            pass
        safe = sanitize_node_error(error, stage, reason, phase)
        return RecoveryDeferred(safe, phase=safe.details["phase"], side_effect_state=side_effect.value)

    def _observe(self, root, record):
        if record.get("node-dispatch") is None:
            raise self._defer(root, record)
        if record["state"] in store.TERMINAL_STATES and not record_holds_node(record):
            return record
        if self.waiter is not None:
            self.waiter(root, record)  # Existing orchestration, outside all authority locks.
            with self.service.owner_guard(self.owner_epoch):
                settled = self._read(root, record)
            if settled["state"] in store.TERMINAL_STATES and not record_holds_node(settled):
                return settled
        raise self._defer(root, record)

    def _slot(self, node_id):
        slot = self.connections.current_slot(node_id)
        if slot is None or slot.capability != "active":
            raise conflict(1, "Node has no active authenticated connection slot", reason_code="transport-unavailable")
        return slot

    def _authorized(self, root, record, identity, slot, callback):
        placement = record["node-placement"]
        sealed = SealedNodePlacement(identity, self.config.server_id,
                                     placement["principal-id"], placement["server-project-id"])

        def live():
            current = self._slot(identity.node_id)
            if (current.connection is not slot.connection or current.identity != slot.identity
                    or current.grant_revision != identity.grant_revision):
                raise conflict(1, "Node connection changed during dispatch", reason_code="connection-replaced-or-closed")
            return current.identity

        def commit():
            if self.occupancy.snapshot().occupied(self.config.server_id, identity.node_id,
                                                 exclude_request=(root, identity.request_id)):
                raise conflict(1, "Another canonical command retains node capacity", reason_code="capacity-occupied")
            return callback()

        return self.authority.authorize_effect(sealed, connection=live, callback=commit)

    async def _prepare(self, slot, payload):
        if not await asyncio.to_thread(self.authority.serialize,
                lambda: self.connections.current_slot(slot.identity.node_id) == slot):
            raise conflict(1, "Node connection changed before preparation", reason_code="connection-replaced-or-closed")
        return await slot.connection.request_work("reconcile", payload,
            reply_types=(PreparedReply, PreparationRejected), timeout=self.timeout)

    async def _send_command(self, slot, identity, payload):
        if not await asyncio.to_thread(self.authority.serialize,
                lambda: self.connections.current_slot(identity.node_id) == slot):
            raise conflict(1, "Node connection changed before command delivery", reason_code="connection-replaced-or-closed")
        return await slot.connection.send_work("command", {"identity": identity.to_mapping(), "payload": payload})

    def __call__(self, root: Path, record: dict, *, reconcile_only: bool = False):
        if type(reconcile_only) is not bool:
            raise invalid(1, "Node reconcile-only flag must be boolean")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise invalid(1, "Synchronous NodeRunner must run off the event loop")
        stage = "ownership"
        try:
            with self.service.owner_guard(self.owner_epoch):
                current = self._read(root, record)
            if current.get("node-dispatch") is not None or reconcile_only:
                stage = "observe"
                return self._observe(root, current)
            if (current["state"] != "running" or current.get("provider-transport-kind") != "worker"
                    or current.get("cancel-requested")):
                raise self._defer(root, current, stage="ownership", reason="attempt-not-dispatchable")
            resume_unbound = current.get("recovery-required") is True
            stage = "admission"
            snapshot = read_node_admission_snapshot(root, current)
            if snapshot.descriptor.server_id != self.config.server_id:
                raise conflict(1, "Node admission belongs to another server")
            placement = current["node-placement"]
            if self.config.projects.get(placement["server-project-id"]) != root:
                raise conflict(1, "Node placement differs from canonical storage project")
            stage = "transport"
            with self.service.owner_guard(self.owner_epoch):
                refreshed = self.connections.refresh_capability(placement["node-id"])
                if refreshed is not None and refreshed[1] != "active":
                    raise conflict(1, "Node grant no longer permits fresh work", reason_code="grant-or-connection-changed")
                slot = self.authority.serialize(lambda: self._slot(placement["node-id"]))
                if slot.grant_revision != placement["grant-revision"]:
                    raise conflict(1, "Node grant changed before preparation")
                binding = PreparationBinding(uuid.uuid4().hex, current["request-id"], slot.identity.node_id,
                    slot.identity.node_epoch, self.owner_epoch, slot.identity.connection_generation,
                    placement["workspace-id"], placement["grant-revision"], 1, uuid.uuid4().hex, uuid.uuid4().hex)
                # Generation 1 belongs to this new command's first binding.
                # Reconnects never reuse or increment this immutable command.
                if self.authority.serialize(lambda: self.occupancy.snapshot().occupied(
                        self.config.server_id, placement["node-id"], exclude_request=(root, current["request-id"]))):
                    raise conflict(1, "Node capacity is occupied before preparation", reason_code="capacity-occupied")
            stage = "prepare"
            sent, reply_frame, reply = self._bridge(self._prepare(slot, {
                "kind": "prepare", "binding": binding.to_mapping(), "semantic": snapshot.descriptor.semantic.to_mapping(),
                "agent-id": snapshot.agent_id, "worker-id": current["worker-id"], "attempt-epoch": current["attempt-epoch"],
                "raw-prompt": snapshot.raw_prompt, "source-workspace": snapshot.source_workspace.to_mapping(),
                "caller-root": snapshot.caller_root, "source": snapshot.source,
                "metadata": {k: v for k, v in snapshot.metadata.items() if k in {"schema_version", "correlation_id"}},
                "timeout-seconds": current.get("timeout-seconds"),
            }))
            stage = "prepared-reply"
            if type(reply) is PreparationRejected:
                if reply.in_reply_to != sent.message_id or reply.message_id != reply_frame.message_id:
                    raise conflict(1, "Node rejection is not correlated with preparation")
                rejected = sanitize_node_error({"code": reply.code}, stage="prepared-reply", reason="preparation-rejected")
                if rejected.code != reply.code:
                    rejected = sanitize_node_error(invalid(1, "Unregistered node preparation rejection"),
                                                   stage="prepared-reply", reason="preparation-rejected")
                raise rejected
            if (type(reply) is not PreparedReply or reply.in_reply_to != sent.message_id
                    or reply.message_id != reply_frame.message_id or reply.attestation.binding != binding
                    or reply.attestation.semantic != snapshot.descriptor.semantic
                    or reply.attestation.worker_id != current["worker-id"]
                    or reply.attestation.attempt_epoch != current["attempt-epoch"]
                    or reply.attestation.provider_id != snapshot.profile.provider_id):
                raise conflict(1, "Node preparation reply differs from admitted attempt")
            payload = assemble_final_command_payload(reply.attestation, snapshot.raw_prompt)
            command = CommandIdentity(binding.command_id, binding.request_id, binding.node_id, binding.node_epoch,
                binding.gateway_owner_epoch, binding.connection_generation, binding.workspace_id, binding.grant_revision,
                binding.binding_generation, hashlib.sha256(canonical_json(payload)).hexdigest(), current["execution-profile-id"])
            validate_final_command_payload(payload, command, accepted_attestation=reply.attestation)
            stage = "retain-prepared"
            persist_prepared_once(root, command, reply.attestation, payload)
            stage = "admission"
            with self.service.owner_guard(self.owner_epoch):
                # Check retained source bytes again after remote preparation.
                read_node_admission_snapshot(root, current)
                stage = "bind"
                bound = self._authorized(root, current, command, slot, lambda: store.bind_owned_node_dispatch(
                    root, current["request-id"], identity=command, command_payload=payload,
                    accepted_attestation=reply.attestation, owner_epoch=self.owner_epoch,
                    worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
                    expected_revision=current["revision"], resume_unbound=resume_unbound))
            stage = "command"
            self._bridge(self._send_command(slot, command, payload))
            stage = "observe"
            return self._observe(root, bound)
        except RecoveryDeferred as error:
            deferred = self._defer(root, record, error.error, stage=stage, phase=error.phase)
            raise deferred from deferred.error
        except Exception as error:
            deferred = self._defer(root, record, error, stage=stage)
            raise deferred from deferred.error

    def _effect_reply(self, connection, frame, work):
        try:
            parsed = parse_work_frame(frame, role="gateway", current_connection=connection.identity,
                                      capability=connection.capability, max_artifact_bytes=1024 * 1024)
            if type(parsed) is not EffectAuthorize or parsed != work:
                raise conflict(1, "Effect request differs from authenticated frame")
            command = work.identity
            with self.service.owner_guard(self.owner_epoch):
                matches = []
                for root in dict.fromkeys(self.config.projects.values()):
                    try:
                        record = store.read_record(root, command.request_id)
                    except AudiaGenticError as error:
                        if error.code != "RES-AGW-001":
                            raise
                    else:
                        matches.append((root, record))
                if len(matches) != 1:
                    raise conflict(1, "Effect requires one original canonical request")
                root, record = matches[0]
                if (record.get("node-dispatch") is None or record["node-dispatch"]["identity"] != command.to_mapping()
                        or record.get("dispatch-owner-epoch") != self.owner_epoch
                        or command.gateway_owner_epoch != self.owner_epoch):
                    raise conflict(1, "Effect does not match the original current-owned command")
                evidence = read_prepared_evidence(root, command, record, require_authorized=False)
                snapshot = read_node_admission_snapshot(root, record)
                if (snapshot.descriptor.server_id != self.config.server_id
                        or snapshot.descriptor.semantic != evidence.attestation.semantic
                        or self.config.projects.get(record["node-placement"]["server-project-id"]) != root):
                    raise conflict(1, "Effect differs from original configured admission")
                slot = self.authority.serialize(lambda: self._slot(command.node_id))
                if slot.connection is not connection:
                    raise conflict(1, "Effect arrived on another connection")
                authorization_id = record["node-dispatch"].get("authorization-id") or uuid.uuid4().hex
                self._authorized(root, record, command, slot, lambda: store.authorize_owned_node_effect(
                    root, command.request_id, identity=command, authorization_id=authorization_id,
                    accepted_attestation=evidence.attestation, current_node_epoch=connection.identity.node_epoch,
                    current_connection_generation=connection.identity.connection_generation, owner_epoch=self.owner_epoch,
                    worker_id=record["worker-id"], attempt_epoch=record["attempt-epoch"], expected_revision=record["revision"]))
            return "effect-authorized", {"identity": command.to_mapping(), "authorization-request-id": frame.message_id,
                                         "authorization-id": authorization_id, "authorized": True}
        except Exception as error:
            safe = sanitize_node_error(error, "bind")
            return "effect-denied", {"identity": work.identity.to_mapping(),
                                        "authorization-request-id": frame.message_id, "code": safe.code}

    async def handle_effect_authorize(self, connection, frame, work):
        """Central runtime handler: disk/locks off-loop, correlated reply after locks."""
        if type(work) is not EffectAuthorize:
            raise invalid(1, "NodeRunner effect handler requires EffectAuthorize")
        kind, payload = await asyncio.to_thread(self._effect_reply, connection, frame, work)
        return await connection.send_work(kind, payload)
