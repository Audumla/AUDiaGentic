"""The A2A facade: a loopback ASGI app that serves published agents through the shared gateway (SH65b-2).

It is a CLIENT of the gateway, never a second authority. The caller's own ``Authorization: Bearer`` token is
forwarded to the gateway, which authenticates the real principal, enforces its project and action grants and
builds the delivery identity from the lease; the facade has no credential of its own, no token store and no
task store. Before a request can have an effect the facade checks, from the gateway's own capability list for
that caller, that every operation the call will need is allowed, so a caller that may submit but not read is
refused before the message is accepted rather than after.

Not here: where routes and cards come from (settings, SH65b-3) and any exposure beyond loopback (an external
TLS proxy's job).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import a2a_pb2 as pb
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .sdk_handler import A2aSdkRequestHandler
from .server import A2aServerAdapter

logger = logging.getLogger(__name__)

#: A bounded body: an A2A message is text, and the facade reads it before the SDK does.
MAX_BODY_BYTES = 1_048_576
_PROJECT_NOT_AUTHORIZED = "shared gateway project is not authorized"  # remote_client.StandaloneGatewayClient.health


@dataclass(frozen=True)
class A2aRoute:
    """One served agent: a gateway project id and a published agent id, never a filesystem path."""

    project_id: str
    agent_id: str

    @property
    def path(self) -> str:
        return f"/a2a/{self.project_id}/{self.agent_id}"


def required_operations(method: str, params: Mapping[str, Any]) -> frozenset[str]:
    """The gateway operations a call will use, so a missing grant is refused before anything happens."""
    if method == "SendMessage":
        message = params.get("message") if isinstance(params.get("message"), dict) else {}
        needs = {"accept_agent_work_message"}
        configuration = params.get("configuration") if isinstance(params.get("configuration"), dict) else {}
        if not configuration.get("returnImmediately"):  # the call waits, then reads the result
            needs |= {"wait_agent_work", "get_agent_work", "read_agent_work_output"}
        if message.get("taskId"):
            needs.add("get_agent_work")
        needs.add("get_agent_context" if message.get("contextId") or message.get("taskId") else "open_agent_context")
        return frozenset(needs)
    if method == "GetTask":
        return frozenset({"get_agent_work", "read_agent_work_output"})
    if method == "CancelTask":
        return frozenset({"cancel_agent_work", "get_agent_work"})
    return frozenset()  # anything else is answered by the SDK (unsupported)


class CallerClientPool:
    """Bounded gateway clients, one per (credential fingerprint, project); idle ones are released.

    The credential itself is never a key or a log value: only its SHA-256. Authorization decisions are never
    cached beyond ``capability_seconds``, so a revoked grant stops working within that window.
    """

    def __init__(self, factory: Callable[[str, str], Any], *, max_clients: int = 64, idle_seconds: float = 300.0,
                 capability_seconds: float = 15.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._factory, self._max, self._idle, self._ttl, self._clock = factory, max_clients, idle_seconds, capability_seconds, clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()

    @staticmethod
    def fingerprint(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def acquire(self, token: str, project_id: str) -> Any:
        key, now = (self.fingerprint(token), project_id), self._clock()
        evicted: list[Any] = []
        with self._lock:
            for old_key, old in list(self._entries.items()):
                if now - old["used"] > self._idle:
                    evicted.append(self._entries.pop(old_key)["client"])
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = {"client": self._factory(token, project_id), "caps": None, "caps_at": 0.0}
            entry["used"] = now
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                evicted.append(self._entries.popitem(last=False)[1]["client"])
        for client in evicted:
            _release(client)
        return entry["client"]

    def capabilities(self, token: str, project_id: str) -> frozenset[str]:
        """The operations the gateway allows this caller on this project (raises the gateway's own error)."""
        client = self.acquire(token, project_id)
        key, now = (self.fingerprint(token), project_id), self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry["caps"] is not None and now - entry["caps_at"] < self._ttl:
                return entry["caps"]
        capabilities = frozenset(str(item) for item in client.health().get("capabilities", ()))
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry["caps"], entry["caps_at"] = capabilities, now
        return capabilities

    def close(self) -> None:
        with self._lock:
            clients = [entry["client"] for entry in self._entries.values()]
            self._entries.clear()
        for client in clients:
            _release(client)


def _release(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # noqa: BLE001 - releasing a lease must never break a request
            logger.warning("a2a facade could not release a gateway client", exc_info=True)


def _bearer(request: Request) -> str | None:
    values = request.headers.getlist("authorization")
    if len(values) != 1:
        return None
    scheme, _, token = values[0].partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() and " " not in token.strip() else None


def _refusal(status: int, message: str) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def _classify(error: AudiaGenticError) -> tuple[int, str]:
    if error.code == "VAL-AGSV-005":
        if error.message == _PROJECT_NOT_AUTHORIZED:
            return 403, "not authorized for this project"
        return 401, "authentication failed"
    if error.code.startswith("NET-"):
        return 503, "gateway unavailable"
    return 502, "gateway error"


def build_a2a_app(routes: tuple[A2aRoute, ...], cards: Mapping[A2aRoute, pb.AgentCard], pool: CallerClientPool) -> Starlette:
    """The ASGI app. ``cards`` are built by the caller from published definitions (SH65b-3)."""
    asgi_routes: list[Route] = []
    for served in routes:
        def adapter_for(context: ServerCallContext, _route: A2aRoute = served) -> A2aServerAdapter:
            token = _bearer_from_context(context)
            return A2aServerAdapter(Path("."), _route.agent_id, pool.acquire(token, _route.project_id))

        handler = A2aSdkRequestHandler(adapter_for)
        inner = create_jsonrpc_routes(handler, served.path)[0].endpoint

        async def guarded(request: Request, _inner=inner, _route: A2aRoute = served):
            token = _bearer(request)
            if token is None:
                return _refusal(401, "a single bearer credential is required")
            raw = await request.body()
            if len(raw) > MAX_BODY_BYTES:
                return _refusal(413, "request too large")
            try:
                body = json.loads(raw)
            except ValueError:
                return await _inner(request)  # the SDK answers a malformed body with its own parse error
            if isinstance(body, dict) and isinstance(body.get("method"), str):
                needs = required_operations(body["method"], body["params"] if isinstance(body.get("params"), dict) else {})
                if needs:
                    try:
                        granted = await asyncio.to_thread(pool.capabilities, token, _route.project_id)
                    except AudiaGenticError as error:
                        status, message = _classify(error)
                        return _refusal(status, message)
                    except Exception:  # noqa: BLE001
                        logger.exception("a2a facade capability check failed")
                        return _refusal(502, "gateway error")
                    if not needs <= granted:
                        return _refusal(403, "the credential may not perform this operation")
            return await _inner(request)

        asgi_routes.append(Route(served.path, guarded, methods=["POST"]))
        asgi_routes.extend(create_agent_card_routes(cards[served], card_url=f"{served.path}/.well-known/agent-card.json"))
    @asynccontextmanager
    async def lifespan(_app: Starlette):
        yield
        await asyncio.to_thread(pool.close)  # release every gateway lease when the app stops

    return Starlette(routes=asgi_routes, lifespan=lifespan)


def _bearer_from_context(context: ServerCallContext) -> str:
    headers = context.state.get("headers") or {}
    value = headers.get("authorization", "")
    return value.partition(" ")[2].strip()
