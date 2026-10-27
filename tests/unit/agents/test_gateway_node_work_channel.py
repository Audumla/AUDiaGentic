"""Real TLS/control/work multiplexing, with no canonical or native effects."""
import asyncio
import base64
import hashlib
from dataclasses import replace
from unittest.mock import Mock

import pytest
from tests.unit.agents.test_gateway_node_transport import channel as channel
from tests.unit.agents.test_gateway_node_transport import tls as tls
from tests.unit.agents.test_gateway_node_transport import wait_until

from audiagentic.components.agents.gateway.node import connection as connection_module
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.components.agents.gateway.node.transport import NodeTransportClient
from audiagentic.components.agents.gateway.node.work_protocol import ArtifactChunk, EffectAuthorized
from audiagentic.foundation.contracts.errors import AudiaGenticError


async def ignore(*args):
    pass


async def pair(channel, gateway_handler=ignore, node_handler=ignore):
    def install(handler):
        async def configure(connection):
            connection.enable_work(lambda frame, message: handler(connection, frame, message),
                max_artifact_bytes=1024 * 1024)
        return configure
    channel.server._configure_work = install(gateway_handler)
    node = await NodeTransportClient(channel.client, node_epoch="boot-work",
        configure_work=install(node_handler)).connect()
    await wait_until(lambda: channel.server.owner._active["node"].connection is not None)
    gateway = channel.server.owner._active["node"].connection
    return node, gateway


def command(connection):
    c = connection.identity
    return CommandIdentity("command", "request", c.node_id, c.node_epoch,
        c.gateway_owner_epoch, c.connection_generation, "workspace", 1, 1, "a" * 64, "profile")


@pytest.mark.asyncio
async def test_effect_reply_retains_exact_frames_and_has_no_injected_generation(channel):
    async def authorize(connection, frame, message):
        await connection.send_work("effect-authorized", {"identity": message.identity.to_mapping(),
            "authorization-request-id": frame.message_id, "authorization-id": "authorization", "authorized": True})
    node, _ = await pair(channel, authorize)
    try:
        sent, reply, message = await node.request_work("effect-authorize",
            {"identity": command(node).to_mapping()}, reply_types=(EffectAuthorized,), timeout=2)
        assert "connection-generation" not in sent.payload
        assert "connection-generation" not in reply.payload
        assert message.authorization_request_id == sent.message_id
        assert message.identity == command(node)
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_control_stays_responsive_while_work_handler_is_blocked(channel):
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(*args):
        entered.set()
        await release.wait()
    node, gateway = await pair(channel, blocked)
    try:
        await node.send_work("effect-authorize", {"identity": command(node).to_mapping()})
        await asyncio.wait_for(entered.wait(), 2)
        before = gateway.last_liveness_at
        sequence = gateway._received_sequence
        await node.heartbeat()
        await wait_until(lambda: gateway._received_sequence == sequence + 1)
        assert gateway.last_liveness_at >= before  # Same Windows monotonic tick is valid.
        await gateway.notify_drain(2)
        await wait_until(lambda: node.capability == "drain")
        assert not release.is_set()
    finally:
        release.set()
        await node.close()


@pytest.mark.asyncio
async def test_reply_arrives_while_dispatcher_is_awaiting_that_reply(channel):
    complete = asyncio.Event()
    data = b"terminal evidence"
    sha = hashlib.sha256(data).hexdigest()
    async def gateway_handler(connection, frame, message):
        _, _, chunk = await connection.request_work("reconcile", {
            "kind": "artifact-get", "identity": command(connection).to_mapping(),
            "artifact-sha256": sha, "offset": 0, "limit": 1024,
        }, reply_types=(ArtifactChunk,), timeout=2)
        assert chunk.data == data
        complete.set()
    async def node_handler(connection, frame, message):
        await connection.send_work("reconcile-result", {
            "kind": "artifact-chunk", "in-reply-to": frame.message_id,
            "identity": message.identity.to_mapping(), "artifact-sha256": sha,
            "artifact-kind": "worker-terminal-result", "offset": 0, "total-bytes": len(data),
            "data": base64.b64encode(data).decode(), "eof": True,
        })
    node, _ = await pair(channel, gateway_handler, node_handler)
    try:
        await node.send_work("effect-authorize", {"identity": command(node).to_mapping()})
        await asyncio.wait_for(complete.wait(), 3)
    finally:
        await node.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["identity", "request"])
