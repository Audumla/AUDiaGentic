"""Bounded node channel with opt-in work delivery, never effect authority.

One receiver handles control and correlated replies independently of a bounded
work dispatcher. Runtime owners must validate grants, local bindings and durable
effects. Heartbeats never become execution progress or watchdog activity.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

from audiagentic.foundation.time import now_iso_z

from .authority import NodeConnectionIdentity
from .contracts import Frame, _identifier, _integer, canonical_json, conflict, invalid
from .work_protocol import WorkFrame, parse_work_frame

UNBOUND = "unbound"
SUBPROTOCOL = "audiagentic-node-v1"
NODE_PATH = "/shared/v1/nodes/connect"
CLOSE_TIMEOUT_SECONDS = 5
logger = logging.getLogger(__name__)
_CHANNEL_REASONS = frozenset({
    "work-disabled", "sequence-mismatch", "reply-unexpected", "reply-command-mismatch",
    "reply-preparation-mismatch", "reply-scope-mismatch", "work-inbox-full", "control-inbox-full",
    "connection-replaced-or-closed", "control-scope-mismatch", "generation-mismatch", "revocation-stale",
})


async def close_socket(websocket, *, code: int = 1000, reason: str = "Node connection closing"):
    """Bound the closing handshake; abort a wedged or cancelled socket close."""
    try:
        await asyncio.wait_for(websocket.close(code=code, reason=reason), CLOSE_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, ConnectionClosed):
        websocket.transport.abort()
    except BaseException:
        websocket.transport.abort()
        raise


def _keys(payload: Mapping[str, Any], expected: set[str]) -> None:
    if set(payload) != expected:
        raise invalid(1, "Unsupported node transport payload fields")


def validate_hello(frame: Frame, *, node_id: str, server_id: str) -> None:
    _keys(frame.payload, {"protocol-version", "server-id", "challenge", "reconnect-checkpoint"})
    if (
        frame.type != "hello"
        or frame.sequence != 1
        or frame.node_id != node_id
        or frame.node_epoch == UNBOUND
        or frame.gateway_owner_epoch != UNBOUND
        or type(frame.payload["protocol-version"]) is not int
        or frame.payload["protocol-version"] != 1
        or frame.payload["server-id"] != server_id
    ):
        raise conflict(1, "Node hello does not match authenticated channel")
    _identifier(frame.payload["challenge"])
    _integer(frame.payload["reconnect-checkpoint"], 0)
    # No durable ACK/checkpoint owner is integrated in this transport-only slice.
    if frame.payload["reconnect-checkpoint"] != 0:
        raise conflict(1, "Receipt checkpointing is not enabled on this transport")


def validate_welcome(
    frame: Frame, *, node_id: str, node_epoch: str, server_id: str, challenge: str
) -> tuple[NodeConnectionIdentity, int, str]:
    _keys(
        frame.payload,
        {
            "protocol-version",
            "server-id",
            "challenge",
            "connection-generation",
            "grant-revision",
            "reconcile-required",
            "capability",
        },
    )
    if (
        frame.type != "welcome"
        or frame.sequence != 1
        or frame.node_id != node_id
        or frame.node_epoch != node_epoch
        or frame.gateway_owner_epoch == UNBOUND
        or frame.payload["server-id"] != server_id
        or frame.payload["challenge"] != challenge
        or type(frame.payload["protocol-version"]) is not int
        or frame.payload["protocol-version"] != 1
        or frame.payload["reconcile-required"] is not True
        or frame.payload["capability"] not in ("active", "drain")
    ):
        raise conflict(1, "Node welcome does not match the current handshake")
    generation = _integer(frame.payload["connection-generation"])
    revision = _integer(frame.payload["grant-revision"])
    return (
        NodeConnectionIdentity(node_id, node_epoch, frame.gateway_owner_epoch, generation),
        revision,
        frame.payload["capability"],
    )


@dataclass(frozen=True)
class ControlEvent:
    type: str
    code: str | None = None
    grant_revision: int | None = None
    capability: str | None = None


@dataclass(frozen=True)
class NodeChannelFailure:
    """Bounded first-cause diagnostic facts, never command or effect authority."""

    code: str
    reason_code: str
    stage: str
    frame_type: str | None
    sequence: int | None
    connection_generation: int
    last_received_sequence: int
    pending_replies: int
    queued_work: int
    occurred_at: str


class NodeConnection:
    """One receiver, serialized bounded writes, and an eight-event control inbox.

    Heartbeats change last_liveness_at only. No execution/watchdog/activity sink
    exists. Binary messages only; sequence is per direction/per connection.
    """

    def __init__(
        self,
        websocket,
        identity: NodeConnectionIdentity,
        *,
        role: str,
        grant_revision: int,
        capability: str,
        current: Callable[[], Awaitable[bool]] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ):
        if role not in {"gateway", "node"}:
            raise invalid(1, "Invalid node connection role")
        if capability not in ("active", "drain"):
            raise invalid(1, "Invalid node connection capability")
        self.websocket = websocket
        self.identity = identity
        self.role = role
        self.grant_revision = _integer(grant_revision)
        self.capability = capability
        self.last_liveness_at = time.monotonic()
        self.events: asyncio.Queue[ControlEvent] = asyncio.Queue(maxsize=8)
        self.failure_summary: NodeChannelFailure | None = None
        self.diagnostic_failure_count = 0
        self.close_reason: str | None = None
        self._current = current
        self._on_close = on_close
        self._send_lock = asyncio.Lock()
        self._sent_sequence = 1  # hello/welcome already sent
        self._received_sequence = 1
        self._closed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._work_task: asyncio.Task | None = None
        self._on_work = None
        self._work_inbox: asyncio.Queue[tuple[Frame, WorkFrame]] = asyncio.Queue(maxsize=8)
        self._pending: dict[str, tuple[tuple[type, ...], asyncio.Future, Mapping]] = {}
        self._max_artifact_bytes = 1024 * 1024

    @property
    def failure(self) -> str | None:
        """Compact code projection of the single retained causal failure."""
        return self.failure_summary.code if self.failure_summary is not None else None

    def begin_close(self, reason: str):
        """Record an owner-requested close without claiming native cancellation."""
        if reason not in {"shutdown", "replacement", "revocation"}:
            raise invalid(1, "Unsupported connection close reason")
        if self.close_reason is None:
            self.close_reason = reason

    def _remember_failure(self, error, *, stage: str, reason: str, frame: Frame | None = None):
        if self.failure_summary is not None:
            return
        code = None if isinstance(error, ConnectionClosed) else getattr(error, "code", None)
        if code not in {"VAL-AGND-001", "CON-AGND-001", "IO-AGND-001"}:
            code = "IO-AGND-001"
        details = getattr(error, "details", None)
        classified = details.get("reason_code") if isinstance(details, Mapping) else None
        if isinstance(classified, str) and classified in _CHANNEL_REASONS:
            reason = classified
        self.failure_summary = NodeChannelFailure(code, reason, stage,
            frame.type if frame is not None else None, frame.sequence if frame is not None else None,
            self.identity.connection_generation, self._received_sequence,
            len(self._pending), self._work_inbox.qsize(), now_iso_z())
        # No exception text/traceback or payload is passed to any log handler.
        # Runtime close owners persist request-associated facts through existing
        # journals. A broken diagnostic sink must not replace the primary error.
        try:
            logger.warning("Node channel failure", extra={
                "error_code": code, "reason_code": reason, "stage": stage,
                "node_id": self.identity.node_id,
                "connection_generation": self.identity.connection_generation,
                "frame_type": self.failure_summary.frame_type,
                "sequence": self.failure_summary.sequence,
            })
        except Exception:  # noqa: BLE001 - logging cannot control transport/effect state
            self.diagnostic_failure_count += 1

    def enable_work(self, handler, *, max_artifact_bytes: int, on_close=None):
        """Install the runtime consumer before starting this connection.

        Handler must offload blocking work and retain native producer lifetime
        independently of socket cancellation. This channel grants no effects.
        """
        if self._task is not None or self._on_work is not None or not callable(handler):
            raise conflict(1, "Work consumer must be installed exactly once before receiver start")
        self._max_artifact_bytes = _integer(max_artifact_bytes)
        self._on_work = handler
        if on_close is not None:
            if self._on_close is not None or not callable(on_close):
                raise conflict(1, "Connection close owner is already installed")
            self._on_close = on_close

    def _receive_work(self, frame: Frame):
        if self._on_work is None:
            raise conflict(1, "Work is disabled", reason_code="work-disabled")
        if frame.sequence != self._received_sequence + 1:
            raise conflict(1, "Work sequence is not contiguous", reason_code="sequence-mismatch")
        message = parse_work_frame(frame, role=self.role, current_connection=self.identity,
            capability=self.capability, max_artifact_bytes=self._max_artifact_bytes)
        reply_to = getattr(message, "in_reply_to", None) or getattr(message, "authorization_request_id", None)
        if reply_to is not None:
            pending = self._pending.get(reply_to)
            if pending is None or type(message) not in pending[0] or pending[1].done():
                raise conflict(1, "Work reply is unsolicited, duplicated or has the wrong operation", reason_code="reply-unexpected")
            original = pending[2]
            if "identity" in original and (
                not hasattr(message, "identity") or message.identity.to_mapping() != original["identity"]
            ):
                raise conflict(1, "Work reply command identity differs from its pending request", reason_code="reply-command-mismatch")
            if hasattr(message, "attestation") and (
                message.attestation.binding.to_mapping() != original.get("binding")
                or message.attestation.semantic.to_mapping() != original.get("semantic")
            ):
                raise conflict(1, "Prepared reply differs from its pending binding or semantic identity", reason_code="reply-preparation-mismatch")
            for field in ("artifact_sha256", "offset", "log_incarnation_id"):
                key = field.replace("_", "-")
                if hasattr(message, field) and key in original and getattr(message, field) != original[key]:
                    raise conflict(1, "Work reply differs from its pending artifact or receipt scope", reason_code="reply-scope-mismatch")
            pending[1].set_result((frame, message))
        else:
            try:
                self._work_inbox.put_nowait((frame, message))
            except asyncio.QueueFull:
                raise conflict(1, "Node work inbox is full", reason_code="work-inbox-full") from None
        self._received_sequence = frame.sequence

    async def _dispatch_work(self):
        frame = None
        try:
            while True:
                frame, message = await self._work_inbox.get()
                await self._on_work(frame, message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._remember_failure(error, stage="dispatch", reason="work-handler-failed", frame=frame)
            await close_socket(self.websocket, code=1008, reason="Node work dispatcher rejected message")

    async def _require_current(self):
        if self._closed.is_set() or (self._current is not None and not await self._current()):
            raise conflict(1, "Node connection has been replaced or closed", reason_code="connection-replaced-or-closed")

    def _validate_control(self, frame: Frame) -> ControlEvent | None:
        identity = self.identity
        if (
            (frame.node_id, frame.node_epoch, frame.gateway_owner_epoch)
            != (identity.node_id, identity.node_epoch, identity.gateway_owner_epoch)
            or frame.gateway_owner_epoch == UNBOUND
            or frame.sequence != self._received_sequence + 1
        ):
            raise conflict(1, "Node frame scope or sequence does not match live connection", reason_code="control-scope-mismatch")
        if frame.type == "heartbeat":
            _keys(frame.payload, {"connection-generation"})
            result = None
        elif frame.type == "revoke" and self.role == "node":
            _keys(frame.payload, {"connection-generation", "grant-revision", "capability"})
            revision = _integer(frame.payload["grant-revision"])
            if revision <= self.grant_revision or frame.payload["capability"] != "drain":
                raise conflict(1, "Node revoke revision is stale", reason_code="revocation-stale")
            result = ControlEvent("revoke", grant_revision=revision, capability="drain")
        elif frame.type == "error":
            _keys(frame.payload, {"connection-generation", "code"})
            code = _identifier(frame.payload["code"])
            if code not in {"VAL-AGND-001", "CON-AGND-001", "IO-AGND-001"}:
                raise invalid(1, "Unsupported node transport error code")
            result = ControlEvent("error", code=code)
        else:
            raise conflict(1, "Node message is not enabled in this transport state or direction")
        if _integer(frame.payload["connection-generation"]) != identity.connection_generation:
            raise conflict(1, "Node frame connection generation is stale", reason_code="generation-mismatch")
        self._received_sequence = frame.sequence
        return result

    async def run(self):
        stage, frame = "receive", None
        try:
            while True:
                stage, frame = "receive", None
                raw = await self.websocket.recv()
                stage = "decode"
                if not isinstance(raw, bytes):
                    raise invalid(1, "Node transport requires binary JSON messages")
                frame = Frame.from_bytes(raw)
                stage = "scope"
                await self._require_current()
                if frame.type not in {"heartbeat", "revoke", "error"}:
                    stage = "work-validation"
                    self._receive_work(frame)
                    continue
                stage = "control-validation"
                event = self._validate_control(frame)
                if event is None:
                    self.last_liveness_at = time.monotonic()
                else:
                    try:
                        self.events.put_nowait(event)
                    except asyncio.QueueFull:
                        raise conflict(1, "Node control inbox is full", reason_code="control-inbox-full") from None
                    if event.type == "revoke":
                        self.grant_revision = event.grant_revision
                        self.capability = "drain"
        except ConnectionClosed as error:
            if self.close_reason is None and not isinstance(error, ConnectionClosedOK):
                self._remember_failure(error, stage="receive", reason="transport-disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._remember_failure(error, stage=stage, reason=f"{stage}-failed", frame=frame)
            await close_socket(self.websocket, code=1008, reason="Node transport rejected message")
        finally:
            self._closed.set()
            if self.close_reason is None:
                self.close_reason = "failed" if self.failure_summary is not None else "peer-closed"
            for _, future, _ in self._pending.values():
                if not future.done():
                    future.set_exception(conflict(1, "Node connection closed while awaiting work reply"))
            if self._work_task is not None:
                self._work_task.cancel()
                await asyncio.gather(self._work_task, return_exceptions=True)
            if self._on_close is not None:
                await self._on_close()

    def start(self):
        if self._task is not None:
            raise conflict(1, "Node receiver is already running")
        self._task = asyncio.create_task(self.run())
        if self._on_work is not None:
            self._work_task = asyncio.create_task(self._dispatch_work())

    async def _send(self, kind: str, **payload):
        return await asyncio.wait_for(self._send_locked(kind, payload), timeout=10)

    async def _send_locked(self, kind: str, payload, *, message_id=None, work=False):
        async with self._send_lock:
            await self._require_current()
            identity = self.identity
            effect = kind in {"effect-authorize", "effect-authorized", "effect-denied"}
            wire_payload = dict(payload) if effect else {**payload, "connection-generation": identity.connection_generation}
            frame = Frame(
                1,
                kind,
                message_id or f"control-{self._sent_sequence + 1}",
                identity.node_id,
                identity.node_epoch,
                identity.gateway_owner_epoch,
                self._sent_sequence + 1,
                wire_payload,
            )
            if work:
                parse_work_frame(frame, role="node" if self.role == "gateway" else "gateway",
                    current_connection=identity, capability=self.capability,
                    max_artifact_bytes=self._max_artifact_bytes)
            self._sent_sequence += 1
            try:
                await self.websocket.send(frame.to_bytes())
            except BaseException as error:
                # A failed/partial send cannot be followed by another sequence.
                self._closed.set()
                self._remember_failure(error, stage="send", reason="transport-send-failed", frame=frame)
                self.websocket.transport.abort()
                raise
            return frame

    async def send_work(self, kind: str, payload: Mapping[str, Any], *, message_id=None) -> Frame:
        """Return exact sent frame for authorization evidence; no replay on send failure."""
        if self._on_work is None:
            raise conflict(1, "Node work routing is not enabled")
        return await asyncio.wait_for(self._send_locked(kind, dict(payload),
            message_id=message_id or uuid.uuid4().hex, work=True), timeout=10)

    async def request_work(self, kind: str, payload: Mapping[str, Any], *, reply_types: tuple[type, ...],
                           timeout: float) -> tuple[Frame, Frame, WorkFrame]:
        """Bounded correlation only; runtime still validates exact command/binding.

        Reply completion happens in the receiver, independently of the work
        dispatcher, so a handler may await a reply without blocking its arrival.
        """
        if (len(self._pending) >= 4 or not reply_types or type(timeout) not in (int, float)
                or not math.isfinite(timeout) or timeout <= 0):
            raise conflict(1, "Node pending reply capacity or request bounds are invalid")
        message_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        retained = json.loads(canonical_json(payload))
        self._pending[message_id] = (reply_types, future, retained)
        try:
            sent = await self.send_work(kind, retained, message_id=message_id)
            reply_frame, message = await asyncio.wait_for(future, timeout)
            return sent, reply_frame, message
        finally:
            self._pending.pop(message_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def heartbeat(self):
        await self._send("heartbeat")

    async def notify_drain(self, revision: int):
        if self.role != "gateway" or _integer(revision) <= self.grant_revision:
            raise conflict(1, "Only gateway may notify a newer grant revocation")
        await self._send("revoke", **{"grant-revision": revision, "capability": "drain"})
        self.grant_revision = revision
        self.capability = "drain"

    async def wait_closed(self):
        await self._closed.wait()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task

    async def close(self, *, reason="shutdown"):
        self.begin_close(reason)
        await close_socket(self.websocket)
        if self._task is not None and self._task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), CLOSE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                self.websocket.transport.abort()
                self._task.cancel()
                await asyncio.wait_for(
                    asyncio.gather(self._task, return_exceptions=True), CLOSE_TIMEOUT_SECONDS
                )
