"""Opt-in recipient process; no gateway service graph.

Construct off-loop, then run once. Channel cleanup precedes reconnect; producer
completion precedes managed-claim retirement, including caller cancellation.
"""

from __future__ import annotations

import asyncio
import errno
import math
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.system.managed_process import current_process_evidence
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner

from ..admission.context import ComponentContextReader
from ..service.shared_config import SharedGatewayNodeConfig
from .contracts import conflict, invalid
from .diagnostics import sanitize_node_error
from .execution_owner import NodeExecutionOwner
from .local_preparation import NodeLocalPreparer
from .receipt_sender import NodeReceiptSender
from .recipient_runtime import NodeRecipientRuntime
from .transport import NodeTransportClient


@dataclass(frozen=True)
class NodeRecipientCause:
    """Closed diagnostic projection, with no mutable details or exception text."""

    code: str
    stage: str
    reason: str

    @classmethod
    def from_error(cls, error):
        safe = sanitize_node_error(error, stage="observe")
        return cls(safe.code, safe.details["stage"], safe.details["reason-code"])


@dataclass(frozen=True)
class NodeRecipientOutcome:
    disposition: Literal["stopped", "retry-exhausted", "deferred"]
    terminal_cause: NodeRecipientCause | None = None


@dataclass(frozen=True)
class _ChannelOutcome:
    elapsed_seconds: float
    retryable: bool
    terminal_cause: NodeRecipientCause | None


def _sender_timeout_retryable(error: Exception) -> bool:
    return (
        isinstance(error, AudiaGenticError)
        and error.code == "CON-AGND-001"
        and (error.details.get("reason-code") or error.details.get("reason_code"))
        in {"receipt-ack-timeout", "receipt-resume-timeout"}
    )


