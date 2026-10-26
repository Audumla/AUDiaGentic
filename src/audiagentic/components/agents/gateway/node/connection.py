"""Bounded node-channel handshake/control state; never execution progress or dispatch.

Only transport messages are enabled. Preparation, receipt ACKs and native command
routing must acquire their strict owner integrations before being accepted here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from websockets.exceptions import ConnectionClosed

from .authority import NodeConnectionIdentity
from .contracts import Frame, _identifier, _integer, conflict, invalid

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
) -> tuple[NodeConnectionIdentity, int]:
    _keys(
        frame.payload,
        {
            "protocol-version",
            "server-id",
            "challenge",
            "connection-generation",
            "grant-revision",
            "reconcile-required",
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
    ):
        raise conflict(1, "Node welcome does not match the current handshake")
    generation = _integer(frame.payload["connection-generation"])
    revision = _integer(frame.payload["grant-revision"])
    return NodeConnectionIdentity(
        node_id, node_epoch, frame.gateway_owner_epoch, generation
    ), revision


@dataclass(frozen=True)
class ControlEvent:
    type: str
    code: str | None = None
    grant_revision: int | None = None


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
        current: Callable[[], Awaitable[bool]] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
    ):
        if role not in {"gateway", "node"}:
            raise invalid(1, "Invalid node connection role")
        self.websocket = websocket
        self.identity = identity
        self.role = role
        self.grant_revision = _integer(grant_revision)
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
            _keys(frame.payload, {"connection-generation", "grant-revision"})
            revision = _integer(frame.payload["grant-revision"])
            if revision <= self.grant_revision:
                raise conflict(1, "Node revoke revision is stale")
            result = ControlEvent("revoke", grant_revision=revision)
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
                event = self._validate_control(Frame.from_bytes(raw))
                if event is None:
                    self.last_liveness_at = time.monotonic()
                else:
                    try:
                        self.events.put_nowait(event)
                    except asyncio.QueueFull:
                        raise conflict(1, "Node control inbox is full") from None
                    if event.type == "revoke":
                        await close_socket(self.websocket, code=1008, reason="Node grant revoked")
                        return
        except ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = getattr(error, "code", "IO-AGND-001")
            await close_socket(self.websocket, code=1008, reason="Node transport rejected message")
        finally:
            self._closed.set()
            if self._on_close is not None:
                await self._on_close()

    def start(self):
        if self._task is not None:
            raise conflict(1, "Node receiver is already running")
        self._task = asyncio.create_task(self.run())

    async def _send(self, kind: str, **payload):
        await asyncio.wait_for(self._send_locked(kind, payload), timeout=10)

    async def _send_locked(self, kind: str, payload):
        async with self._send_lock:
            await self._require_current()
            self._sent_sequence += 1
            identity = self.identity
            frame = Frame(
                1,
                kind,
                f"control-{self._sent_sequence}",
                identity.node_id,
                identity.node_epoch,
                identity.gateway_owner_epoch,
                self._sent_sequence,
                {"connection-generation": identity.connection_generation, **payload},
            )
            try:
                await self.websocket.send(frame.to_bytes())
            except BaseException:
                # A failed/partial send cannot be followed by another sequence.
                self._closed.set()
                self.websocket.transport.abort()
                raise

    async def heartbeat(self):
        await self._send("heartbeat")

    async def revoke(self, revision: int):
        if self.role != "gateway" or _integer(revision) <= self.grant_revision:
            raise conflict(1, "Only gateway may notify a newer grant revocation")
        await self._send("revoke", **{"grant-revision": revision})

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
