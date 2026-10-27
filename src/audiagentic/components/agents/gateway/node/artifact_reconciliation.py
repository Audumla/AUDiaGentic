"""Bounded original-artifact retrieval and canonical terminal publication.

The runner's synchronous waiter calls this off-loop. Canonical terminal receipt
metadata, not cursor equality or receipt replay, selects the original artifact.
No command, preparation, execution or second result store is introduced here.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from pathlib import Path

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY

from .admission_contract import NodeAdmissionDescriptor
from .contracts import CommandIdentity, _integer, conflict, invalid
from .diagnostics import sanitize_node_error
from .observability import emit_node_stage
from .publication import publish_owned_node_terminal
from .receipts import Receipt, _digest
from .work_protocol import MAX_CHUNK_BYTES, ArtifactChunk


class NodeTerminalReconciler:
    """Existing NodeRunner waiter; response custody is the publication owner's."""

    def __init__(self, config, service_store, connections, loop, *, max_artifact_bytes=1024 * 1024,
                 chunk_bytes=MAX_CHUNK_BYTES, max_read_budget_bytes=None, timeout_seconds=30):
        if (service_store.key != GATEWAY_SERVICE_KEY or connections.authority.path != config.config_path
                or connections.authority.service_root != service_store.root.resolve()):
            raise invalid(1, "Artifact reconciliation requires the same configured owners")
        _integer(max_artifact_bytes)
        _integer(chunk_bytes)
        if chunk_bytes > MAX_CHUNK_BYTES:
            raise invalid(1, "Artifact chunk bound exceeds the wire contract")
        if max_read_budget_bytes is None:
            max_read_budget_bytes = max_artifact_bytes * ((max_artifact_bytes + chunk_bytes - 1) // chunk_bytes)
        _integer(max_read_budget_bytes)
        if max_read_budget_bytes < max_artifact_bytes:
            raise invalid(1, "Artifact read budget must cover the first trusted full-file bound")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise invalid(1, "Artifact timeout must be positive and finite")
        self.config, self.service, self.connections, self.loop = config, service_store, connections, loop
        self.owner_epoch = connections.gateway_owner_epoch
        self.max_bytes, self.chunk_bytes = max_artifact_bytes, chunk_bytes
        self.read_budget, self.timeout = max_read_budget_bytes, timeout_seconds

    def _read(self, root, original):
        if root not in self.config.projects.values():
            raise conflict(1, "Artifact request root is outside configured storage")
        record = store.read_record(root, original["request-id"], include_output=False)
        if (record.get("dispatch-owner-epoch") != self.owner_epoch
                or any(record.get(key) != original.get(key) for key in ("worker-id", "attempt-epoch"))):
            raise conflict(1, "Artifact request attempt or owner changed")
        dispatch, prior = record.get("node-dispatch"), original.get("node-dispatch")
        if not isinstance(dispatch, dict) or not isinstance(prior, dict) or dispatch["identity"] != prior["identity"]:
            raise conflict(1, "Artifact request has no original bound command")
        identity = CommandIdentity.from_mapping(dispatch["identity"])
        placement = record.get("node-placement") or {}
        if (identity.request_id != record["request-id"] or identity.execution_profile_id != record["execution-profile-id"]
                or placement.get("node-id") != identity.node_id or placement.get("workspace-id") != identity.workspace_id
                or placement.get("grant-revision") != identity.grant_revision
                or self.config.projects.get(placement.get("server-project-id")) != root
                or not record.get("dispatch-service-root")
                or Path(record["dispatch-service-root"]).resolve() != self.service.root.resolve()):
            raise conflict(1, "Artifact request differs from its original placement")
        if record.get("node-admission") is not None and NodeAdmissionDescriptor.from_mapping(record["node-admission"]).server_id != self.config.server_id:
            raise conflict(1, "Artifact request belongs to another server")
        return record, identity

    def _current(self, node_id, expected=None):
        with self.service.owner_guard(self.owner_epoch):
            def check():
                slot = self.connections.current_slot(node_id)
                if (slot is None or slot.capability not in {"active", "drain"}
                        or slot.connection.close_reason is not None or slot.connection.failure is not None
                        or (expected is not None and slot.connection is not expected)):
                    raise conflict(1, "Artifact channel changed", reason_code="artifact-channel-replaced")
                return slot.connection
            return self.connections.authority.serialize(check)

    async def _fetch(self, connection, identity, digest):
        data, total, charged = bytearray(), None, 0
        deadline = time.monotonic() + self.timeout
        while True:
            if charged + (self.max_bytes if total is None else total) > self.read_budget:
                raise conflict(1, "Artifact read budget exhausted", reason_code="artifact-read-budget-exhausted")
            await asyncio.to_thread(self._current, identity.node_id, connection)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Artifact transfer deadline expired")
            sent, frame, reply = await connection.request_work("reconcile", {
                "kind": "artifact-get", "identity": identity.to_mapping(), "artifact-sha256": digest,
                "offset": len(data), "limit": self.chunk_bytes,
            }, reply_types=(ArtifactChunk,), timeout=remaining)
            if (type(reply) is not ArtifactChunk or reply.in_reply_to != sent.message_id
                    or reply.message_id != frame.message_id or reply.identity != identity
                    or reply.artifact_sha256 != digest or reply.offset != len(data)
                    or type(reply.total_bytes) is not int or not 0 <= reply.total_bytes <= self.max_bytes
                    or len(reply.data) > self.chunk_bytes
                    or (total is not None and reply.total_bytes != total)
                    or (reply.total_bytes > 0 and not reply.data)
                    or len(data) + len(reply.data) > reply.total_bytes
                    or type(reply.eof) is not bool or reply.eof != (len(data) + len(reply.data) == reply.total_bytes)):
                raise conflict(1, "Artifact transfer metadata changed", reason_code="artifact-transfer-mismatch")
            if reply.artifact_kind != "worker-terminal-result":
                raise conflict(1, "Artifact kind cannot establish worker output", reason_code="artifact-kind-unsupported")
            total = reply.total_bytes
            charged += total  # Recipient currently reads/hashes the whole artifact per chunk.
            if charged > self.read_budget:
                raise conflict(1, "Artifact read budget exhausted", reason_code="artifact-read-budget-exhausted")
            data.extend(reply.data)
            if reply.eof:
                raw = bytes(data)
                if hashlib.sha256(raw).hexdigest() != digest:
                    raise conflict(1, "Artifact bytes differ from custody", reason_code="artifact-transfer-mismatch")
                # Complete bytes were authenticated at reception and verified.
                # Later replacement does not invalidate this immutable artifact.
                return raw

    def __call__(self, root, original):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise invalid(1, "Artifact reconciliation must run off the transport loop")
        current, stage, started_ns = None, "artifact", time.monotonic_ns()
        try:
            with self.service.owner_guard(self.owner_epoch):
                current, identity = self._read(root, original)
            if current["state"] in store.TERMINAL_STATES:
                return current  # Preserve an existing lifecycle winner, never resurrect it.
            dispatch = current["node-dispatch"]
            if dispatch["receipt-stage"] != "terminal" or dispatch["authorization-state"] != "terminal":
                raise conflict(1, "Original terminal receipt is not ready", reason_code="artifact-receipt-pending")
            receipt = Receipt(identity, "terminal", _integer(dispatch["receipt-sequence"]), _digest(dispatch["output-sha256"]))
            if receipt.digest != dispatch["receipt-sha256"]:
                raise conflict(1, "Original terminal receipt changed", reason_code="artifact-transfer-mismatch")
            connection = self._current(identity.node_id)
            if not self.loop.is_running() or self.loop.is_closed():
                raise conflict(1, "Artifact transport loop is unavailable")
            future = asyncio.run_coroutine_threadsafe(self._fetch(connection, identity, receipt.output_sha256), self.loop)
            try:
                raw = future.result(timeout=self.timeout + 1)
            except BaseException:
                future.cancel()
                raise
            emit_node_stage(root, current, "artifact-verified", started_ns=started_ns, connection=connection.identity)
            stage = "publication"
            with self.service.owner_guard(self.owner_epoch):
                latest, _ = self._read(root, original)
            result = publish_owned_node_terminal(root, identity=identity, terminal_receipt=receipt,
                raw_artifact=raw, connection=connection.identity, service_store=self.service,
                current_owner_epoch=self.owner_epoch, expected_revision=latest["revision"])
            emit_node_stage(root, result, "terminal-published", started_ns=started_ns, connection=connection.identity)
            return result
        except Exception as error:
            if getattr(error, "code", None) in {"CON-MSVC-014", "CON-MSVC-018"}:
                stage = "ownership"
            safe = sanitize_node_error(error, stage=stage)
            side_effect = "terminal-evidence-seen" if current and current["node-dispatch"]["receipt-stage"] == "terminal" else "may-have-started"
            raise RecoveryDeferred(safe, phase=safe.details["phase"], side_effect_state=side_effect) from safe