async def test_mismatched_pending_reply_closes_without_consuming_as_success(channel, mismatch):
    async def wrong(connection, frame, message):
        identity = replace(message.identity, command_id="different") if mismatch == "identity" else message.identity
        await connection.send_work("effect-authorized", {"identity": identity.to_mapping(),
            "authorization-request-id": "unsolicited" if mismatch == "request" else frame.message_id,
            "authorization-id": "authorization", "authorized": True})
    node, _ = await pair(channel, wrong)
    try:
        with pytest.raises(AudiaGenticError, match="closed while awaiting"):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=2)
        assert node.failure == "CON-AGND-001"
        assert node.failure_summary.reason_code == (
            "reply-command-mismatch" if mismatch == "identity" else "reply-unexpected")
        assert node.failure_summary.stage == "work-validation"
        assert node.failure_summary.frame_type == "effect-authorized"
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_work_overflow_closes_instead_of_unbounded_tasks(channel):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def blocked(*args):
        calls.append(1)
        entered.set()
        await release.wait()
    node, gateway = await pair(channel, blocked)
    try:
        payload = {"identity": command(node).to_mapping()}
        await node.send_work("effect-authorize", payload)
        await asyncio.wait_for(entered.wait(), 2)
        for _ in range(9):
            await node.send_work("effect-authorize", payload)
        await asyncio.wait_for(gateway.wait_closed(), 2)
        assert gateway.failure == "CON-AGND-001"
        assert calls == [1]
    finally:
        release.set()
        await node.close()


@pytest.mark.asyncio
async def test_reply_timeout_retires_channel_and_releases_pending_slot(channel):
    entered = asyncio.Event()
    requests = []

    async def delayed_reply(connection, frame, message):
        requests.append(frame.message_id)
        entered.set()
        await asyncio.sleep(0.2)
        await connection.send_work("effect-authorized", {"identity": message.identity.to_mapping(),
            "authorization-request-id": frame.message_id, "authorization-id": "authorization", "authorized": True})

    node, gateway = await pair(channel, delayed_reply)
    try:
        with pytest.raises(TimeoutError):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=0.05)
        assert entered.is_set()
        assert node.close_reason == "shutdown"
        assert node._pending == {}
        await asyncio.wait_for(node.wait_closed(), 2)
        await asyncio.wait_for(gateway.wait_closed(), 2)
        await asyncio.sleep(0.25)  # Past the peer's original reply deadline.
        assert node.failure is None
        assert not node._task.cancelled()
        assert len(requests) == 1
        with pytest.raises(AudiaGenticError, match="closed"):
            await node.heartbeat()
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_cancelled_outstanding_request_retires_channel_without_cancelling_receiver(channel):
    entered = asyncio.Event()
    requests = []

    async def pending_reply(connection, frame, message):
        requests.append(frame.message_id)
        entered.set()
        await asyncio.Event().wait()

    node, gateway = await pair(channel, pending_reply)
    task = asyncio.create_task(node.request_work("effect-authorize",
        {"identity": command(node).to_mapping()}, reply_types=(EffectAuthorized,), timeout=10))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert node.close_reason == "shutdown"
        assert node._pending == {}
        await asyncio.wait_for(node.wait_closed(), 2)
        await asyncio.wait_for(gateway.wait_closed(), 2)
        assert node.failure is None
        assert not node._task.cancelled()
        assert len(requests) == 1
        with pytest.raises(AudiaGenticError, match="closed"):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=1)
        assert node._pending == {}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await node.close()


@pytest.mark.asyncio
async def test_pending_capacity_is_bounded_and_close_releases_waiters(channel):
    entered = asyncio.Event()
    async def handler(*args):
        entered.set()
    node, _ = await pair(channel, handler)
    pending = []
    try:
        for _ in range(4):
            pending.append(asyncio.create_task(node.request_work("effect-authorize",
                {"identity": command(node).to_mapping()}, reply_types=(EffectAuthorized,), timeout=10)))
        await wait_until(lambda: len(node._pending) == 4)
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(AudiaGenticError, match="capacity"):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=2)
        await node.close()
        results = await asyncio.gather(*pending, return_exceptions=True)
        assert all(isinstance(result, AudiaGenticError) for result in results)
        assert node._pending == {}
    finally:
        await node.close()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_invalid_outbound_work_does_not_consume_sequence(channel):
    node, gateway = await pair(channel)
    try:
        sequence = node._sent_sequence
        with pytest.raises(AudiaGenticError):
            await node.send_work("effect-authorize", {"identity": replace(command(node), connection_generation=99).to_mapping()})
        assert node._sent_sequence == sequence
        await node.heartbeat()
        await wait_until(lambda: gateway._received_sequence == sequence + 1)
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_first_failure_survives_cleanup_without_private_exception_text(channel, caplog):
    secret = "PRIVATE-CONTENT credential and caller locator must not be logged"
    async def fail(*args):
        raise RuntimeError(secret)
    node, gateway = await pair(channel, fail)
    observed = []
    async def closed():
        observed.append(gateway.failure_summary)
    gateway._on_close = closed
    try:
        await node.send_work("effect-authorize", {"identity": command(node).to_mapping()})
        await asyncio.wait_for(gateway.wait_closed(), 2)
        first = gateway.failure_summary
        assert first is not None
        assert (first.code, first.stage, first.reason_code) == (
            "IO-AGND-001", "dispatch", "work-handler-failed")
        assert observed == [first]
        gateway._remember_failure(RuntimeError("later failure"), stage="cleanup", reason="cleanup-failed")
        assert gateway.failure_summary is first
        assert secret not in caplog.text
        assert secret not in repr(first)
        assert first.connection_generation == gateway.identity.connection_generation
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_broken_logging_sink_does_not_mask_channel_error_or_close_owner(channel, monkeypatch):
    async def fail(*args):
        raise RuntimeError("primary PRIVATE error")
    node, gateway = await pair(channel, fail)
    completed = asyncio.Event()
    async def closed():
        completed.set()
    gateway._on_close = closed
    logger = Mock()
    logger.warning.side_effect = OSError("logging disk full")
    monkeypatch.setattr(connection_module, "logger", logger)
    try:
        await node.send_work("effect-authorize", {"identity": command(node).to_mapping()})
        await asyncio.wait_for(gateway.wait_closed(), 2)
        assert completed.is_set()
        assert gateway.failure_summary.reason_code == "work-handler-failed"
        assert gateway.diagnostic_failure_count == 1
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_send_failure_records_first_cause_without_exception_payload(channel, monkeypatch, caplog):
    node, _ = await pair(channel)
    async def fail(*args):
        raise OSError("PRIVATE send body and credential")
    monkeypatch.setattr(node.websocket, "send", fail)
    try:
        with pytest.raises(OSError):
            await node.heartbeat()
        await asyncio.wait_for(node.wait_closed(), 2)
        assert node.failure_summary.stage == "send"
        assert node.failure_summary.reason_code == "transport-send-failed"
        assert node.failure_summary.frame_type == "heartbeat"
        assert "PRIVATE" not in caplog.text
    finally:
        await node.close()


