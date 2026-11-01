"""SH65b-2: the A2A facade in front of a REAL shared-gateway HTTP server (facade -> real client -> real ingress)."""
from __future__ import annotations

import pytest

pytest.importorskip("a2a.server.routes", reason="needs the optional `a2a` extra (a2a-sdk[http-server])")
httpx = pytest.importorskip("httpx")

from a2a.types import a2a_pb2 as pb  # noqa: E402
from a2a.utils.constants import VERSION_HEADER  # noqa: E402

from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient  # noqa: E402
from audiagentic.components.agents.protocols.a2a.facade import (  # noqa: E402
    A2aRoute,
    CallerClientPool,
    build_a2a_app,
    required_operations,
)

from .test_gateway_shared_ingress import shared  # noqa: E402,F401  (the real shared-gateway server fixture)

ONE, TWO = A2aRoute("one", "agent-a"), A2aRoute("two", "agent-a")


def _card(route: A2aRoute) -> pb.AgentCard:
    card = pb.AgentCard(name=route.agent_id, description="test", version="1")
    interface = card.supported_interfaces.add()
    interface.url, interface.protocol_binding, interface.protocol_version = f"http://test{route.path}", "JSONRPC", "1.0"
    return card


class _Gateway:
    """The fake application behind the real shared server: just enough Work behaviour for an A2A round trip."""

    def __init__(self, application) -> None:
        self.works: dict[str, dict] = {}
        self.calls: list[tuple] = []
        application.open_agent_context = self.open_context
        application.get_agent_context = lambda root, cid: {"context_id": cid, "state": "open"}
        application.accept_agent_work_message = self.accept
        application.wait_agent_work = self.wait
        application.get_agent_work = self.get_work
        application.read_agent_work_output = lambda root, wid: {"text": f"done:{wid}"}
        application.cancel_agent_work = self.cancel

    def get_work(self, root, work_id):
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        if work_id not in self.works:  # what the real owner raises since RES-AGW-153
            raise AudiaGenticError("RES-AGW-153", "agent-work", "No Work with this id exists in the project")
        return dict(self.works[work_id])

    def open_context(self, root, agent_id, title=None):
        self.calls.append(("open", root.name))
        return {"context_id": f"ctx_{root.name}"}

    def accept(self, root, context_id, message, *, delivery_identity, work_id=None, intent=None, exclusive=False):
        self.calls.append(("accept", root.name, delivery_identity["principal"], delivery_identity["protocol"]))
        wid = work_id or f"work_{message['message_id']}"
        self.works.setdefault(wid, {"work_id": wid, "context_id": context_id, "state": "active"})
        return dict(self.works[wid])

    def wait(self, root, work_id, timeout_seconds=None):
        self.calls.append(("wait", root.name))
        self.works[work_id]["state"] = "completed"
        return {"work": dict(self.works[work_id]), "wait-outcome": "terminal"}

    def cancel(self, root, work_id):
        self.calls.append(("cancel", root.name))
        self.works[work_id]["state"] = "cancelled"
        return dict(self.works[work_id])


@pytest.fixture
def stack(shared):  # noqa: F811
    gateway = _Gateway(shared.application._application)
    port = shared.server.server_port

    def factory(token: str, project: str) -> StandaloneGatewayClient:
        return StandaloneGatewayClient(f"http://127.0.0.1:{port}", token, shared_server_id="test", shared_project_id=project)

    pool = CallerClientPool(factory)
    app = build_a2a_app((ONE, TWO), {ONE: _card(ONE), TWO: _card(TWO)}, pool)
    yield app, gateway, pool
    pool.close()


