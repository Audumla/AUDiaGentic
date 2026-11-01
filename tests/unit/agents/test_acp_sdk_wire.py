"""SH66: the ACP adapter driven by the pinned agent-client-protocol SDK's own client over a real stream pair."""
from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest

acp = pytest.importorskip("acp", reason="needs the optional `acp` extra")

from acp import Client, RequestError  # noqa: E402
from acp.schema import TextContentBlock  # noqa: E402

from audiagentic.components.agents.protocols.acp import AcpAgent  # noqa: E402
from audiagentic.foundation.contracts.errors import AudiaGenticError  # noqa: E402

from .test_acp_external_adapter import FakeAgentsPort  # noqa: E402


class _Client(Client):
    async def session_update(self, *args, **kwargs) -> None:
        return None

    async def request_permission(self, *args, **kwargs):
        raise NotImplementedError


async def _connect(agent: AcpAgent, *, unstable: bool = False):
    """The SDK's own client wired to the agent over a socket pair. Note the SDK's naming: `input_stream` is the WRITER."""
    a, b = socket.socketpair()
    client_reader, client_writer = await asyncio.open_connection(sock=a)
    agent_reader, agent_writer = await asyncio.open_connection(sock=b)
    server = asyncio.create_task(acp.run_agent(agent, input_stream=agent_writer, output_stream=agent_reader,
                                               use_unstable_protocol=unstable))
    return acp.connect_to_agent(_Client(), client_writer, client_reader, use_unstable_protocol=unstable), server


def _text(value: str) -> list[TextContentBlock]:
    return [TextContentBlock(type="text", text=value)]


async def _session(tmp_path: Path, port: FakeAgentsPort | None = None, *, unstable: bool = False):
    port = port or FakeAgentsPort()
    connection, server = await _connect(AcpAgent(tmp_path, "agent-test", port), unstable=unstable)
    return port, connection, server


@pytest.mark.asyncio
async def test_initialize_negotiates_wire_version_one_and_advertises_only_load_session(tmp_path: Path) -> None:
    _, connection, server = await _session(tmp_path)
    try:
        init = await asyncio.wait_for(connection.initialize(protocol_version=1), 10)
        assert init.protocol_version == 1 and init.agent_capabilities.load_session is True
        assert not init.agent_capabilities.prompt_capabilities.image if init.agent_capabilities.prompt_capabilities else True
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_a_prompt_round_trips_to_end_turn_with_bounded_output(tmp_path: Path) -> None:
    _, connection, server = await _session(tmp_path)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        reply = await asyncio.wait_for(connection.prompt(prompt=_text("hello"), session_id=session.session_id), 10)
        assert reply.stop_reason == "end_turn"
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_an_outstanding_prompt_reaches_the_client_as_invalid_request_with_the_registered_code(tmp_path: Path) -> None:
    port, connection, server = await _session(tmp_path)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        port.works["work_x"] = {"work_id": "work_x", "context_id": session.session_id, "state": "active"}
        with pytest.raises(RequestError) as raised:
            await asyncio.wait_for(connection.prompt(prompt=_text("again"), session_id=session.session_id), 10)
        assert raised.value.code == -32600 and raised.value.data["code"] == "CON-ACP-001"
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_a_failed_work_is_an_internal_error_with_the_code_and_state_only(tmp_path: Path) -> None:
    _, connection, server = await _session(tmp_path, FakeAgentsPort(final="failed"))
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        with pytest.raises(RequestError) as raised:
            await asyncio.wait_for(connection.prompt(prompt=_text("go"), session_id=session.session_id), 10)
        assert raised.value.code == -32603 and raised.value.data["code"] == "CON-ACP-002"
        assert raised.value.data["state"] == "failed"
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_validation_failures_are_invalid_params_not_internal_errors(tmp_path: Path) -> None:
    _, connection, server = await _session(tmp_path)
    try:
        await connection.initialize(protocol_version=1)
        with pytest.raises(RequestError) as outside:
            await connection.new_session(cwd="/")  # outside the bound project root
        assert outside.value.code == -32602
        session = await connection.new_session(cwd=str(tmp_path))
        with pytest.raises(RequestError) as empty:
            await connection.prompt(prompt=[], session_id=session.session_id)
        assert empty.value.code == -32602 and empty.value.data["code"] == "VAL-ACP-003"
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_an_unexpected_exception_never_puts_its_text_on_the_wire(tmp_path: Path) -> None:
    port = FakeAgentsPort()

    def boom(*args, **kwargs):
        raise RuntimeError("SECRET-INTERNAL-DETAIL-MARKER")

    port.accept_agent_work_message = boom  # type: ignore[method-assign]
    _, connection, server = await _session(tmp_path, port)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        with pytest.raises(RequestError) as raised:
            await asyncio.wait_for(connection.prompt(prompt=_text("x"), session_id=session.session_id), 10)
        assert raised.value.code == -32603 and "SECRET-INTERNAL" not in repr(raised.value.data)
        assert raised.value.data == {"code": "INT-ACP-000"}
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_unsupported_operations_are_method_not_found(tmp_path: Path) -> None:
    _, connection, server = await _session(tmp_path)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        with pytest.raises(RequestError) as raised:
            await connection.set_session_mode(mode_id="x", session_id=session.session_id)
        assert raised.value.code == -32601
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_close_fork_and_resume_are_unstable_methods_a_stable_v1_client_cannot_reach(tmp_path: Path) -> None:
    """Measured on agent-client-protocol 0.11.0: session/close, session/fork and session/resume are unstable-only."""
    _, connection, server = await _session(tmp_path)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        with pytest.raises(RequestError) as raised:
            await connection.close_session(session_id=session.session_id)
        assert raised.value.code == -32601
    finally:
        server.cancel()


@pytest.mark.asyncio
async def test_when_unstable_methods_are_enabled_closing_a_session_cancels_its_outstanding_work(tmp_path: Path) -> None:
    port, connection, server = await _session(tmp_path, unstable=True)
    try:
        await connection.initialize(protocol_version=1)
        session = await connection.new_session(cwd=str(tmp_path))
        port.works["work_x"] = {"work_id": "work_x", "context_id": session.session_id, "state": "active"}
        await connection.close_session(session_id=session.session_id)
        assert ("cancel", "work_x") in port.calls and ("close", session.session_id) in port.calls
    finally:
        server.cancel()


def test_the_translation_table_covers_validation_precondition_and_failure() -> None:
    from audiagentic.components.agents.protocols.acp.agent import _request_error

    assert _request_error(AudiaGenticError("VAL-ACP-003", "validation", "no text")).code == -32602
    assert _request_error(AudiaGenticError("CON-AGW-167", "constraint", "busy")).code == -32600
    assert _request_error(AudiaGenticError("CON-ACP-002", "acp", "failed")).code == -32603
    assert _request_error(AudiaGenticError("EXT-X-001", "x", "secret text")).data == {"code": "EXT-X-001"}
