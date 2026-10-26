"""Isolated node producer owner; no listener, scheduler, queue or native retry.

The host claims an execution-node ManagedServiceOwner before opening this core.
It authenticates control channels and revalidates live grants/config before
run_one. Call run_one synchronously outside the control event loop. No lock is
held across the fixed verified worker executor. Control replacement cannot move
the receipt scope while that producer can still write. Worker errors preserve
uncertainty and occupancy; neither disconnect nor handoff grants another effect.
"""

from __future__ import annotations

import json
import math
import os
import threading
import weakref
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from audiagentic.components.agents.contracts.execution_context import (
    MANIFEST_SCHEMA_VERSION,
    ExecutionManifest,
    canonicalize_project_root,
    compute_context_fingerprint,
    compute_prompt_digest,
)
from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
)
from audiagentic.components.agents.gateway.queue import worker
from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig
from audiagentic.foundation.system.managed_process import process_creation_identity
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey

from .authority import NodeConnectionIdentity
from .contracts import (
    CommandIdentity,
    Frame,
    _constant,
    _identifier,
    _integer,
    _pairs,
    canonical_json,
    conflict,
    invalid,
    validate_effect_authorization,
)
from .preparation import (
    PreparationBinding,
    RetainedNodePreparation,
    validate_final_command_preparation,
)
from .receipts import NodeReceiptStore, Receipt, ReceiptCheckpoint, ReceiptOwnerScope

_OPEN_LOCK = threading.Lock()
_OPEN = weakref.WeakValueDictionary()
_CREATE = object()


@dataclass(frozen=True)
class NodeExecutionSnapshot:
    control: NodeConnectionIdentity | None
    capability: str | None
    owner_scope: ReceiptOwnerScope | None
    producer_command_id: str | None
    producer_running: bool
    handoff_pending: bool
    capacity_blocked: bool


