"""Process-owned recipient for opt-in node work; not a listener or scheduler.

The host retains this object across socket reconnects and must keep its event
loop alive until wait_producer completes. Cancellation of a socket dispatcher
never cancels the retained producer, implies unsent, or authorizes another run.
Preparation and execution use asyncio's existing thread offload, no owned pool.
Grant authentication/revocation remain the channel/central owner's authority.
Historical ACK/artifact handlers are installed; receipt sending is not.
"""

from __future__ import annotations

import asyncio
import base64
import math
from dataclasses import dataclass, field

from ..service.shared_config import SharedGatewayNodeConfig
from .connection import NodeConnection
from .contracts import conflict, invalid, validate_effect_authorization
from .execution_owner import NodeExecutionOwner
from .local_preparation import NodeLocalPreparer
from .preparation import RetainedNodePreparation, validate_final_command_preparation
from .source_workspace import validate_recipient_workspace
from .work_protocol import (
    ArtifactGet,
    CommandWork,
    EffectAuthorized,
    EffectDenied,
    PrepareWork,
    ReceiptAckWork,
    parse_work_frame,
)


@dataclass(frozen=True)
class RecipientFailure:
    code: str
    reason_code: str


@dataclass(frozen=True)
class _Accepted:
    work: PrepareWork = field(repr=False)
    preparation: RetainedNodePreparation = field(repr=False)
    connection: NodeConnection = field(repr=False)


