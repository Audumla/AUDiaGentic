"""Process-owned recipient for opt-in node work; not a listener or scheduler.

The host retains this object across socket reconnects and must keep its event
loop alive until wait_producer completes. Cancellation of a socket dispatcher
never cancels the retained producer, implies unsent, or authorizes another run.
Preparation and execution use asyncio's existing thread offload, no owned pool.
Grant authentication/revocation remain the channel/central owner's authority.
Receipt/artifact pumping is deliberately not installed here.
"""

from __future__ import annotations

import asyncio
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
    CommandWork,
    EffectAuthorized,
    EffectDenied,
    PrepareWork,
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
        default_timeout_seconds: float = 300,
    ):
        if type(config) is not SharedGatewayNodeConfig or type(owner) is not NodeExecutionOwner:
            raise invalid(1, "Recipient requires configured process-owned execution owner")
        if preparer is not None and type(preparer) is not NodeLocalPreparer:
            raise invalid(1, "Recipient requires the local preparation owner")
        if type(max_artifact_bytes) is not int or max_artifact_bytes <= 0:
            raise invalid(1, "Recipient artifact bound must be positive")
        for value in (authorization_timeout_seconds, default_timeout_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise invalid(1, "Recipient timeouts must be positive finite values")
        self._config = config
        self._owner = owner
        self._preparer = preparer or NodeLocalPreparer(config)
        self._max_artifact_bytes = max_artifact_bytes
        self._authorization_timeout = authorization_timeout_seconds
        self._default_timeout = default_timeout_seconds
        self._configure_lock = asyncio.Lock()
        self._connection = None
        self._accepted = None
        self._preparing = None
        self._authorizing = False
        self._producer = None
        self.failure: RecipientFailure | None = None

    @property
    def current_connection(self) -> NodeConnection | None:
        """For later receipt pumping, never an execution grant."""
        return self._connection

    @property
    def producer_pending(self) -> bool:
        return self._producer is not None and not self._producer.done()

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
            if self._connection is connection:
                self._connection = None
                if not self.producer_pending:
                    self._accepted = None
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
            self._connection = connection
            if not self.producer_pending:
                self._accepted = None

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
            await self._live(connection)
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
            if type(work) is PrepareWork:
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
        if (
            self.producer_pending
            or self._authorizing
            or (self._preparing is not None and not self._preparing.done())
            or self._accepted is not None
        ):
            raise conflict(1, "Recipient preparation slot is occupied")
        c, b = connection.identity, work.binding
        if (
            (b.node_id, b.node_epoch, b.gateway_owner_epoch, b.connection_generation)
            != (c.node_id, c.node_epoch, c.gateway_owner_epoch, c.connection_generation)
            or b.grant_revision != connection.grant_revision
            or b.workspace_id != work.source_workspace.workspace_id
        ):
            raise conflict(1, "Preparation binding differs from current channel")

        def materialize():
            if self._owner.snapshot().capacity_blocked:
                raise conflict(1, "Recipient producer capacity is occupied")
            # Must precede ANY catalog/materialization/provider-preflight read.
            validate_recipient_workspace(
                self._config, work.source_workspace, caller_root=work.caller_root
            )
            return self._preparer.prepare(
                binding=b,
                semantic=work.semantic,
                agent_id=work.agent_id,
                raw_prompt=work.raw_prompt,
                worker_id=work.worker_id,
                attempt_epoch=work.attempt_epoch,
                source=work.source,
                metadata=work.metadata,
                timeout_seconds=work.timeout_seconds,
            )

        task = asyncio.create_task(asyncio.to_thread(materialize))
        self._preparing = task
        task.add_done_callback(self._consume_preparation)
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
            validate_recipient_workspace,
            self._config,
            work.source_workspace,
            caller_root=work.caller_root,
        )
        await self._live(connection)
        self._accepted = _Accepted(work, preparation, connection)
        await connection.send_work(
            "reconcile-result",
            {
                "kind": "prepared",
                "in-reply-to": work.message_id,
                "attestation": preparation.attestation.to_mapping(),
            },
        )

    def _consume_preparation(self, task):
        if not task.cancelled() and task.exception() is not None:
            self._remember(task.exception(), "preparation-rejected")

    async def _command(self, connection, work):
        accepted = self._accepted
        if (
            accepted is None
            or accepted.connection is not connection
            or self.producer_pending
            or self._authorizing
        ):
            raise conflict(1, "Command has no available retained preparation")
        self._authorizing = True
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
            task = asyncio.create_task(self._produce(accepted, work, sent, reply))
            self._producer = task
            await asyncio.shield(task)
        finally:
            self._authorizing = False

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
                timeout_seconds=accepted.work.timeout_seconds or self._default_timeout,
            )
        except Exception as error:
            self._remember(error, "producer-failed")
            return None  # Receipt state remains authoritative; never infer unsent.
        finally:
            if self._accepted is accepted:
                self._accepted = None
            try:
                await asyncio.to_thread(self._owner.handoff_if_quiescent)
            except Exception as error:
                self._remember(error, "owner-fenced")

    async def wait_producer(self):
        """Process shutdown/reconnect owner may await; caller cancellation is shielded."""
        task = self._producer
        return None if task is None else await asyncio.shield(task)