def _worker_inputs(identity, preparation, payload, workspace):
    """Consume approved private bundle contracts before committing effect intent."""
    a = preparation.attestation
    try:
        bundle = json.loads(
            preparation._provider_manifest.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
        if (
            not isinstance(bundle, dict)
            or set(bundle)
            != {"version", "kind", "worker-identity", "execution-manifest", "provider-request"}
            or type(bundle["version"]) is not int
            or bundle["version"] != 1
            or bundle["kind"] != "node-worker-preparation"
            or canonical_json(bundle) != preparation._provider_manifest
        ):
            raise invalid(1, "Unsupported private worker preparation bundle")
        expected = WorkerExecutionIdentity.from_mapping(
            bundle["worker-identity"], tier_field="provider-isolation-tier"
        )
        request = WorkerExecuteEnvelope(expected, bundle["provider-request"]).execution_request
        manifest = ExecutionManifest.from_mapping(bundle["execution-manifest"])
        if (
            canonical_json(expected.to_mapping(tier_field="provider-isolation-tier"))
            != canonical_json(bundle["worker-identity"])
            or canonical_json(manifest.to_mapping()) != canonical_json(bundle["execution-manifest"])
            or type(bundle["execution-manifest"]["schema_version"]) is not int
            or bundle["execution-manifest"]["schema_version"] != MANIFEST_SCHEMA_VERSION
        ):
            raise invalid(1, "Private worker identity requires exact contracts")
        root = canonicalize_project_root(str(workspace.root))
        packet = request["packet-data"]
        if (
            not workspace.root.is_dir()
            or canonicalize_project_root(expected.project_root).fingerprint != root.fingerprint
            or expected.worker_id != a.worker_id
            or expected.attempt_epoch != a.attempt_epoch
            or expected.manifest_id != a.manifest_id
            or expected.context_fingerprint != a.context_fingerprint
            or expected.provider_isolation_tier != "full-isolation"
            or manifest.manifest_id != expected.manifest_id
            or manifest.context_fingerprint != expected.context_fingerprint
            or compute_context_fingerprint(manifest.identity) != expected.context_fingerprint
            or manifest.request_id != identity.request_id
            or manifest.identity.project_root != root.fingerprint
            or manifest.identity.component_profile != expected.component_profile
            or manifest.identity.provider_isolation_tier != expected.provider_isolation_tier
            or manifest.identity.execution_profile_id != identity.execution_profile_id
            or manifest.identity.provider_id != a.provider_id
            or manifest.identity.agent_runtime_digest != a.runtime_digest
            or manifest.prompt_digest != compute_prompt_digest(payload["raw-prompt"])
            or not isinstance(a.model_id, str)
            or not a.model_id
            or manifest.identity.model_id != a.model_id
            or request["model-id"] != a.model_id
            or request["model-alias"] != a.model_alias
            or request["provider-id"] != a.provider_id
            or type(request["attempt-epoch"]) is not int
            or not isinstance(packet, dict)
            or packet.get("request-id") != identity.request_id
            or packet.get("working-root") != expected.project_root
            or packet.get("prompt-body") != preparation._rendered_prompt
        ):
            raise conflict(
                1, "Worker inputs differ from exact retained preparation or local workspace"
            )
        return expected, request, frozenset({a.model_id})
    except (KeyError, TypeError, ValueError, UnicodeError, RecursionError, AttributeError):
        raise invalid(1, "Invalid private worker preparation inputs") from None


class NodeExecutionOwner:
    def __init__(self, key, config, service_store, service_owner_epoch, node_epoch):
        if key is not _CREATE:
            raise invalid(1, "Use NodeExecutionOwner.open with a claimed node process")
        self._config = config
        self._service = service_store
        self._service_epoch = service_owner_epoch
        self._node_epoch = node_epoch
        self._lock = threading.Lock()
        self._control = self._last_control = self._bound = None
        self._capability = None
        self._store = None
        self._running = None
        self._pending = set()
        self._retired_gateways = set()

    @classmethod
    def open(
        cls,
        config: SharedGatewayNodeConfig,
        *,
        service_store: ManagedServiceStore,
        service_owner_epoch: str,
        node_epoch: str,
    ) -> NodeExecutionOwner:
        if (
            type(config) is not SharedGatewayNodeConfig
            or type(service_store) is not ManagedServiceStore
        ):
            raise invalid(1, "Execution owner requires typed node config and managed service store")
        _identifier(config.node_id)
        _identifier(config.server_id)
        _identifier(node_epoch)
        _identifier(service_owner_epoch)
        key = ServiceKey("execution-node", config.node_id)
        expected_root = config.state_root / key.scope / key.service_kind / key.service_id
        if (
            not config.state_root.is_absolute()
            or service_store.key != key
            or service_store.root.resolve() != expected_root.resolve()
        ):
            raise conflict(1, "Node process must use its configured local execution-node service")
        owner = cls(_CREATE, config, service_store, service_owner_epoch, node_epoch)
        registry_key = str(config.state_root.resolve())
        with _OPEN_LOCK:
            if registry_key in _OPEN:
                raise conflict(1, "A local execution owner already holds this state root")
            _OPEN[registry_key] = owner
        try:
            with owner._guard():
                scope = NodeReceiptStore.read_owner_scope(
                    config.state_root, expected_node_id=config.node_id
                )
                if scope is not None:
                    owner._store = NodeReceiptStore(root=config.state_root, **scope.__dict__)
            # Read bounded pages under separate short owner fences. No producer
            # is exposed until recovery finishes; no SQL escapes ReceiptStore.
            after = 0
            while owner._store is not None:
                with owner._guard():
                    rows = owner._store.receipts_after(after, limit=100)
                    for receipt in rows:
                        latest = owner._store.get(receipt.identity)
                        if latest.state != "terminal":
                            owner._pending.add(receipt.identity)
                if not rows:
                    break
                after = rows[-1].sequence
            return owner
        except BaseException:
            with _OPEN_LOCK:
                if _OPEN.get(registry_key) is owner:
                    del _OPEN[registry_key]
            raise

    @contextmanager
    def _guard(self):
        # Lock order is lifecycle owner -> producer -> receipt transaction.
        with self._service.owner_guard(self._service_epoch) as record:
            evidence = record.process
            if (
                evidence is None
                or evidence.pid != os.getpid()
                or evidence.owner_epoch != self._service_epoch
                or not evidence.creation_identity
                or process_creation_identity(os.getpid()) != evidence.creation_identity
            ):
                raise conflict(1, "Execution node service does not belong to this live process")
            with self._lock:
                yield

    def _scope(self):
        if self._store is None:
            return None
        return ReceiptOwnerScope(
            self._store.node_id, self._store.node_epoch, self._store.gateway_owner_epoch
        )

    def _snapshot(self):
        return NodeExecutionSnapshot(
            self._control,
            self._capability,
            self._scope(),
            self._running.command_id if self._running else None,
            self._running is not None,
            self._control is not None and self._control != self._bound,
            bool(self._running or self._pending),
        )

    def snapshot(self) -> NodeExecutionSnapshot:
        with self._guard():
            return self._snapshot()

    def observe_connection(
        self,
        connection: NodeConnectionIdentity,
        *,
        capability: str = "active",
    ) -> NodeExecutionSnapshot:
        if type(connection) is not NodeConnectionIdentity or capability not in ("active", "drain"):
            raise invalid(1, "Execution owner requires trusted typed active/drain channel facts")
        for value in (connection.node_id, connection.node_epoch, connection.gateway_owner_epoch):
            _identifier(value)
        _integer(connection.connection_generation)
        if (
            connection.node_id != self._config.node_id
            or connection.node_epoch != self._node_epoch
            or "unbound" in (connection.node_epoch, connection.gateway_owner_epoch)
        ):
            raise conflict(1, "Control connection does not belong to this node process epoch")
        with self._guard():
            previous = self._last_control
            if connection.gateway_owner_epoch in self._retired_gateways:
                raise conflict(1, "Retired gateway control epoch cannot be resurrected")
            if (
                previous is not None
                and previous != connection
                and previous.gateway_owner_epoch == connection.gateway_owner_epoch
                and connection.connection_generation <= previous.connection_generation
            ):
                raise conflict(1, "Stale control connection generation")
            if previous == connection and self._control is None:
                raise conflict(1, "Disconnected channel cannot be resurrected")
            if (
                previous is not None
                and previous.gateway_owner_epoch != connection.gateway_owner_epoch
            ):
                self._retired_gateways.add(previous.gateway_owner_epoch)
            self._control = self._last_control = connection
            self._capability = capability
            return self._snapshot()

    def connection_lost(self, connection: NodeConnectionIdentity) -> NodeExecutionSnapshot:
        if type(connection) is not NodeConnectionIdentity:
            raise invalid(1, "Disconnect requires trusted typed connection facts")
        with self._guard():
            if self._control == connection:
                self._control = None
                self._capability = None
            return self._snapshot()

    def handoff_if_quiescent(self) -> NodeExecutionSnapshot:
        with self._guard():
            if self._running is not None or self._control is None:
                return self._snapshot()
            control = self._control
            scope = ReceiptOwnerScope(
                control.node_id, control.node_epoch, control.gateway_owner_epoch
            )
            if self._store is None:
                self._store = NodeReceiptStore(root=self._config.state_root, **scope.__dict__)
            elif self._scope() != scope:
                self._store.advance_epoch(
                    node_epoch=scope.node_epoch, gateway_owner_epoch=scope.gateway_owner_epoch
                )
                self._store = NodeReceiptStore(root=self._config.state_root, **scope.__dict__)
            self._bound = control
            return self._snapshot()

    def acknowledge(self, frame: Frame) -> ReceiptCheckpoint | None:
        if type(frame) is not Frame or frame.type != "reconcile-result":
            raise invalid(1, "Execution owner ACK requires reconcile-result")
        with self._guard():
            if self._control is None or self._control != self._bound or self._store is None:
                return None  # Caller must replay; no buffering and no acknowledged progress.
            return self._store.acknowledge(
                frame, expected_server_id=self._config.server_id, current_connection=self._control
            )

    def receipts_after(self, sequence: int = 0, *, limit: int = 100) -> tuple[Receipt, ...]:
        """Evidence replay also includes old epochs; never authorizes execution."""
        with self._guard():
            return () if self._store is None else self._store.receipts_after(sequence, limit=limit)

    def run_one(
        self,
        identity: CommandIdentity,
        *,
        preparation: RetainedNodePreparation,
        command_payload: Mapping[str, Any],
        current_binding: PreparationBinding,
        authorization_request: Frame,
        authorization_reply: Frame,
        timeout_seconds: float,
    ) -> Receipt:
        """Run one newly authorized intent. Caller serializes live effect grants.

        current_binding is trusted caller state, not copied from the command.
        No callback can supply execution proof. Failures after intent are retained
        for reconciliation; repeated calls cannot execute an existing intent.
        """
        if (
            type(identity) is not CommandIdentity
            or type(preparation) is not RetainedNodePreparation
            or type(current_binding) is not PreparationBinding
            or type(authorization_request) is not Frame
            or type(authorization_reply) is not Frame
            or isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise invalid(1, "Execution requires typed correlated inputs and bounded timeout")
        # Detach mutable caller input before validating or retaining durable bytes.
        raw = canonical_json(command_payload)
        payload = json.loads(raw)
        validate_final_command_preparation(
            preparation, payload, identity, current_binding=current_binding
        )
        workspace = self._config.workspaces.get(identity.workspace_id)
        if workspace is None or identity.execution_profile_id not in workspace.execution_profiles:
            raise conflict(1, "Command workspace/profile is not locally configured")
        expected, request, allowed_models = _worker_inputs(
            identity, preparation, payload, workspace
        )
        with self._guard():
            live = self._control
            if (
                live is None
                or live != self._bound
                or self._capability != "active"
                or self._store is None
                or self._running is not None
                or (
                    identity.node_id,
                    identity.node_epoch,
                    identity.gateway_owner_epoch,
                    identity.connection_generation,
                )
                != (
                    live.node_id,
                    live.node_epoch,
                    live.gateway_owner_epoch,
                    live.connection_generation,
                )
                or self._pending - {identity}
            ):
                raise conflict(
                    1, "Node producer is occupied, disconnected, draining or awaiting handoff"
                )
            validate_effect_authorization(
                identity,
                authorization_request,
                authorization_reply,
                connection_generation=live.connection_generation,
            )
            store = self._store
            try:
                receipt = store.prepare(identity, raw)
            except BaseException:
                # A persistence exception may follow commit. Retain occupancy
                # rather than treating an unknown prepare outcome as absence.
                self._pending.add(identity)
                raise
            if receipt.state != "prepared":
                raise conflict(1, "Existing effect or terminal is reconciliation-only")
            # Pending is recorded before a potentially uncertain durable write.
            self._pending.add(identity)
            if not store.effect_intent(
                identity,
                authorization_request,
                authorization_reply,
                connection_generation=live.connection_generation,
            ):
                raise conflict(1, "Existing intent never permits a second worker call")
            self._running = identity
        try:
            proof = worker.execute_verified_isolated_provider_turn(
                identity=expected,
                execution_request=request,
                allowed_model_ids=allowed_models,
                timeout_seconds=timeout_seconds,
            )
            with self._guard():
                if self._running != identity or self._store is not store:
                    raise conflict(1, "Producer ownership changed before terminal persistence")
                receipt = store.terminal_from_worker_result(
                    identity, preparation=preparation, proof=proof
                )
                self._pending.discard(identity)
                return receipt
        finally:
            # No producer writes follow this barrier, including worker-error paths.
            # Do not reacquire a replaced service lease just to release local state.
            with self._lock:
                if self._running == identity:
                    self._running = None
