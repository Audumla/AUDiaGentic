"""Authenticated historical receipt ingress over existing custody owners.

Slot validation admits a receipt; it is not a slot lease across disk I/O.
Replacement after admission may leave durable custody without an ACK. Only the
current connection can send that ACK. No grant lock spans custody, network or
publication, and the checkpoint owner acquires the service guard itself.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from weakref import ref

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.observability import record_timeline_event

from .checkpoints import CanonicalReceiptTarget, NodeReceiptCheckpoints
from .connection import NodeConnection
from .contracts import conflict, invalid
from .diagnostics import sanitize_node_error
from .observability import emit_node_stage
from .occupancy import NodeOccupancy
from .work_protocol import ReceiptReady, ReceiptResume, ReceiptWork, parse_work_frame

logger = logging.getLogger(__name__)

class NodeReceiptRuntime:
    """One bounded checkpoint-owner cache, not an executor or result store."""

    def __init__(self, config, service_store, connections, *, on_node_changed=None):
        authority = connections.authority
        if (service_store.key != GATEWAY_SERVICE_KEY
                or authority.service_root != service_store.root.resolve()
                or authority.path != config.config_path):
            raise invalid(1, "Receipt ingress requires the same service and configuration owners")
        self.config, self.service, self.connections = config, service_store, connections
        self.authority, self.owner_epoch = authority, connections.gateway_owner_epoch
        self.on_node_changed = on_node_changed
        self.occupancy = NodeOccupancy(tuple(config.projects.values()), server_id=config.server_id)
        self._streams = {}  # Configured node IDs only; do not retain closed socket buffers.
        self.custody_changed = asyncio.Event()  # Wake hint; canonical state is authoritative.

    def _current(self, connection, *, stream=False):
        """Run under the existing authority serialization, never a network wait."""
        slot = self.connections.current_slot(connection.identity.node_id)
        if (slot is None or slot.connection is not connection or slot.identity != connection.identity
                or slot.capability not in {"active", "drain"}
                or connection.close_reason is not None or connection.failure is not None):
            raise conflict(1, "Historical receipt channel is no longer current", reason_code="receipt-channel-replaced")
        if not stream:
            return True
        node = slot.identity.node_id
        if node not in {grant.node_id for grant in self.config.nodes}:
            raise conflict(1, "Receipt node is outside configured enrollment", reason_code="receipt-target-mismatch")
        previous = self._streams.get(node)
        if previous is None or previous[0]() is not connection:
            previous = (ref(connection), NodeReceiptCheckpoints(self.service, server_id=self.config.server_id, node_id=node))
            self._streams[node] = previous
        return previous[1]

    def _target(self, identity):
        matches = []
        for root in dict.fromkeys(self.config.projects.values()):
            try:
                record = store.read_record(root, identity.request_id, include_output=False)
            except AudiaGenticError as error:
                if error.code != "RES-AGW-001":
                    raise
            else:
                matches.append((root, record))
        if len(matches) != 1:
            raise conflict(1, "Receipt requires one original canonical request", reason_code="receipt-target-mismatch")
        root, record = matches[0]
        dispatch, placement = record.get("node-dispatch"), record.get("node-placement")
        if (not isinstance(dispatch, dict) or dispatch.get("identity") != identity.to_mapping()
                or not isinstance(placement, dict) or placement.get("node-id") != identity.node_id
                or placement.get("workspace-id") != identity.workspace_id
                or placement.get("grant-revision") != identity.grant_revision
                or self.config.projects.get(placement.get("server-project-id")) != root
                or record.get("dispatch-owner-epoch") != self.owner_epoch
                or record.get("execution-profile-id") != identity.execution_profile_id
                or not record.get("dispatch-service-root")
                or Path(record["dispatch-service-root"]).resolve() != self.service.root.resolve()):
            raise conflict(1, "Receipt differs from its original owned request", reason_code="receipt-target-mismatch")
        return root, record

    def _accept(self, connection, work):
        # The precheck is the historical admission linearization point, not a
        # fresh-effect grant. The service guard below is owned by accept itself.
        checkpoint = self.authority.serialize(lambda: self._current(connection, stream=True))
        applied = []
        started_ns = time.monotonic_ns()

        def resolve(identity):
            root, record = self._target(identity)
            target = CanonicalReceiptTarget(root, self.owner_epoch, record["worker-id"],
                record["attempt-epoch"], record["revision"])
            applied.append((root, identity.request_id))
            return target

        ack = checkpoint.accept(work.receipt, log_incarnation_id=work.log_incarnation_id,
                                expected_epoch=self.owner_epoch, resolve_target=resolve)
        # Older duplicate bodies are deliberately not resolved or published.
        # A real C+1 target is known here; diagnostic failure cannot undo custody.
        for root, request_id in applied:
            try:
                record = store.read_record(root, request_id, include_output=False)
            except Exception:
                try:
                    logger.warning("Node receipt custody retained; stage projection unavailable",
                                   extra={"request-id": request_id})
                except Exception:
                    pass  # A secondary sink fault cannot reverse committed custody.
                continue
            emit_node_stage(root, record, "receipt-committed", started_ns=started_ns, connection=connection.identity)
        return ack, bool(applied)

    def _resume(self, connection, work):
        checkpoint = self.authority.serialize(lambda: self._current(connection, stream=True))
        return checkpoint.resume_cursor(log_incarnation_id=work.log_incarnation_id, expected_epoch=self.owner_epoch)

    def _ready_current(self, connection, *, stream=False):
        checkpoint = self._current(connection, stream=stream)
        slot = self.connections.current_slot(connection.identity.node_id)
        if (slot.capability != "active" or connection.capability != "active"
                or slot.grant_revision != connection.grant_revision):
            raise conflict(1, "Readiness requires the current active grant", reason_code="ready-channel-invalid")
        return checkpoint

    def _ready(self, connection, work):
        # Checkpoint methods take their own service guard. Never nest that guard
        # or hold authority across cursor I/O. The later publication is a hint,
        # not an effect grant or a cursor write/ACK.
        checkpoint = self.authority.serialize(lambda: self._ready_current(connection, stream=True))
        cursor = checkpoint.resume_cursor(log_incarnation_id=work.log_incarnation_id, expected_epoch=self.owner_epoch)
        if cursor != (work.through_sequence, work.through_receipt_sha256):
            raise conflict(1, "Readiness differs from durable custody", reason_code="receipt-cursor-mismatch")

        def publish():
            self._ready_current(connection)
            previous = self.connections.is_ready(connection, grant_revision=connection.grant_revision)
            if not self.connections.mark_ready(connection, grant_revision=connection.grant_revision):
                raise conflict(1, "Readiness grant or live channel changed", reason_code="ready-channel-invalid")
            return not previous

        with self.service.owner_guard(self.owner_epoch):
            # Canonical disk reads stay owner-fenced, outside the grant lock.
            # This is a scheduling hint; effect admission rechecks occupancy.
            if self.occupancy.snapshot().occupied(self.config.server_id, connection.identity.node_id):
                raise conflict(1, "Canonical work still holds node capacity", reason_code="capacity-occupied")
            return self.authority.serialize(publish)

    def _notify(self, connection, work):
        """Optional synchronous host wake hint; off-loop and outside ALL locks."""
        if self.on_node_changed is None:
            return
        try:
            self.on_node_changed(connection.identity.node_id)
        except Exception as error:
            safe = sanitize_node_error(error, stage="notification", reason="node-notification-failed")
            try:
                self._trace_failure(connection, work, safe)
            except Exception:
                pass  # Notification and secondary diagnostics cannot undo custody/readiness.

    def _trace_failure(self, connection, work, error):
        # Unresolved/gapped receipts may have no trusted request target. Use
        # the existing service resource timeline, never peer-supplied roots.
        record_timeline_event(self.service.timeline_path, component="agents", resource_kind="managed-service",
            resource_id=self.service.key.service_id, event="node.receipt-ingress-deferred", attributes={
                "node-id": connection.identity.node_id,
                "connection-generation": connection.identity.connection_generation,
                "log-incarnation-id": work.log_incarnation_id,
                "receipt-sequence": work.receipt.sequence if type(work) is ReceiptWork else work.through_sequence,
                "error-code": error.code, "phase": error.details["phase"],
                "reason-code": error.details["reason-code"],
            })

    async def handle_work(self, connection, frame, work):
        """Dispatch authenticated custody/readiness; all disk/locks off-loop."""
        if type(connection) is not NodeConnection or connection.role != "gateway":
            raise invalid(1, "Receipt ingress requires a gateway-side channel")
        parsed = parse_work_frame(frame, role="gateway", current_connection=connection.identity,
                                  capability=connection.capability, max_artifact_bytes=1024 * 1024)
        if type(parsed) not in {ReceiptWork, ReceiptResume, ReceiptReady} or parsed != work:
            raise invalid(1, "Receipt ingress differs from authenticated work")
        changed = False
        try:
            if type(work) is ReceiptReady:
                changed = await asyncio.to_thread(self._ready, connection, work)
                if changed:
                    self.custody_changed.set()
                return None  # Readiness is not an ACK or an authorization exchange.
            if type(work) is ReceiptResume:
                sequence, digest = await asyncio.to_thread(self._resume, connection, work)
                payload = {"kind": "receipt-resume", "in-reply-to": frame.message_id,
                    "log-incarnation-id": work.log_incarnation_id, "after-sequence": sequence,
                    "after-receipt-sha256": digest}
            else:
                ack, changed = await asyncio.to_thread(self._accept, connection, work)
                if changed:
                    self.custody_changed.set()
                payload = ack.payload(connection_generation=connection.identity.connection_generation)
            # Replacement never erases custody; it suppresses the stale reply.
            await asyncio.to_thread(self.authority.serialize, lambda: self._current(connection))
            return await connection.send_work("reconcile-result", payload)
        except Exception as error:
            # A failed cursor write remains poisoned in its stream owner. No
            # positive reply, reset, execution retry or lifecycle failure here.
            stage = "ownership" if getattr(error, "code", None) in {"CON-MSVC-014", "CON-MSVC-018"} else ("ready" if type(work) is ReceiptReady else "receipt")
            safe = sanitize_node_error(error, stage=stage)
            try:
                await asyncio.to_thread(self._trace_failure, connection, work, safe)
            except Exception:
                pass  # Preserve the primary sanitized failure, not a log-sink error.
            raise safe from None
        finally:
            if changed:
                try:
                    await asyncio.to_thread(self._notify, connection, work)
                except Exception:
                    # Even executor submission can fail. Do not replace the
                    # primary error, sent ACK or committed readiness/custody.
                    try:
                        logger.warning("Node change notification unavailable; canonical state retained")
                    except Exception:
                        pass
