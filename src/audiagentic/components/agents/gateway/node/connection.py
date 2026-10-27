"""Bounded node channel with opt-in work delivery, never effect authority.

One receiver handles control and correlated replies independently of a bounded
work dispatcher. Runtime owners must validate grants, local bindings and durable
effects. Heartbeats never become execution progress or watchdog activity.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from websockets.exceptions import ConnectionClosed

from .authority import NodeConnectionIdentity
from .contracts import Frame, _identifier, _integer, canonical_json, conflict, invalid
from .work_protocol import WorkFrame, parse_work_frame

UNBOUND = "unbound"
SUBPROTOCOL = "audiagentic-node-v1"
NODE_PATH = "/shared/v1/nodes/connect"
CLOSE_TIMEOUT_SECONDS = 5


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
        self.failure: str | None = None
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
        if self._on_work is None or frame.sequence != self._received_sequence + 1:
            raise conflict(1, "Work is disabled or its sequence is not contiguous")
        message = parse_work_frame(frame, role=self.role, current_connection=self.identity,
            capability=self.capability, max_artifact_bytes=self._max_artifact_bytes)
        reply_to = getattr(message, "in_reply_to", None) or getattr(message, "authorization_request_id", None)
        if reply_to is not None:
            pending = self._pending.get(reply_to)
            if pending is None or type(message) not in pending[0] or pending[1].done():
                raise conflict(1, "Work reply is unsolicited, duplicated or has the wrong operation")
            original = pending[2]
            if "identity" in original and (
                not hasattr(message, "identity") or message.identity.to_mapping() != original["identity"]
            ):
                raise conflict(1, "Work reply command identity differs from its pending request")
            if hasattr(message, "attestation") and (
                message.attestation.binding.to_mapping() != original.get("binding")
                or message.attestation.semantic.to_mapping() != original.get("semantic")
            ):
                raise conflict(1, "Prepared reply differs from its pending binding or semantic identity")
            for field in ("artifact_sha256", "offset", "log_incarnation_id"):
                key = field.replace("_", "-")
                if hasattr(message, field) and key in original and getattr(message, field) != original[key]:
                    raise conflict(1, "Work reply differs from its pending artifact or receipt scope")
            pending[1].set_result((frame, message))
        else:
            try:
                self._work_inbox.put_nowait((frame, message))
            except asyncio.QueueFull:
                raise conflict(1, "Node work inbox is full") from None
        self._received_sequence = frame.sequence

    async def _dispatch_work(self):
        try:
            while True:
                frame, message = await self._work_inbox.get()
                await self._on_work(frame, message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = getattr(error, "code", "IO-AGND-001")
            await close_socket(self.websocket, code=1008, reason="Node work dispatcher rejected message")

    async def _require_current(self):
        if self._closed.is_set() or (self._current is not None and not await self._current()):
            raise conflict(1, "Node connection has been replaced or closed")

    def _validate_control(self, frame: Frame) -> ControlEvent | None:
        identity = self.identity
        if (
            (frame.node_id, frame.node_epoch, frame.gateway_owner_epoch)
            != (identity.node_id, identity.node_epoch, identity.gateway_owner_epoch)
            or frame.gateway_owner_epoch == UNBOUND
            or frame.sequence != self._received_sequence + 1
        ):
            raise conflict(1, "Node frame scope or sequence does not match live connection")
        if frame.type == "heartbeat":
            _keys(frame.payload, {"connection-generation"})
            result = None
        elif frame.type == "revoke" and self.role == "node":
            _keys(frame.payload, {"connection-generation", "grant-revision", "capability"})
            revision = _integer(frame.payload["grant-revision"])
            if revision <= self.grant_revision or frame.payload["capability"] != "drain":
                raise conflict(1, "Node revoke revision is stale")
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
            raise conflict(1, "Node frame connection generation is stale")
        self._received_sequence = frame.sequence
        return result

    async def run(self):
        try:
            while True:
                raw = await self.websocket.recv()
                if not isinstance(raw, bytes):
                    raise invalid(1, "Node transport requires binary JSON messages")
                await self._require_current()
                frame = Frame.from_bytes(raw)
                if frame.type not in {"heartbeat", "revoke", "error"}:
                    self._receive_work(frame)
                    continue
                event = self._validate_control(frame)
                if event is None:
                    self.last_liveness_at = time.monotonic()
                else:
                    try:
                        self.events.put_nowait(event)
                    except asyncio.QueueFull:
                        raise conflict(1, "Node control inbox is full") from None
                    if event.type == "revoke":
                        self.grant_revision = event.grant_revision
                        self.capability = "drain"
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = getattr(error, "code", "IO-AGND-001")
            await close_socket(self.websocket, code=1008, reason="Node transport rejected message")
        finally:
            self._closed.set()
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
            except BaseException:
                # A failed/partial send cannot be followed by another sequence.
                self._closed.set()
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

    async def close(self):
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
