"""Explicit-start node WSS transport; no scheduling, effects, receipt ACK or host hooks.

Requires websockets 15.x: asyncio additional_headers, explicit proxy=None and the
verified connect.process_redirect override. The node extra pins that major API.
TLS may terminate at the configured front door; this listener binds loopback only.
"""

from __future__ import annotations

import asyncio
import hmac
import ssl
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.asyncio.server import ServerConnection, serve

from audiagentic.components.agents.gateway.remote_client import load_auth_token
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayNodeConfig,
    SharedGatewayServerConfig,
    load_shared_server_config,
)

from .authority import NodeConnectionIdentity, NodeGrantAuthority
from .connection import (
    NODE_PATH,
    SUBPROTOCOL,
    UNBOUND,
    NodeConnection,
    close_socket,
    validate_hello,
    validate_welcome,
)
from .contracts import MAX_FRAME_BYTES, Frame, _identifier, conflict, invalid

_LIMITS = dict(
    compression=None,
    max_size=MAX_FRAME_BYTES,
    max_queue=4,
    write_limit=32768,
    open_timeout=10,
    ping_interval=20,
    ping_timeout=20,
    close_timeout=5,
)


class DirectNodeConnect(connect):
    """Never follow even same-origin redirects with node bearer credentials."""

    def process_redirect(self, exc):
        return (
            conflict(1, "Node WebSocket redirects are forbidden")
            if (
                getattr(getattr(exc, "response", None), "status_code", 0)
                in {300, 301, 302, 303, 307, 308}
            )
            else exc
        )


class _NodeSocket(ServerConnection):
    authenticated_node_id: str | None = None


@dataclass(frozen=True)
class ConnectionSlot:
    identity: NodeConnectionIdentity
    websocket: ServerConnection
    grant_revision: int


class NodeConnectionOwner:
    """Owner-epoch-scoped live slots. Every mutation uses authority.serialize.

    One instance per service owner epoch; generations survive socket cleanup.
    current_identity() is intentionally lock-free for invocation INSIDE the
    authority's authorize_effect callback, avoiding recursive authority locks.
    """

    def __init__(self, authority: NodeGrantAuthority, gateway_owner_epoch: str):
        self.authority = authority
        self.gateway_owner_epoch = _identifier(gateway_owner_epoch)
        if gateway_owner_epoch == UNBOUND:
            raise invalid(1, "Gateway owner epoch cannot be unbound")
        self._active: dict[str, ConnectionSlot] = {}
        self._generations: dict[str, int] = {}

    def _config(self):
        return load_shared_server_config(self.authority.path)

    def authenticate(self, authorization: str) -> str:
        def check():
            matched = None
            for grant in self._config().nodes:
                token = load_auth_token(grant.token_file)
                if (
                    hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode())
                    and grant.enabled
                ):
                    matched = grant.node_id
            if matched is None:
                raise conflict(1, "Node credential is not enrolled and enabled")
            return matched

        return self.authority.serialize(check)

    def replace(
        self, node_id: str, node_epoch: str, websocket
    ) -> tuple[ConnectionSlot, ConnectionSlot | None]:
        def change():
            grant = next(
                (g for g in self._config().nodes if g.node_id == node_id and g.enabled), None
            )
            if grant is None:
                raise conflict(1, "Node grant is no longer enabled")
            generation = self._generations.get(node_id, 0) + 1
            identity = NodeConnectionIdentity(
                node_id, node_epoch, self.gateway_owner_epoch, generation
            )
            slot = ConnectionSlot(identity, websocket, grant.revision)
            old = self._active.get(node_id)
            self._generations[node_id] = generation
            self._active[node_id] = slot
            return slot, old

        return self.authority.serialize(change)

    def remove(self, slot: ConnectionSlot) -> bool:
        def change():
            if self._active.get(slot.identity.node_id) is not slot:
                return False
            del self._active[slot.identity.node_id]
            return True

        return self.authority.serialize(change)

    def is_current(self, slot: ConnectionSlot) -> bool:
        return self.authority.serialize(lambda: self._active.get(slot.identity.node_id) is slot)

    def current_identity(self, node_id: str) -> NodeConnectionIdentity | None:
        """Read only while the caller already holds the shared authority lock."""
        slot = self._active.get(node_id)
        return slot.identity if slot is not None else None