@dataclass(frozen=True)
class NodeReconnectPolicy:
    """Finite consecutive failures; connecting alone never resets the budget."""

    max_failures: int = 3
    delay_seconds: float = 1
    stable_seconds: float = 30

    def __post_init__(self):
        if type(self.max_failures) is not int or self.max_failures < 1:
            raise invalid(1, "Reconnect failure budget must be positive")
        for value in (self.delay_seconds, self.stable_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise invalid(1, "Reconnect timings must be positive and finite")


class NodeRecipientHost:
    @classmethod
    def create(
        cls,
        config: SharedGatewayNodeConfig,
        *,
        component_context_reader: ComponentContextReader,
        reconnect: NodeReconnectPolicy | None = None,
    ):
        """Claim once per process; a new boot requires a new process.

        Retirement does not release the execution owner's process-lifetime
        fence. Recreating a host while that owner is retained fails closed.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise conflict(1, "Create recipient host off the event loop")
        if type(config) is not SharedGatewayNodeConfig:
            raise invalid(1, "Recipient host requires typed local configuration")
        if not callable(component_context_reader):
            raise invalid(1, "Recipient host requires an explicit component context reader")
        policy = NodeReconnectPolicy() if reconnect is None else reconnect
        if type(policy) is not NodeReconnectPolicy:
            raise invalid(1, "Recipient host requires a reconnect policy")
        boot = uuid.uuid4().hex
        store = ManagedServiceStore(
            ServiceKey("execution-node", config.node_id), root=config.state_root
        )
        owner = ManagedServiceOwner(store)
        claim = owner.claim(
            protocol_version="1",
            endpoint=EndpointInfo("node-recipient", "node:" + config.node_id),
            evidence_factory=lambda epoch: current_process_evidence(owner_epoch=epoch),
            health_facts={"connected": False},
        )
        try:
            execution = NodeExecutionOwner.open(
                config, service_store=store, service_owner_epoch=claim.owner_epoch, node_epoch=boot
            )
            preparer = NodeLocalPreparer(config, component_context_reader=component_context_reader)
            runtime = NodeRecipientRuntime(config, execution, preparer=preparer)
            client = NodeTransportClient(
                config, node_epoch=boot, configure_work=runtime.configure_work
            )
            sender = NodeReceiptSender(runtime)
            return cls(store, owner, claim.owner_epoch, boot, runtime, client, sender, policy)
        except BaseException:
            owner.retire(expected_epoch=claim.owner_epoch)
            raise

    def __init__(self, store, owner, epoch, boot, runtime, client, sender, policy):
        self.service_store, self.service_owner = store, owner
        self.owner_epoch, self.node_epoch = epoch, boot
        self.runtime, self.client, self.sender = runtime, client, sender
        self.reconnect = policy
        self._stop = asyncio.Event()
        self._loop = None
        self._started = False
        self.failure = None

    def request_stop(self):
        """Signal only: never close, drain, cancel or kill a producer here."""
        if self._loop is None:
            self._stop.set()
        else:
            self._loop.call_soon_threadsafe(self._stop.set)

    def _observe(self, event, *, connected=False, elapsed=0):
        # Health and timeline are diagnostics, never work progress or authority.
        facts = {"connected": connected, "elapsed-seconds": max(0, elapsed)}
        if self.failure is not None:
            facts.update(self.failure)
        try:
            self.service_store.heartbeat(facts, expected_epoch=self.owner_epoch)
        except Exception:
            pass
        try:
            record_timeline_event(
                self.service_store.timeline_path,
                component="agents",
                resource_kind="managed-service",
                resource_id=self.service_store.key.service_id,
                event=event,
                state="running",
                attributes=facts,
            )
        except Exception:
            pass  # Includes a faulty logging sink; never rollback custody.

    def _remember(self, error):
        if self.failure is None:
            safe = sanitize_node_error(error, stage="observe")
            self.failure = {
                "code": safe.code,
                "stage": safe.details["stage"],
                "reason": safe.details["reason-code"],
            }

    async def _interruptible(self, awaitable, *, connection_attempt=False):
        task = asyncio.create_task(awaitable)
        delivered = False
        stop = asyncio.create_task(self._stop.wait())
        try:
            done, _ = await asyncio.wait((task, stop), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                result = await task
                delivered = True
                return result
            return None
        finally:

            async def cleanup():
                for pending in (task, stop):
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(task, stop, return_exceptions=True)
                # A completed connect racing stop/cancellation still owns a
                # channel, even if its result never reached the run loop.
                if (
                    connection_attempt
                    and not delivered
                    and not task.cancelled()
                    and task.exception() is None
                ):
                    connection = task.result()
                    if connection is not None:
                        await connection.close()

            cleanup_task = asyncio.create_task(cleanup())
            cancelled = False
            while not cleanup_task.done():
                try:
                    await asyncio.shield(cleanup_task)
                except asyncio.CancelledError:
                    cancelled = True
            await cleanup_task
            if cancelled:
                raise asyncio.CancelledError

    async def _channel(self, connection, connected_at):
        sender = asyncio.create_task(self.sender.run(connection))
        closed = asyncio.create_task(connection.wait_closed())
        event = asyncio.create_task(connection.events.get())
        stop = asyncio.create_task(self._stop.wait())
        elapsed, retryable = 0, True
        cause = None
        try:
            while True:
                done, _ = await asyncio.wait(
                    (sender, closed, event, stop), return_when=asyncio.FIRST_COMPLETED
                )
                if sender in done:
                    await sender
                if closed in done:
                    await closed
                    failure = connection.failure_summary
                    if failure is not None:
                        safe = sanitize_node_error(
                            {
                                "code": failure.code,
                                "details": {
                                    "reason-code": failure.reason_code,
                                },
                            },
                            stage="observe",
                        )
                        self._remember(safe)
                        cause = NodeRecipientCause.from_error(safe)
                        if failure.reason_code not in {
                            "transport-disconnected",
                            "transport-send-failed",
                        }:
                            raise safe
                if sender in done or closed in done or stop in done:
                    # A closed channel can win before the sender unwinds its
                    # timed-out request. Join that bounded sender path before
                    # deciding; never cancel away its causal timeout evidence.
                    if closed in done and not self._stop.is_set():
                        await sender
                    # Exclude cleanup time: a slow close is not stable connectivity.
                    elapsed = time.monotonic() - connected_at
                    break
                control = event.result()
                if control.type == "revoke" and control.capability == "drain":
                    # NodeConnection already applied grant revision/capability.
                    # Keep historical receipt/ACK/artifact handlers alive. The
                    # runtime/sender owns the prohibition on fresh readiness.
                    event = asyncio.create_task(connection.events.get())
                    continue
                if control.type == "error":
                    raise sanitize_node_error({"code": control.code}, stage="observe")
                raise conflict(1, "Unsupported recipient control boundary")
        except Exception as error:
            self._remember(error)
            cause = NodeRecipientCause.from_error(error)
            retryable = _sender_timeout_retryable(error)
        finally:
            cleanup_error = None
            try:
                await connection.close()
            except Exception as error:
                cleanup_error = sanitize_node_error(error, stage="observe")
            finally:
                for task in (sender, closed, event, stop):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(sender, closed, event, stop, return_exceptions=True)
            if not sender.cancelled() and sender.exception() is not None:
                self._remember(sender.exception())
                if cause is None:
                    cause = NodeRecipientCause.from_error(sender.exception())
                retryable = retryable and _sender_timeout_retryable(sender.exception())
            if cleanup_error is not None:
                self._remember(cleanup_error)
                # Separate policy from first cause: a primary timeout remains
                # visible, but unproven cleanup never permits another channel.
                retryable = False
                cause = NodeRecipientCause.from_error(cleanup_error)
        return _ChannelOutcome(elapsed, retryable, cause)

    async def _finish(self):
        await self.runtime.wait_producer()
        failure = self.runtime.failure
        if failure is not None:
            self._remember({"code": failure.code})
        await asyncio.to_thread(self._observe, "node.host-quiescent")
        await asyncio.to_thread(self.service_owner.retire, expected_epoch=self.owner_epoch)

    async def run(self) -> NodeRecipientOutcome:
        """Run once; cancellation waits for the producer before propagating."""
        if self._started:
            raise conflict(1, "Recipient host can only run once")
        self._started, self._loop = True, asyncio.get_running_loop()
        failures = 0
        result = NodeRecipientOutcome("stopped")
        try:
            while not self._stop.is_set():
                elapsed = 0
                terminal = False
                cause = None
                try:
                    connection = await self._interruptible(
                        self.client.connect(), connection_attempt=True
                    )
                    if connection is None:
                        break
                    connected_at = time.monotonic()
                    # Shield cleanup from caller cancellation; the channel itself
                    # owns only sender/control waiters, never the producer.
                    cycle = asyncio.create_task(self._channel(connection, connected_at))
                    try:
                        await asyncio.to_thread(
                            self._observe, "node.host-connected", connected=True
                        )
                        outcome = await asyncio.shield(cycle)
                        elapsed, terminal = outcome.elapsed_seconds, not outcome.retryable
                        cause = outcome.terminal_cause
                    except asyncio.CancelledError:
                        self._stop.set()
                        while not cycle.done():
                            try:
                                await asyncio.shield(cycle)
                            except asyncio.CancelledError:
                                continue
                        await cycle
                        raise
                except asyncio.CancelledError:
                    raise
                except (OSError, TimeoutError) as error:
                    self._remember(error)
                    cause = NodeRecipientCause.from_error(error)
                    # Missing credentials/files, TLS validation and unknown OS
                    # failures are configuration boundaries, not network retry.
                    terminal = not (
                        isinstance(error, (ConnectionError, TimeoutError))
                        or error.errno
                        in {
                            errno.ECONNREFUSED,
                            errno.ECONNRESET,
                            errno.ETIMEDOUT,
                            errno.EHOSTUNREACH,
                            errno.ENETUNREACH,
                            errno.EPIPE,
                        }
                    )
                except Exception as error:
                    self._remember(error)
                    cause = NodeRecipientCause.from_error(error)
                    terminal = True  # Auth/config/cursor/unknown errors fail closed.
                if not self._stop.is_set() and self.failure is None:
                    self._remember(None)
                await asyncio.to_thread(self._observe, "node.host-disconnected", elapsed=elapsed)
                failures = (0 if elapsed >= self.reconnect.stable_seconds else failures) + 1
                if terminal:
                    result = NodeRecipientOutcome("deferred", cause or NodeRecipientCause.from_error(None))
                    break
                if self._stop.is_set():
                    break
                if failures >= self.reconnect.max_failures:
                    result = NodeRecipientOutcome("retry-exhausted", cause or NodeRecipientCause.from_error(None))
                    break
                await self._interruptible(asyncio.sleep(self.reconnect.delay_seconds))
        finally:
            # Repeated cancellation cannot detach this shutdown barrier.
            finish = asyncio.create_task(self._finish())
            cancelled = False
            while not finish.done():
                try:
                    await asyncio.shield(finish)
                except asyncio.CancelledError:
                    cancelled = True
            await finish
            if cancelled:
                raise asyncio.CancelledError
        return result