@pytest.mark.asyncio
async def test_owner_replacement_is_distinguished_from_protocol_failure(channel):
    node, gateway = await pair(channel)
    replacement = None
    try:
        replacement = await NodeTransportClient(channel.client, node_epoch="replacement-boot").connect()
        await asyncio.wait_for(gateway.wait_closed(), 2)
        assert gateway.close_reason == "replacement"
        assert gateway.failure_summary is None
    finally:
        await node.close()
        if replacement is not None:
            await replacement.close()


@pytest.mark.asyncio
async def test_async_runtime_setup_is_awaited_before_receiver_start(channel):
    entered, release = asyncio.Event(), asyncio.Event()
    connections = []
    async def configure(connection):
        connection.enable_work(ignore, max_artifact_bytes=1024)
        connections.append(connection)
        entered.set()
        await release.wait()
    pending = asyncio.create_task(NodeTransportClient(channel.client, node_epoch="setup-boot",
        configure_work=configure).connect())
    node = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert connections[0]._task is None
        assert not pending.done()
        release.set()
        node = await asyncio.wait_for(pending, 2)
        assert node._task is not None
    finally:
        release.set()
        if node is None:
            node = await pending
        await node.close()


@pytest.mark.asyncio
async def test_failed_async_setup_notifies_partial_owner_once_before_receiver_start(channel):
    notifications, connections = [], []
    async def configure(connection):
        async def closed():
            notifications.append(connection.failure_summary)
        connection.enable_work(ignore, max_artifact_bytes=1024, on_close=closed)
        connections.append(connection)
        raise RuntimeError("PRIVATE setup failure")
    with pytest.raises(RuntimeError, match="PRIVATE setup"):
        await NodeTransportClient(channel.client, node_epoch="setup-failed",
            configure_work=configure).connect()
    node, = connections
    assert node._task is None
    assert len(notifications) == 1
    assert notifications[0].stage == "configuration"
    await node.close()
    assert len(notifications) == 1
    with pytest.raises(AudiaGenticError, match="closed"):
        node.start()


@pytest.mark.asyncio
async def test_retirement_discards_already_queued_work(channel):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def blocked(connection, frame, work):
        seen.append(frame.message_id)
        entered.set()
        await release.wait()

    node, gateway = await pair(channel, blocked)
    try:
        payload = {"identity": command(node).to_mapping()}
        first = await node.send_work("effect-authorize", payload)
        await asyncio.wait_for(entered.wait(), 2)
        await node.send_work("effect-authorize", payload)
        await wait_until(lambda: gateway._work_inbox.qsize() == 1)
        gateway.begin_close("shutdown")
        release.set()
        await asyncio.wait_for(asyncio.shield(gateway._work_task), 2)
        assert seen == [first.message_id]
        assert gateway.failure_summary is None
    finally:
        release.set()
        await gateway.close()
        await node.close()


@pytest.mark.asyncio
async def test_request_timeout_closes_real_socket_when_immediate_abort_fails(channel, monkeypatch):
    node, gateway = await pair(channel)
    original_abort = node.websocket.transport.abort

    def fail_first_abort():
        if abort.call_count == 1:
            raise OSError("abort unavailable")
        return original_abort()

    abort = Mock(side_effect=fail_first_abort)
    monkeypatch.setattr(node.websocket.transport, "abort", abort)
    try:
        with pytest.raises(TimeoutError):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=0.02)
        await asyncio.wait_for(node.wait_closed(), 2)
        assert node.close_reason == "shutdown"
        assert node.failure_summary is None
        assert not node._pending
        assert node.websocket.close_code is not None
        assert abort.call_count >= 1
    finally:
        monkeypatch.setattr(node.websocket.transport, "abort", original_abort)
        await node.close()
        await gateway.close()