class NodeRecipientRuntime:
    """One accepted preparation and one process-retained producer task."""

    def __init__(
        self,
        config: SharedGatewayNodeConfig,
        owner: NodeExecutionOwner,
        *,
        preparer: NodeLocalPreparer | None = None,
        max_artifact_bytes: int = 1024 * 1024,
        authorization_timeout_seconds: float = 10,
    ):
        if type(config) is not SharedGatewayNodeConfig or type(owner) is not NodeExecutionOwner:
            raise invalid(1, "Recipient requires configured process-owned execution owner")
        if preparer is not None and type(preparer) is not NodeLocalPreparer:
            raise invalid(1, "Recipient requires the local preparation owner")
        if type(max_artifact_bytes) is not int or max_artifact_bytes <= 0:
            raise invalid(1, "Recipient artifact bound must be positive")
        if (type(authorization_timeout_seconds) not in (int, float)
                or not math.isfinite(authorization_timeout_seconds) or authorization_timeout_seconds <= 0):
            raise invalid(1, "Recipient timeouts must be positive finite values")
        self._config = config
        self._owner = owner
        self._preparer = preparer or NodeLocalPreparer(config)
        self._max_artifact_bytes = max_artifact_bytes
        self._authorization_timeout = authorization_timeout_seconds
        self._configure_lock = asyncio.Lock()
        self._admission_gate = asyncio.Lock()
        self._state_revision = 0
        self._ready_emitted = None
        self._connection = None
        self._accepted = None
        self._preparing = None
        self._authorizing = False
        self._producer = None
        # Notification only: clear before rereading the owner's durable cursor.
        # Valid duplicate ACKs may wake a waiter; deferred ACKs never signal.
        self.acknowledgement_event = asyncio.Event()
        # One process-local notification for admission, cleanup and producer
        # transitions. A set event alone is neither a new cycle nor ACK proof.
        self.state_changed_event = asyncio.Event()
        self.failure: RecipientFailure | None = None

    @property
    def execution_owner(self) -> NodeExecutionOwner:
        """The sole process-owned receipt/effect owner; no alternate store."""
        return self._owner

    @property
    def current_connection(self) -> NodeConnection | None:
        """For later receipt pumping, never an execution grant."""
        return self._connection

    @property
    def producer_pending(self) -> bool:
        return self._producer is not None and not self._producer.done()

    def _state_changed(self):
        self._state_revision += 1
        self.state_changed_event.set()

    def _locally_quiescent(self, connection):
        return (
            self._connection is connection
            and connection.close_reason is None
            and connection.failure is None
            and connection.capability == "active"
            and self._accepted is None
            and self._preparing is None
            and not self._authorizing
            and not self.producer_pending
        )

    async def emit_receipt_ready(self, connection, checkpoint):
        """One hint per quiescent cycle, serialized with local work admission.

        The sender has resumed and drained through this durable ACK. Snapshot
        I/O is outside the local gate; the revision recheck fences intervening
        admission. Neither the hint nor cursor progress proves native completion.
        """
        async with self._admission_gate:
            if not self._locally_quiescent(connection):
                return False
            revision = self._state_revision
            if self._ready_emitted == (connection, revision):
                return False
        snapshot = await asyncio.to_thread(self._owner.snapshot)
        current_checkpoint = await asyncio.to_thread(self._owner.receipt_checkpoint)
        scope = snapshot.owner_scope
        c = connection.identity
        if (
            current_checkpoint != checkpoint
            or snapshot.control != c or snapshot.capability != "active"
            or snapshot.capacity_blocked or snapshot.producer_running or snapshot.handoff_pending
            or scope is None
            or (scope.node_id, scope.node_epoch, scope.gateway_owner_epoch)
            != (c.node_id, c.node_epoch, c.gateway_owner_epoch)
        ):
            return False
        async with self._admission_gate:
            if (not self._locally_quiescent(connection) or self._state_revision != revision
                    or self._ready_emitted == (connection, revision)):
                return False
            # send_work has its own bounded send deadline; no service, grant,
            # thread or native-execution lock is held here.
            # Reserve the attempt before awaiting transport: cancellation or
            # an uncertain send cannot manufacture more hints in this cycle.
            self._ready_emitted = (connection, revision)
            await connection.send_work("reconcile", {
                "kind": "receipt-ready",
                "log-incarnation-id": checkpoint.log_incarnation_id,
                "through-sequence": checkpoint.through_sequence,
                "through-receipt-sha256": checkpoint.through_receipt_sha256,
            })
            return True

    @staticmethod
    def _safe_code(error):
        code = getattr(error, "code", None)
        return code if code in {"VAL-AGND-001", "CON-AGND-001", "IO-AGND-001"} else "IO-AGND-001"

    def _remember(self, error, reason):
        if self.failure is None:
            self.failure = RecipientFailure(self._safe_code(error), reason)

    async def _live(self, connection, *, active=True):
        if (
            self._connection is not connection
            or connection.close_reason is not None
            or connection.failure is not None
            or (active and connection.capability != "active")
        ):
            raise conflict(1, "Recipient channel is not current and active")
        await asyncio.to_thread(
            self._owner.observe_connection, connection.identity, capability=connection.capability
        )
        if (
            self._connection is not connection
            or connection.close_reason is not None
            or connection.failure is not None
            or (active and connection.capability != "active")
        ):
            raise conflict(1, "Recipient channel changed during owner observation")

    async def configure_work(self, connection: NodeConnection) -> None:
        """Pass to NodeTransportClient(configure_work=...); install before start."""
        if type(connection) is not NodeConnection or connection.role != "node":
            raise invalid(1, "Recipient requires a node-side work channel")

        async def closed():
            if connection.failure_summary is not None:
                self._remember(connection.failure_summary, "channel-failed")
            # Stale close callbacks cannot erase a newer connection. No producer
            # cancellation, native kill or inference about effects occurs here.
            async with self._admission_gate:
                if self._connection is connection:
                    self._connection = None
                    if not self.producer_pending:
                        self._accepted = None
                    self._state_changed()
            try:
                await asyncio.to_thread(self._owner.connection_lost, connection.identity)
            except Exception as error:
                self._remember(error, "owner-fenced")

        async with self._configure_lock:
            if self._connection is not None and self._connection.identity == connection.identity:
                raise conflict(1, "A recipient channel already owns this generation")
            connection.enable_work(
                lambda frame, work: self._handle(connection, frame, work),
                max_artifact_bytes=self._max_artifact_bytes,
                on_close=closed,
            )
            # Associate before any await so partial-configuration close cleanup
            # finds the exact connection; stale callbacks never erase a successor.
            async with self._admission_gate:
                self._connection = connection
                if not self.producer_pending:
                    self._accepted = None
                self._state_changed()

            def observe():
                self._owner.observe_connection(
                    connection.identity, capability=connection.capability
                )
                self._owner.handoff_if_quiescent()

            publication = asyncio.create_task(asyncio.to_thread(observe))
            try:
                await asyncio.shield(publication)
            except asyncio.CancelledError:
                try:
                    await publication  # Fence the publication before notifying loss.
                finally:
                    await connection.close()
                raise
            except Exception as error:
                self._remember(error, "owner-fenced")
                await connection.close()
                raise conflict(1, "Recipient configuration rejected") from None

    async def _handle(self, connection, frame, work):
        reason = "command-correlation"
        try:
            # Consume actual wire facts even when invoked by a custom dispatcher.
            parsed = parse_work_frame(
                frame,
                role="node",
                current_connection=connection.identity,
                capability=connection.capability,
                max_artifact_bytes=self._max_artifact_bytes,
            )
            if parsed != work:
                raise conflict(1, "Recipient work differs from its received frame")
            historical = type(parsed) in (ReceiptAckWork, ArtifactGet)
            await self._live(connection, active=not historical)
            if type(work) is ReceiptAckWork:
                reason = "receipt-ack"
                checkpoint = await asyncio.to_thread(self._owner.acknowledge, frame)
                if checkpoint is not None:
                    self.acknowledgement_event.set()
            elif type(work) is ArtifactGet:
                reason = "artifact-read"
                chunk = await asyncio.to_thread(
                    self._owner.read_artifact_chunk,
                    work.identity,
                    work.artifact_sha256,
                    work.offset,
                    work.limit,
                    max_total_bytes=self._max_artifact_bytes,
                )
                await self._live(connection, active=False)
                await connection.send_work(
                    "reconcile-result",
                    {
                        "kind": "artifact-chunk",
                        "in-reply-to": frame.message_id,
                        "identity": work.identity.to_mapping(),
                        "artifact-sha256": chunk.artifact_sha256,
                        "artifact-kind": chunk.artifact_kind,
                        "offset": chunk.offset,
                        "total-bytes": chunk.total_bytes,
                        "data": base64.b64encode(chunk.data).decode("ascii"),
                        "eof": chunk.eof,
                    },
                )
            elif type(work) is PrepareWork:
                reason = "preparation-rejected"
                await self._prepare(connection, work)
            elif type(work) is CommandWork:
                await self._command(connection, work)
            else:
                raise invalid(1, "Recipient work kind is not integrated")
        except asyncio.CancelledError:
            raise  # Socket cancellation cannot propagate through the producer shield.
        except Exception as error:
            self._remember(error, reason)
            if type(work) is PrepareWork:
                await connection.send_work(
                    "reconcile-result",
                    {
                        "kind": "prepare-rejected",
                        "in-reply-to": frame.message_id,
                        "code": self._safe_code(error),
                    },
                )
                return
            raise conflict(1, "Recipient work rejected", reason_code=reason) from None

    async def _prepare(self, connection, work):
        c, b = connection.identity, work.binding

        def materialize():
            if (
                (b.node_id, b.node_epoch, b.gateway_owner_epoch, b.connection_generation)
                != (c.node_id, c.node_epoch, c.gateway_owner_epoch, c.connection_generation)
                or b.grant_revision != connection.grant_revision
                or b.workspace_id != work.source_workspace.workspace_id
            ):
                raise conflict(1, "Preparation binding differs from current channel")
            if self._owner.snapshot().capacity_blocked:
                raise conflict(1, "Recipient producer capacity is occupied")
            validate_recipient_workspace(
                self._config, work.source_workspace, caller_root=work.caller_root
            )
            return self._preparer.prepare(
                binding=b, semantic=work.semantic, agent_id=work.agent_id,
                raw_prompt=work.raw_prompt, worker_id=work.worker_id,
                attempt_epoch=work.attempt_epoch, source=work.source,
                metadata=work.metadata,
            )

        async with self._admission_gate:
            if not self._locally_quiescent(connection):
                raise conflict(1, "Recipient preparation slot is occupied")
            task = asyncio.create_task(asyncio.to_thread(materialize))
            self._preparing = task
            self._state_changed()
        task.add_done_callback(self._consume_preparation)
        try:
            preparation = await asyncio.shield(task)
            await self._live(connection)
            if (
                type(preparation) is not RetainedNodePreparation
                or preparation.attestation.binding != b
                or preparation.attestation.semantic != work.semantic
                or preparation.attestation.worker_id != work.worker_id
                or preparation.attestation.attempt_epoch != work.attempt_epoch
                or connection.grant_revision != b.grant_revision
            ):
                raise conflict(1, "Local preparation differs from accepted work")
            await asyncio.to_thread(
                validate_recipient_workspace, self._config, work.source_workspace,
                caller_root=work.caller_root,
            )
            await self._live(connection)
            async with self._admission_gate:
                if self._connection is not connection or connection.close_reason is not None:
                    raise conflict(1, "Preparation channel changed before acceptance")
                self._accepted = _Accepted(work, preparation, connection)
                self._state_changed()
            await connection.send_work("reconcile-result", {
                "kind": "prepared", "in-reply-to": work.message_id,
                "attestation": preparation.attestation.to_mapping(),
            })
        except Exception as error:
            self._remember(error, "preparation-rejected")
            async with self._admission_gate:
                if self._accepted is not None and self._accepted.work is work:
                    self._accepted = None
            await connection.send_work("reconcile-result", {
                "kind": "prepare-rejected", "in-reply-to": work.message_id,
                "code": self._safe_code(error),
            })
        finally:
            if task.done():
                await self._release_preparation(task)
            else:
                # A disconnected dispatcher cannot cancel thread materialization
                # or advertise a free slot until that retained work actually ends.
                task.add_done_callback(lambda done: asyncio.create_task(self._release_preparation(done)))

    async def _release_preparation(self, task):
        async with self._admission_gate:
            if self._preparing is task:
                self._preparing = None
                self._state_changed()

    def _consume_preparation(self, task):
        if not task.cancelled() and task.exception() is not None:
            self._remember(task.exception(), "preparation-rejected")

    async def _command(self, connection, work):
        async with self._admission_gate:
            accepted = self._accepted
            if (
                accepted is None or accepted.connection is not connection
                or self.producer_pending or self._authorizing
                or self._connection is not connection or connection.close_reason is not None
                or connection.capability != "active"
            ):
                raise conflict(1, "Command has no available retained preparation")
            self._authorizing = True
            self._state_changed()
        started = False
        try:
            snapshot = await asyncio.to_thread(self._owner.snapshot)
            await self._live(connection)
            if snapshot.capacity_blocked or self._accepted is not accepted:
                raise conflict(1, "Command preparation or producer capacity changed")
            validate_final_command_preparation(
                accepted.preparation,
                work.command_payload,
                work.identity,
                current_binding=accepted.work.binding,
            )
            if connection.grant_revision != accepted.work.binding.grant_revision:
                raise conflict(1, "Retained grant revision changed")
            sent, reply, message = await connection.request_work(
                "effect-authorize",
                {"identity": work.identity.to_mapping()},
                reply_types=(EffectAuthorized, EffectDenied),
                timeout=self._authorization_timeout,
            )
            await self._live(connection)
            if (
                self._accepted is not accepted
                or connection.grant_revision != accepted.work.binding.grant_revision
            ):
                raise conflict(1, "Preparation or grant changed during effect authorization")
            if type(message) is not EffectAuthorized:
                raise conflict(1, "Effect authorization was denied")
            validate_effect_authorization(
                work.identity,
                sent,
                reply,
                connection_generation=connection.identity.connection_generation,
            )
            # Exact immutable channel Frames go to the sole durable producer.
            async with self._admission_gate:
                if (self._connection is not connection or connection.close_reason is not None
                        or connection.capability != "active" or self._accepted is not accepted):
                    raise conflict(1, "Command channel changed before producer startup")
                task = asyncio.create_task(self._produce(accepted, work, sent, reply))
                self._producer = task
                started = True
                self._state_changed()
            # The process retains this task; the one channel dispatcher must
            # remain free for receipt ACKs and artifact requests. Shutdown uses
            # wait_producer(), never cancellation of this independently owned work.
        finally:
            async with self._admission_gate:
                self._authorizing = False
                if not started and self._accepted is accepted:
                    self._accepted = None
                self._state_changed()

    async def _produce(self, accepted, work, sent, reply):
        try:
            await self._live(accepted.connection)
            if accepted.connection.grant_revision != accepted.work.binding.grant_revision:
                raise conflict(1, "Grant changed before producer admission")
            return await asyncio.to_thread(
                self._owner.run_one,
                work.identity,
                preparation=accepted.preparation,
                command_payload=work.command_payload,
                current_binding=accepted.work.binding,
                source_workspace=accepted.work.source_workspace,
                caller_root=accepted.work.caller_root,
                authorization_request=sent,
                authorization_reply=reply,
            )
        except Exception as error:
            self._remember(error, "producer-failed")
            return None  # Receipt state remains authoritative; never infer unsent.
        finally:
            async with self._admission_gate:
                if self._accepted is accepted:
                    self._accepted = None
            try:
                await asyncio.to_thread(self._owner.handoff_if_quiescent)
            except Exception as error:
                self._remember(error, "owner-fenced")
            finally:
                async with self._admission_gate:
                    self._state_changed()

    async def wait_producer(self):
        """Process shutdown/reconnect owner may await; caller cancellation is shielded."""
        task = self._producer
        return None if task is None else await asyncio.shield(task)
