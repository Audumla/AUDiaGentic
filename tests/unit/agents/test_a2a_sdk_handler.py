"""SH65: the A2A adapter served through the pinned a2a-sdk JSON-RPC routes, over a real ASGI wire (SDK models, no mocks of the SDK)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("a2a.server.routes", reason="needs the optional `a2a` extra (a2a-sdk[http-server])")
pytest.importorskip("starlette")
httpx = pytest.importorskip("httpx")

from starlette.applications import Starlette  # noqa: E402

from a2a.server.routes import create_jsonrpc_routes  # noqa: E402
from audiagentic.components.agents.protocols.a2a import A2aServerAdapter  # noqa: E402
from audiagentic.components.agents.protocols.a2a.sdk_handler import A2aSdkRequestHandler  # noqa: E402

from a2a.utils.constants import VERSION_HEADER  # noqa: E402

from .test_a2a_adapter import FakePorts  # noqa: E402

#: A 1.0 client declares the protocol version it speaks; a request without the header is treated as 0.3.
VERSION = {VERSION_HEADER: "1.0"}


def _app(tmp_path: Path, ports: FakePorts) -> Starlette:
    handler = A2aSdkRequestHandler(A2aServerAdapter(tmp_path, "agent-a", ports))
    return Starlette(routes=create_jsonrpc_routes(handler, "/a2a"))


async def _rpc(app, method: str, params: dict, request_id: int = 1) -> dict:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/a2a", headers=VERSION,
                                     json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    assert response.status_code == 200, response.text
    return response.json()


def _send(message_id="m1", text="hello", **message) -> dict:
    return {"message": {"messageId": message_id, "role": "ROLE_USER", "parts": [{"text": text}], **message}}


@pytest.mark.asyncio
async def test_send_message_returns_a_proto_json_task_with_the_canonical_state(tmp_path: Path) -> None:
    body = await _rpc(_app(tmp_path, FakePorts()), "SendMessage", _send(contextId="ctx-a"))
    task = body["result"]["task"]
    assert task["contextId"] == "ctx-a" and task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["artifacts"][0]["parts"] == [{"text": "done"}]


@pytest.mark.asyncio
async def test_return_immediately_does_not_wait_and_reports_the_working_task(tmp_path: Path) -> None:
    ports = FakePorts()
    params = {**_send(contextId="ctx-a"), "configuration": {"returnImmediately": True}}
    body = await _rpc(_app(tmp_path, ports), "SendMessage", params)
    assert body["result"]["task"]["status"]["state"] == "TASK_STATE_WORKING"
    assert not any(call[0] == "wait" for call in ports.calls)


@pytest.mark.asyncio
async def test_task_id_continues_the_work_and_get_task_reads_it(tmp_path: Path) -> None:
    ports = FakePorts(final_state="active")
    app = _app(tmp_path, ports)
    first = (await _rpc(app, "SendMessage", _send("m1", "start", contextId="ctx-a")))["result"]["task"]
    follow = (await _rpc(app, "SendMessage", _send("m2", "more", taskId=first["id"], contextId="ctx-a")))["result"]["task"]
    assert follow["id"] == first["id"]
    fetched = (await _rpc(app, "GetTask", {"id": first["id"]}))["result"]
    assert fetched["id"] == first["id"] and fetched["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.asyncio
async def test_cancel_a_running_task_and_refuse_a_finished_one(tmp_path: Path) -> None:
    app = _app(tmp_path, FakePorts(final_state="active"))
    task = (await _rpc(app, "SendMessage", _send(contextId="ctx-a")))["result"]["task"]
    cancelled = (await _rpc(app, "CancelTask", {"id": task["id"]}))["result"]
    assert cancelled["status"]["state"] == "TASK_STATE_CANCELED"
    done = _app(tmp_path, FakePorts())
    finished = (await _rpc(done, "SendMessage", _send(contextId="ctx-a")))["result"]["task"]
    error = (await _rpc(done, "CancelTask", {"id": finished["id"]}))["error"]
    assert error["code"] == -32002  # TaskNotCancelable


@pytest.mark.asyncio
async def test_unknown_task_is_task_not_found(tmp_path: Path) -> None:
    error = (await _rpc(_app(tmp_path, FakePorts()), "GetTask", {"id": "nope"}))["error"]
    assert error["code"] == -32001


@pytest.mark.asyncio
async def test_a_replayed_message_returns_the_same_task_and_a_changed_payload_is_invalid_params(tmp_path: Path) -> None:
    app = _app(tmp_path, FakePorts())
    one = (await _rpc(app, "SendMessage", _send("m1", "same", contextId="ctx-a")))["result"]["task"]
    again = (await _rpc(app, "SendMessage", _send("m1", "same", contextId="ctx-a")))["result"]["task"]
    assert one["id"] == again["id"]
    error = (await _rpc(app, "SendMessage", _send("m1", "different", contextId="ctx-a")))["error"]
    assert error["code"] == -32602


@pytest.mark.asyncio
async def test_rich_parts_are_content_type_not_supported_and_a_missing_message_id_is_invalid(tmp_path: Path) -> None:
    app = _app(tmp_path, FakePorts())
    rich = {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"url": "https://example.invalid/x"}]}}
    assert (await _rpc(app, "SendMessage", rich))["error"]["code"] == -32005
    no_id = {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}}
    assert (await _rpc(app, "SendMessage", no_id))["error"]["code"] == -32602
    agent_role = {"message": {"messageId": "m2", "role": "ROLE_AGENT", "parts": [{"text": "hi"}]}}
    assert (await _rpc(app, "SendMessage", agent_role))["error"]["code"] == -32602


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["SendStreamingMessage", "SubscribeToTask"])
async def test_streaming_and_resubscription_are_unsupported(tmp_path: Path, method: str) -> None:
    transport = httpx.ASGITransport(app=_app(tmp_path, FakePorts()))
    params = _send(contextId="ctx-a") if method == "SendStreamingMessage" else {"id": "x"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/a2a", headers=VERSION,
                                     json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    assert response.json()["error"]["code"] == -32004


@pytest.mark.asyncio
async def test_a_request_without_the_version_header_is_refused_as_version_not_supported(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(app=_app(tmp_path, FakePorts()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/a2a", json={"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "x"}})
    assert response.json()["error"]["code"] == -32009


# --- the SDK's own client against the same server -------------------------------------------------------


def _card() -> "pb.AgentCard":
    from a2a.types import a2a_pb2 as pb

    card = pb.AgentCard(name="agent-a", description="test", version="1")
    interface = card.supported_interfaces.add()
    interface.url, interface.protocol_binding, interface.protocol_version = "http://test/a2a", "JSONRPC", "1.0"
    return card


def _sdk_client(app):
    from a2a.client import ClientConfig, ClientFactory

    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return ClientFactory(ClientConfig(streaming=False, httpx_client=http, supported_protocol_bindings=["JSONRPC"])).create(_card())


@pytest.mark.asyncio
async def test_the_sdk_client_completes_send_get_and_cancel_against_the_handler(tmp_path: Path) -> None:
    from a2a.types import a2a_pb2 as pb

    app = _app(tmp_path, FakePorts(final_state="active"))
    client = _sdk_client(app)
    request = pb.SendMessageRequest(message=pb.Message(
        message_id="m1", context_id="ctx-a", role=pb.ROLE_USER, parts=[pb.Part(text="hello")]))
    events = [event async for event in client.send_message(request)]
    task = events[-1].task
    assert task.context_id == "ctx-a" and task.status.state == pb.TASK_STATE_WORKING
    fetched = await client.get_task(pb.GetTaskRequest(id=task.id))
    assert fetched.id == task.id and fetched.status.state == pb.TASK_STATE_WORKING
    cancelled = await client.cancel_task(pb.CancelTaskRequest(id=task.id))
    assert cancelled.status.state == pb.TASK_STATE_CANCELED


@pytest.mark.asyncio
async def test_the_sdk_client_surfaces_a_refused_message_as_a_client_error(tmp_path: Path) -> None:
    from a2a.types import a2a_pb2 as pb

    client = _sdk_client(_app(tmp_path, FakePorts()))
    bad = pb.SendMessageRequest(message=pb.Message(message_id="m1", role=pb.ROLE_AGENT, parts=[pb.Part(text="x")]))
    with pytest.raises(Exception) as raised:  # the SDK maps JSON-RPC error codes onto its own exception types
        _ = [event async for event in client.send_message(bad)]
    assert "-32602" in repr(raised.value) or "Invalid" in repr(raised.value) or "invalid" in str(raised.value).lower()