class NodeTransportServer:
    def __init__(
        self,
        config: SharedGatewayServerConfig,
        authority: NodeGrantAuthority,
        *,
        gateway_owner_epoch: str,
    ):
        if config.node_listen is None or config.node_listen.host != "127.0.0.1":
            raise invalid(1, "Node transport requires configured IPv4 loopback listener")
        if config.config_path is None or config.config_path.resolve() != authority.path:
            raise conflict(1, "Node listener config does not match grant authority")
        self.config = config
        self.owner = NodeConnectionOwner(authority, gateway_owner_epoch)
        self._server = None

    async def _authenticate_upgrade(self, connection: _NodeSocket, request):
        if request.path != NODE_PATH:
            return connection.respond(HTTPStatus.NOT_FOUND, "Unknown node endpoint\n")
        # A supervised node isn't a browser. No browser Origin is authorized.
        if request.headers.get_all("Origin"):
            return connection.respond(HTTPStatus.FORBIDDEN, "Node Origin is not allowed\n")
        authorizations = request.headers.get_all("Authorization")
        if len(authorizations) != 1:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Node authentication required\n")
        try:
            connection.authenticated_node_id = await asyncio.to_thread(
                self.owner.authenticate, authorizations[0]
            )
        except Exception:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Node authentication failed\n")
        return None

    async def _handle(self, websocket: _NodeSocket):
        slot = None
        old = None
        connection = None
        try:
            if websocket.authenticated_node_id is None or websocket.subprotocol != SUBPROTOCOL:
                raise conflict(1, "Node handshake has no authenticated protocol identity")
            raw = await asyncio.wait_for(websocket.recv(), timeout=5)
            if not isinstance(raw, bytes):
                raise invalid(1, "Node hello must be binary JSON")
            hello = Frame.from_bytes(raw)
            validate_hello(
                hello, node_id=websocket.authenticated_node_id, server_id=self.config.server_id
            )
            # Shield publication: cancellation must not leave an untracked live slot
            # if the thread finishes its authority-serialized mutation afterward.
            publication = asyncio.create_task(
                asyncio.to_thread(self.owner.replace, hello.node_id, hello.node_epoch, websocket)
            )
            try:
                slot, old = await asyncio.shield(publication)
            except asyncio.CancelledError:
                slot, old = await publication
                raise
            if old is not None:
                await close_socket(old.websocket, code=1008, reason="Node connection replaced")
                old = None
            welcome = Frame(
                1,
                "welcome",
                uuid.uuid4().hex,
                hello.node_id,
                hello.node_epoch,
                self.owner.gateway_owner_epoch,
                1,
                {
                    "protocol-version": 1,
                    "server-id": self.config.server_id,
                    "challenge": hello.payload["challenge"],
                    "connection-generation": slot.identity.connection_generation,
                    "grant-revision": slot.grant_revision,
                    "reconcile-required": True,
                },
            )
            await asyncio.wait_for(websocket.send(welcome.to_bytes()), timeout=10)

            async def current():
                return await asyncio.to_thread(self.owner.is_current, slot)

            connection = NodeConnection(
                websocket,
                slot.identity,
                role="gateway",
                grant_revision=slot.grant_revision,
                current=current,
            )
            connection.start()
            await connection.wait_closed()
        except asyncio.CancelledError:
            raise
        except Exception:
            await close_socket(websocket, code=1008, reason="Node handshake or channel rejected")
        finally:
            try:
                if old is not None:
                    await close_socket(old.websocket, code=1008, reason="Node connection replaced")
            finally:
                try:
                    if connection is not None:
                        await connection.close()
                    else:
                        await close_socket(websocket)
                finally:
                    if slot is not None:
                        await asyncio.to_thread(self.owner.remove, slot)

    async def start(self, *, ssl_context: ssl.SSLContext | None = None):
        if self._server is not None:
            raise conflict(1, "Node listener is already started")
        self._server = await serve(
            self._handle,
            self.config.node_listen.host,
            self.config.node_listen.port,
            process_request=self._authenticate_upgrade,
            origins=[None],
            subprotocols=[SUBPROTOCOL],
            create_connection=_NodeSocket,
            ssl=ssl_context,
            **_LIMITS,
        )
        return self

    @property
    def port(self) -> int:
        if self._server is None:
            raise conflict(1, "Node listener is not started")
        return self._server.sockets[0].getsockname()[1]

    async def close(self):
        if self._server is not None:
            self._server.close()
            await asyncio.wait_for(self._server.wait_closed(), timeout=15)
            self._server = None


def _validate_endpoint(endpoint: str):
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "wss"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != NODE_PATH
            or any(c.isspace() or ord(c) < 32 for c in endpoint)
            or any(c in endpoint for c in "?#\\")
            or parsed.netloc.endswith(":")
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise invalid(1, "Node endpoint must be WSS with the exact configured node path") from None


class NodeTransportClient:
    def __init__(self, config: SharedGatewayNodeConfig, *, node_epoch: str):
        _validate_endpoint(config.endpoint)
        self.config = config
        self.node_epoch = _identifier(node_epoch)
        if node_epoch == UNBOUND:
            raise invalid(1, "Node boot epoch cannot be unbound")
        _identifier(config.node_id)
        _identifier(config.server_id)

    async def connect(self) -> NodeConnection:
        """One authenticated connection attempt; no retry, epoch rotation or replay."""
        context = ssl.create_default_context(
            cafile=str(self.config.ca_file) if self.config.ca_file else None
        )
        websocket = await DirectNodeConnect(
            self.config.endpoint,
            ssl=context,
            proxy=None,
            additional_headers={
                "Authorization": f"Bearer {load_auth_token(self.config.token_file)}"
            },
            subprotocols=[SUBPROTOCOL],
            **_LIMITS,
        )
        try:
            if websocket.subprotocol != SUBPROTOCOL:
                raise conflict(1, "Node subprotocol was not negotiated")
            challenge = uuid.uuid4().hex
            hello = Frame(
                1,
                "hello",
                uuid.uuid4().hex,
                self.config.node_id,
                self.node_epoch,
                UNBOUND,
                1,
                {
                    "protocol-version": 1,
                    "server-id": self.config.server_id,
                    "challenge": challenge,
                    "reconnect-checkpoint": 0,
                },
            )
            await asyncio.wait_for(websocket.send(hello.to_bytes()), timeout=10)
            raw = await asyncio.wait_for(websocket.recv(), timeout=5)
            if not isinstance(raw, bytes):
                raise invalid(1, "Node welcome must be binary JSON")
            identity, revision = validate_welcome(
                Frame.from_bytes(raw),
                node_id=self.config.node_id,
                node_epoch=self.node_epoch,
                server_id=self.config.server_id,
                challenge=challenge,
            )
            connection = NodeConnection(websocket, identity, role="node", grant_revision=revision)
            connection.start()
            return connection
        except BaseException:
            await close_socket(websocket, code=1008, reason="Node welcome rejected")
            raise
