"""Real TLS/control/work multiplexing, with no canonical or native effects."""
import asyncio
import base64
import hashlib
from dataclasses import replace

import pytest
from tests.unit.agents.test_gateway_node_transport import channel as channel
from tests.unit.agents.test_gateway_node_transport import tls as tls
from tests.unit.agents.test_gateway_node_transport import wait_until

from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.components.agents.gateway.node.transport import NodeTransportClient
from audiagentic.components.agents.gateway.node.work_protocol import ArtifactChunk, EffectAuthorized
from audiagentic.foundation.contracts.errors import AudiaGenticError


async def ignore(*args):
    pass


async def pair(channel, gateway_handler=ignore, node_handler=ignore):
    def install(handler):
        def configure(connection):
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
async def test_reply_timeout_releases_fixed_pending_slot(channel):
    node, _ = await pair(channel)
    try:
        with pytest.raises(TimeoutError):
            await node.request_work("effect-authorize", {"identity": command(node).to_mapping()},
                reply_types=(EffectAuthorized,), timeout=0.02)
        assert node._pending == {}
        await node.heartbeat()
    finally:
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
