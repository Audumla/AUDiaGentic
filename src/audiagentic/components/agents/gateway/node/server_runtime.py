"""Standalone host composition over the existing queue, custody and node owners.

The listener is a loopback backend for the deployment's TLS proxy. No recipient
execution, retry scheduler, queue, or grant authority is created here.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue import work_index
from audiagentic.components.agents.gateway.queue.queue import NodeQueuePolicy
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred

from .admission_contract import NodeAdmissionDescriptor
from .admission_owner import NodeAdmissionOwner
from .artifact_reconciliation import NodeTerminalReconciler
from .contracts import conflict, invalid
from .diagnostics import sanitize_node_error
from .drain import NodeDrainEligibility
from .placement import NodeAdmissionPlacement
from .receipt_runtime import NodeReceiptRuntime
from .runner import NodeRunner
from .transport import NodeTransportServer
from .work_protocol import EffectAuthorize, ReceiptReady, ReceiptResume, ReceiptWork

logger = logging.getLogger(__name__)


class NodeQueuePorts:
    """Bind once; short local snapshots only, never locks around owner calls."""

    def __init__(self):
        self._lock = threading.Lock()
        self._runtime: NodeServerRuntime | None = None
        self._bound = False

    def bind(self, runtime: NodeServerRuntime):
        with self._lock:
            if self._bound:
                raise conflict(1, "Node queue ports are already bound")
            self._bound, self._runtime = True, runtime

    def clear(self):
        with self._lock:
            self._runtime = None

    def _snapshot(self):
        with self._lock:
            return self._runtime

    def ready(self, placement: NodeAdmissionPlacement) -> bool:
        runtime = self._snapshot()
        return runtime is not None and runtime.ready(placement)

    def wake(self, node_id: str) -> None:
        runtime = self._snapshot()
        if runtime is not None:
            runtime.wake(node_id)


class NodeServerRuntime:
    def __init__(self, config, service_store, authority, queue, owner_epoch, ports: NodeQueuePorts,
                 *, shutdown_timeout: float = 35, ssl_context=None):
        if type(shutdown_timeout) not in (int, float) or not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise invalid(1, "Node bridge shutdown deadline must be positive and finite")
        self.config, self.service, self.authority, self.queue = config, service_store, authority, queue
        self.owner_epoch, self.ports = owner_epoch, ports
        self.shutdown_timeout = shutdown_timeout
        # None in production: the listener is a loopback backend for the
        # deployment's own TLS-terminating reverse proxy (see module
        # docstring). An explicit context here is for qualification/test use
        # only, terminating TLS in-process instead of through that proxy.
        self._ssl_context = ssl_context
        self.transport = NodeTransportServer(config, authority, gateway_owner_epoch=owner_epoch,
            drain_eligibility=NodeDrainEligibility(config, service_store), configure_work=self._configure)
        self.connections = self.transport.owner
        self.receipts = NodeReceiptRuntime(config, service_store, self.connections,
            on_node_changed=queue.notify_node_changed)
        self.loop = asyncio.new_event_loop()
        self.reconciler = NodeTerminalReconciler(config, service_store, self.connections, self.loop)
        self.runner = NodeRunner(config, service_store, authority, self.connections, self.loop, waiter=self.reconciler)
        self.admission = NodeAdmissionOwner(config, authority, service_store, queue, self.run)
        self._thread: threading.Thread | None = None
        self._condition = threading.Condition()
        self._workers = 0
        self._stopping = False
        self._started = False
        self._closed = False
        self._available = False

    async def _configure(self, connection):
        async def changed():
            await asyncio.to_thread(self._notify_changed, connection.identity.node_id)

        async def receive(frame, work):
            if type(work) is EffectAuthorize:
                return await self.runner.handle_effect_authorize(connection, frame, work)
            if type(work) in {ReceiptWork, ReceiptResume, ReceiptReady}:
                return await self.receipts.handle_work(connection, frame, work)
            raise invalid(1, "Node server received an unsupported work message")

        connection.enable_work(receive, max_artifact_bytes=self.reconciler.max_bytes, on_close=changed)

    def start(self):
        if self._started or self._stopping:
            raise conflict(1, "Node server cannot be started again")
        self._started = True
        self._thread = threading.Thread(target=self._run_loop, name="gateway-node-server", daemon=True)
        starting = None
        try:
            self._thread.start()
            starting = asyncio.run_coroutine_threadsafe(
                self.transport.start(ssl_context=self._ssl_context), self.loop
            )
            starting.result(timeout=15)
            self._available = True
            self.ports.bind(self)
            for grant in self.config.nodes:
                self._notify_changed(grant.node_id)
        except BaseException:
            if starting is not None:
                starting.cancel()
            try:
                self.close()
            except Exception:
                try:
                    logger.warning("Node startup cleanup failed", extra={"code": "IO-AGND-001"})
                except Exception:
                    pass
            raise

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _notify_changed(self, node_id):
        try:
            self.queue.notify_node_changed(node_id)
        except Exception:
            try:
                logger.warning("Node queue notification failed", extra={"code": "IO-AGND-001"})
            except Exception:
                pass

    def ready(self, placement):
        if self._stopping or placement.server_id != self.config.server_id:
            return False
        with self.service.owner_guard(self.owner_epoch):
            def check():
                slot = self.connections.current_slot(placement.node_id)
                return slot is not None and self.connections.is_ready(slot.connection,
                    grant_revision=placement.grant_revision)
            return self.authority.serialize(check)

    def run(self, root, record, *, reconcile_only=False):
        with self._condition:
            if self._stopping or not self._available:
                error = sanitize_node_error(conflict(1, "Node runtime is unavailable"), "transport",
                    "transport-unavailable")
                raise RecoveryDeferred(error, phase=error.details["phase"],
                    side_effect_state="may-have-started" if record.get("node-dispatch") else "not-started")
            self._workers += 1
        try:
            return self.runner(root, record, reconcile_only=reconcile_only)
        finally:
            with self._condition:
                self._workers -= 1
                self._condition.notify_all()

    def enqueue_recovered(self, root, record):
        descriptor = NodeAdmissionDescriptor.from_mapping(record["node-admission"])
        p = record["node-placement"]
        placement = NodeAdmissionPlacement(descriptor.server_id, p["node-id"], p["workspace-id"],
            p["principal-id"], p["server-project-id"], p["grant-revision"])
        if (descriptor.server_id != self.config.server_id
                or self.config.projects.get(placement.server_project_id) != root):
            raise conflict(1, "Node recovery differs from configured storage")
        policy = descriptor.policy
        return self.queue.enqueue_recovered_node(root, record, placement=placement,
            policy=NodeQueuePolicy(policy.profile_id, policy.generation, policy.config_digest,
                policy.pending_capacity, policy.global_capacity, policy.project_capacity),
            runner=self.run, dispatch_owner_epoch=self.owner_epoch, dispatch_service_root=self.service.root)

    def wake(self, node_id):
        if self._stopping or node_id not in {n.node_id for n in self.config.nodes}:
            return
        with self.service.owner_guard(self.owner_epoch):
            entries, _ = work_index.recover_work_index_entries(self.service.root, live_owner_epoch=self.owner_epoch)
            records = []
            for entry in entries:
                if entry.project_root not in self.config.projects.values():
                    continue
                record = store.read_record(entry.project_root, entry.request_id, include_output=False)
                if (record.get("dispatch-owner-epoch") == self.owner_epoch
                        and record["state"] in {"queued", "running"}
                        and (record.get("node-placement") or {}).get("node-id") == node_id
                        and record.get("node-admission") is not None
                        and isinstance(record.get("recovery"), dict)
                        and (record["state"] == "queued" or record.get("recovery-required") is True)):
                    records.append((entry.project_root, record))
        records.sort(key=lambda item: (item[1]["state"] != "running", item[1].get("enqueue-ordinal") or 0,
            item[1].get("created-at") or "", item[1]["request-id"]))
        for root, record in records:
            self.enqueue_recovered(root, record)

    def revoke(self, node_id, *, expected_grant_revision):
        # Existing operation executor calls this port; persist through the same
        # authority first, then refresh/notify off its lock. Retry is idempotent.
        result = self.authority.revoke(node_id, expected_grant_revision=expected_grant_revision)
        if self._started and not self._stopping:
            asyncio.run_coroutine_threadsafe(self.transport.refresh_capability(node_id), self.loop).result(timeout=15)
            self._notify_changed(node_id)
        return result

    def close(self):
        if self._closed:
            return
        self.ports.clear()
        with self._condition:
            self._stopping = True
            self._available = False
        self.queue.shutdown()
        failure = None
        if self.loop.is_running():
            closing = asyncio.run_coroutine_threadsafe(self.transport.close(), self.loop)
            try:
                closing.result(timeout=16)
            except Exception as error:
                closing.cancel()
                failure = error
        deadline = time.monotonic() + self.shutdown_timeout
        with self._condition:
            while self._workers:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise conflict(1, "Node bridge workers have not retired")
                self._condition.wait(remaining)
        if self._thread is not None and self._thread.ident is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise conflict(1, "Node transport loop has not retired")
        if not self.loop.is_closed():
            self.loop.close()
        self._closed = True
        if failure is not None:
            raise failure