async def _post(app, route: A2aRoute, method: str, params: dict, token: str | None = "token-alice", **headers):
    sent = {VERSION_HEADER: "1.0", **headers}
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(route.path, headers=sent, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _send(text="hello", message_id="m1", **message) -> dict:
    return {"message": {"messageId": message_id, "role": "ROLE_USER", "parts": [{"text": text}], **message}}


@pytest.mark.asyncio
async def test_a_send_message_runs_through_the_real_gateway_as_the_authenticated_principal(stack) -> None:
    app, gateway, _ = stack
    response = await _post(app, ONE, "SendMessage", _send())
    task = response.json()["result"]["task"]
    assert response.status_code == 200 and task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["parts"] == [{"text": f"done:{task['id']}"}]
    # The gateway, not the facade, established who sent it: alice's own token, over protocol a2a, in project one.
    assert ("accept", "one", "alice", "a2a") in gateway.calls and ("open", "one") in gateway.calls


@pytest.mark.asyncio
async def test_missing_malformed_and_unknown_credentials_are_401(stack) -> None:
    app, gateway, _ = stack
    for token, extra in ((None, {}), ("wrong-token", {})):
        response = await _post(app, ONE, "SendMessage", _send(), token=token, **extra)
        assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer", token
    two = await _post(app, ONE, "SendMessage", _send(), token=None, Authorization="Basic abc")
    assert two.status_code == 401
    assert not gateway.calls  # nothing reached the gateway's Work operations


@pytest.mark.asyncio
async def test_a_credential_without_the_project_grant_is_403(stack) -> None:
    app, gateway, _ = stack
    response = await _post(app, ONE, "SendMessage", _send(), token="token-bob")  # bob is granted project two only
    assert response.status_code == 403 and not gateway.calls
    ok = await _post(app, TWO, "SendMessage", _send(message_id="m2"), token="token-bob")
    assert ok.status_code == 200 and ("accept", "two", "bob", "a2a") in gateway.calls


@pytest.mark.asyncio
async def test_a_blocking_send_needs_submit_and_read_and_is_refused_before_anything_is_accepted(stack) -> None:
    app, gateway, _ = stack
    observer = await _post(app, ONE, "SendMessage", _send(), token="token-observer")  # read only, no submit
    assert observer.status_code == 403
    assert not [call for call in gateway.calls if call[0] in {"accept", "open"}]
    quick = await _post(app, ONE, "SendMessage", {**_send(message_id="m3"), "configuration": {"returnImmediately": True}},
                        token="token-observer")
    assert quick.status_code == 403  # submit is needed either way


@pytest.mark.asyncio
async def test_return_immediately_needs_submit_only_and_does_not_wait(stack) -> None:
    app, gateway, _ = stack
    response = await _post(app, ONE, "SendMessage", {**_send(), "configuration": {"returnImmediately": True}})
    assert response.status_code == 200
    assert response.json()["result"]["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert not [call for call in gateway.calls if call[0] == "wait"]


@pytest.mark.asyncio
async def test_get_task_is_a_read_and_cancel_needs_the_cancel_action(stack) -> None:
    app, gateway, _ = stack
    task = (await _post(app, ONE, "SendMessage", {**_send(), "configuration": {"returnImmediately": True}})).json()["result"]["task"]
    read = await _post(app, ONE, "GetTask", {"id": task["id"]}, token="token-observer")
    assert read.status_code == 200 and read.json()["result"]["id"] == task["id"]
    denied = await _post(app, ONE, "CancelTask", {"id": task["id"]}, token="token-alice")  # submit/read/session, no cancel
    assert denied.status_code == 403 and not [call for call in gateway.calls if call[0] == "cancel"]
    allowed = await _post(app, ONE, "CancelTask", {"id": task["id"]}, token="token-canceller")
    assert allowed.status_code == 200 and allowed.json()["result"]["status"]["state"] == "TASK_STATE_CANCELED"


@pytest.mark.asyncio
async def test_each_caller_gets_its_own_gateway_client_and_the_credential_is_never_a_key(stack) -> None:
    app, _, pool = stack
    await _post(app, ONE, "SendMessage", _send(), token="token-alice")
    await _post(app, TWO, "SendMessage", _send(message_id="m2"), token="token-bob")
    keys = list(pool._entries)
    assert len(keys) == 2 and {project for _, project in keys} == {"one", "two"}
    assert all("token-" not in fingerprint for fingerprint, _ in keys) and all(len(f) == 64 for f, _ in keys)


@pytest.mark.asyncio
async def test_the_agent_card_is_public_and_names_its_own_route(stack) -> None:
    app, _, _ = stack
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"{ONE.path}/.well-known/agent-card.json")
    assert response.status_code == 200
    assert response.json()["supportedInterfaces"][0]["url"] == f"http://test{ONE.path}"


def test_required_operations_follow_the_call_shape() -> None:
    fresh = required_operations("SendMessage", {"message": {"messageId": "m"}})
    assert fresh == {"accept_agent_work_message", "open_agent_context", "wait_agent_work", "get_agent_work", "read_agent_work_output"}
    quick = required_operations("SendMessage", {"message": {"contextId": "c"}, "configuration": {"returnImmediately": True}})
    assert quick == {"accept_agent_work_message", "get_agent_context"}
    follow = required_operations("SendMessage", {"message": {"taskId": "t"}, "configuration": {"returnImmediately": True}})
    assert follow == {"accept_agent_work_message", "get_agent_work", "get_agent_context"}
    assert required_operations("GetTask", {}) == {"get_agent_work", "read_agent_work_output"}
    assert required_operations("CancelTask", {}) == {"cancel_agent_work", "get_agent_work"}
    assert required_operations("SendStreamingMessage", {}) == frozenset()


class _Client:
    def __init__(self, caps=("accept_agent_work_message",)) -> None:
        self.closed, self.caps, self.health_calls = False, caps, 0

    def health(self):
        self.health_calls += 1
        return {"capabilities": list(self.caps)}

    def close(self) -> None:
        self.closed = True


def test_the_pool_evicts_idle_clients_bounds_its_size_and_refreshes_capabilities() -> None:
    now = [0.0]
    made: list[_Client] = []

    def factory(token, project):
        made.append(_Client())
        return made[-1]

    pool = CallerClientPool(factory, max_clients=2, idle_seconds=100, capability_seconds=10, clock=lambda: now[0])
    pool.acquire("t1", "p")
    assert pool.capabilities("t1", "p") == {"accept_agent_work_message"} and made[0].health_calls == 1
    pool.capabilities("t1", "p")
    assert made[0].health_calls == 1  # cached inside the window
    now[0] = 11.0
    pool.capabilities("t1", "p")
    assert made[0].health_calls == 2  # a revoked grant is noticed after the window
    pool.acquire("t2", "p")
    pool.acquire("t3", "p")  # over the bound: the least recently used is released
    assert made[0].closed and len(pool._entries) == 2
    now[0] = 500.0
    pool.acquire("t4", "p")  # idle entries are released
    assert made[1].closed and made[2].closed
    pool.close()
    assert all(client.closed for client in made)


# --- a real socket: uvicorn on loopback, the SDK's own client, a bearer token ------------------------------


@pytest.mark.asyncio
async def test_the_sdk_client_reaches_the_facade_over_a_real_loopback_socket_with_its_bearer(stack) -> None:
    import asyncio
    import socket

    uvicorn = pytest.importorskip("uvicorn")
    from a2a.client import ClientConfig, ClientFactory

    app, gateway, _ = stack
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started
        card = pb.AgentCard(name="agent-a", description="test", version="1")
        interface = card.supported_interfaces.add()
        interface.url, interface.protocol_binding, interface.protocol_version = (
            f"http://127.0.0.1:{port}{ONE.path}", "JSONRPC", "1.0")
        async with httpx.AsyncClient(headers={"Authorization": "Bearer token-alice"}) as http:
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=http,
                                                supported_protocol_bindings=["JSONRPC"])).create(card)
            request = pb.SendMessageRequest(message=pb.Message(message_id="m9", role=pb.ROLE_USER, parts=[pb.Part(text="hi")]))
            events = [event async for event in client.send_message(request)]
            assert events[-1].task.status.state == pb.TASK_STATE_COMPLETED
            fetched = await client.get_task(pb.GetTaskRequest(id=events[-1].task.id))
            assert fetched.id == events[-1].task.id
        assert ("accept", "one", "alice", "a2a") in gateway.calls
        # The same socket without a credential is refused before the gateway is touched.
        async with httpx.AsyncClient() as bare:
            refused = await bare.post(f"http://127.0.0.1:{port}{ONE.path}", headers={VERSION_HEADER: "1.0"},
                                      json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}})
        assert refused.status_code == 401
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


@pytest.mark.asyncio
async def test_an_unknown_task_crosses_the_gateway_and_is_reported_without_internals(stack) -> None:
    app, _, _ = stack
    response = await _post(app, ONE, "GetTask", {"id": "work_does_not_exist"})
    body = response.json()
    assert response.status_code == 200 and "error" in body
    # Whatever the gateway says, a client sees a JSON-RPC error with no path, traceback or exception text.
    assert body["error"]["code"] == -32001  # TaskNotFound, preserved across the gateway's error envelope
    assert "Traceback" not in response.text and "KeyError" not in response.text
