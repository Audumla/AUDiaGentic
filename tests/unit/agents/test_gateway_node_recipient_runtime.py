"""Real channel correlation/local receipts; fake child I/O, no native/provider E2E."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.unit.agents.test_gateway_node_execution_owner import env as env
from tests.unit.agents.test_gateway_node_execution_owner import open_owner
from tests.unit.agents.test_gateway_node_worker_terminal import mint_proof
from websockets.exceptions import ConnectionClosedOK

from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.connection import NodeConnection
from audiagentic.components.agents.gateway.node.contracts import canonical_json
from audiagentic.components.agents.gateway.node.execution_owner import NodeExecutionOwner
from audiagentic.components.agents.gateway.node.local_preparation import NodeLocalPreparer
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.components.agents.gateway.node.recipient_runtime import NodeRecipientRuntime
from audiagentic.components.agents.gateway.node.work_protocol import (
    EffectAuthorize,
    PreparationRejected,
    PreparedReply,
)
from audiagentic.components.agents.gateway.queue import worker
from audiagentic.foundation.contracts.errors import AudiaGenticError


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.peer = None
        self.closed = False
        self.transport = SimpleNamespace(abort=self.abort)

    async def send(self, raw):
        if self.closed:
            raise ConnectionClosedOK(None, None)
        self.peer.incoming.put_nowait(raw)

    async def recv(self):
        value = await self.incoming.get()
        if value is None:
            raise ConnectionClosedOK(None, None)
        return value

    def abort(self):
        for socket in (self, self.peer):
            if not socket.closed:
                socket.closed = True
                socket.incoming.put_nowait(None)

    async def close(self, **kwargs):
        self.abort()


async def pair(runtime, *, generation=1, authorize=None):
    a, b = Socket(), Socket()
    a.peer, b.peer = b, a
    identity = NodeConnectionIdentity("node", "boot", "gateway", generation)
    node = NodeConnection(a, identity, role="node", grant_revision=1, capability="active")
    gateway = NodeConnection(b, identity, role="gateway", grant_revision=1, capability="active")
    exchanges = []

    async def handle(frame, message):
        if type(message) is not EffectAuthorize:
            raise AssertionError("unexpected gateway work")
        if authorize is not None:
            return await authorize(gateway, frame, message)
        reply = await gateway.send_work(
            "effect-authorized",
            {
                "identity": message.identity.to_mapping(),
                "authorization-request-id": frame.message_id,
                "authorization-id": "grant",
                "authorized": True,
            },
        )
        exchanges.append((frame, reply))

    gateway.enable_work(handle, max_artifact_bytes=1024 * 1024)
    await runtime.configure_work(node)
    node.start()
    gateway.start()
    return node, gateway, exchanges


def prepare_payload(case, **changes):
    return dict(
        {
            "kind": "prepare",
            "binding": case.preparation.attestation.binding.to_mapping(),
            "semantic": case.preparation.attestation.semantic.to_mapping(),
            "agent-id": "agent",
            "worker-id": "worker",
            "attempt-epoch": 1,
            "raw-prompt": case.payload["raw-prompt"],
            "source-workspace": case.source_workspace.to_mapping(),
            "caller-root": case.caller_root,
            "source": None,
            "metadata": {},
            "timeout-seconds": 1,
        },
        **changes,
    )


async def prepare(gateway, case, **changes):
    return await gateway.request_work(
        "reconcile",
        prepare_payload(case, **changes),
        reply_types=(PreparedReply, PreparationRejected),
        timeout=3,
    )


async def command(gateway, case, *, payload=None, identity=None):
    return await gateway.send_work(
        "command",
        {"identity": (identity or case.identity).to_mapping(), "payload": payload or case.payload},
    )


def setup(env, monkeypatch):
    owner = open_owner(env)
    calls = []

    def local_prepare(self, **kwargs):
        calls.append(kwargs)
        return env.case.preparation

    monkeypatch.setattr(NodeLocalPreparer, "prepare", local_prepare)
    runtime = NodeRecipientRuntime(env.config, owner, authorization_timeout_seconds=1)
    return owner, runtime, calls


def worker_io(env, monkeypatch, *, block=False, fail=False):
    mint_proof(monkeypatch, env.case)
    entered = asyncio.Event()
    release = threading.Event()
    calls = []
    loop = asyncio.get_running_loop()
    original = worker._wait_for_provider_terminal

    def wait(*args, **kwargs):
        calls.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        if block:
            assert release.wait(5), "test did not release fake child"
        if fail:
            raise RuntimeError("PRIVATE prompt/root failure text")
        return original(*args, **kwargs)

    monkeypatch.setattr(worker, "_wait_for_provider_terminal", wait)
    return entered, release, calls


async def close(node, gateway):
    await node.close()
    await gateway.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["root", "digest", "node", "readonly"])
async def test_real_source_validation_precedes_preparer(env, monkeypatch, tmp_path, bad):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    change = {}
    if bad == "root":
        other = tmp_path / "other"
        other.mkdir()
        change["caller-root"] = str(other)
    else:
        source = env.case.source_workspace.to_mapping()
        if bad == "digest":
            source["binding-sha256"] = "f" * 64
        elif bad == "node":
            source["source-node-id"] = "other"
        else:
            source["access-mode"] = "read-only"
        change["source-workspace"] = source
    try:
        # Some malformed identities are already rejected by the real channel parser.
        try:
            _, _, reply = await prepare(gateway, env.case, **change)
            assert type(reply) is PreparationRejected
        except AudiaGenticError:
            pass
        assert not calls
        assert not owner.receipts_after()
        assert runtime.failure is None or runtime.failure.reason_code == "preparation-rejected"
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_exact_authorization_frames_and_source_reach_sole_producer(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, worker_calls = worker_io(env, monkeypatch)
    captured, requested = [], []
    original_run, original_request = NodeExecutionOwner.run_one, NodeConnection.request_work

    def run(self, *args, **kwargs):
        captured.append(kwargs)
        return original_run(self, *args, **kwargs)

    async def request(self, *args, **kwargs):
        value = await original_request(self, *args, **kwargs)
        if args[0] == "effect-authorize":
            requested.append(value)
        return value

    monkeypatch.setattr(NodeExecutionOwner, "run_one", run)
    monkeypatch.setattr(NodeConnection, "request_work", request)
    node, gateway, exchanges = await pair(runtime)
    try:
        _, _, reply = await prepare(gateway, env.case)
        assert type(reply) is PreparedReply
        assert len(calls) == 1 and "caller_root" not in calls[0]
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 3)
        receipt = await runtime.wait_producer()
        assert receipt.state == "terminal"
        assert len(worker_calls) == 1 and worker_calls[0] != threading.get_ident()
        assert captured[0]["authorization_request"] is requested[0][0]
        assert captured[0]["authorization_reply"] is requested[0][1]
        assert captured[0]["authorization_request"] == exchanges[0][0]
        assert captured[0]["source_workspace"] == env.case.source_workspace
        assert captured[0]["caller_root"] == env.case.caller_root
        assert [r.state for r in owner.receipts_after()] == [
            "prepared",
            "effect-intent",
            "terminal",
        ]
        assert runtime.failure is None
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_changed_raw_semantic_command_rejected_before_authorization(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, exchanges = await pair(runtime)
    try:
        await prepare(gateway, env.case)
        payload = dict(env.case.payload) | {"raw-prompt": "another request"}
        import hashlib

        identity = replace(
            env.case.identity, payload_sha256=hashlib.sha256(canonical_json(payload)).hexdigest()
        )
        await command(gateway, env.case, payload=payload, identity=identity)
        await asyncio.wait_for(node.wait_closed(), 3)
        assert not exchanges and not owner.receipts_after()
        assert runtime.failure.reason_code == "command-correlation"
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_root_drift_after_preparation_does_not_commit_intent(env, monkeypatch, tmp_path):
    owner, runtime, calls = setup(env, monkeypatch)

    async def authorize(gateway, frame, message):
        other = tmp_path / "changed-root"
        other.mkdir()
        env.config.workspaces["workspace"] = replace(env.config.workspaces["workspace"], root=other)
        await gateway.send_work(
            "effect-authorized",
            {
                "identity": message.identity.to_mapping(),
                "authorization-request-id": frame.message_id,
                "authorization-id": "grant",
                "authorized": True,
            },
        )

    node, gateway, _ = await pair(runtime, authorize=authorize)
    observed = asyncio.Event()
    original = NodeExecutionOwner.run_one

    def run(self, *args, **kwargs):
        try:
            return original(self, *args, **kwargs)
        finally:
            loop.call_soon_threadsafe(observed.set)

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(NodeExecutionOwner, "run_one", run)
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("root override executed"),
    )
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(observed.wait(), 3)
        assert await runtime.wait_producer() is None
        assert not owner.receipts_after()
        assert runtime.failure.reason_code == "producer-failed"
        assert str(tmp_path) not in repr(runtime.failure)
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_disconnect_cancels_dispatcher_but_retains_blocked_producer(env, monkeypatch):
    owner, runtime, preparer_calls = setup(env, monkeypatch)
    entered, release, worker_calls = worker_io(env, monkeypatch, block=True)
    node, gateway, _ = await pair(runtime)
    newer = None
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 3)
        await close(node, gateway)
        assert runtime.current_connection is None
        assert runtime.producer_pending and owner.snapshot().producer_running
        waiter = asyncio.create_task(runtime.wait_producer())
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert runtime.producer_pending
        newer, new_gateway, _ = await pair(runtime, generation=2)
        await node._on_close()  # Delayed old cleanup cannot erase G2.
        assert runtime.current_connection is newer
        work = prepare_payload(env.case)
        work["binding"] = dict(work["binding"]) | {"connection-generation": 2}
        _, _, rejected = await new_gateway.request_work(
            "reconcile", work, reply_types=(PreparedReply, PreparationRejected), timeout=3
        )
        assert type(rejected) is PreparationRejected
        assert len(preparer_calls) == 1
        release.set()
        receipt = await asyncio.wait_for(runtime.wait_producer(), 3)
        assert receipt.state == "terminal" and len(worker_calls) == 1
        assert owner.snapshot().control.connection_generation == 2
        assert not owner.snapshot().handoff_pending
        assert owner.receipts_after()[-1].state == "terminal"
        assert (
            NodeReceiptStore(
                root=env.config.state_root,
                node_id="node",
                node_epoch="boot",
                gateway_owner_epoch="gateway",
            )
            .worker_terminal_output(env.case.identity)
            .text.startswith("Verified answer")
        )
    finally:
        release.set()
        if runtime.producer_pending:
            await asyncio.wait_for(runtime.wait_producer(), 3)
        await close(node, gateway)
        if newer is not None:
            await close(newer, new_gateway)


@pytest.mark.asyncio
async def test_worker_failure_keeps_intent_and_redacted_status(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, worker_calls = worker_io(env, monkeypatch, fail=True)
    node, gateway, _ = await pair(runtime)
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 3)
        assert await runtime.wait_producer() is None
        assert owner.snapshot().capacity_blocked
        assert owner.receipts_after()[-1].state == "effect-intent"
        assert "PRIVATE" not in repr(runtime.failure)
        assert runtime.failure.reason_code == "producer-failed"
        _, _, rejected = await prepare(gateway, env.case)
        assert type(rejected) is PreparationRejected and len(worker_calls) == 1
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_each_preparation_reply_uses_current_error_not_retained_first_cause(env, monkeypatch):
    from audiagentic.components.agents.gateway.node.contracts import conflict, invalid

    owner, runtime, calls = setup(env, monkeypatch)
    failures = iter([invalid(1, "PRIVATE first"), conflict(1, "PRIVATE second")])

    def failing(self, **kwargs):
        raise next(failures)

    monkeypatch.setattr(NodeLocalPreparer, "prepare", failing)
    node, gateway, _ = await pair(runtime)
    try:
        _, _, first = await prepare(gateway, env.case)
        _, _, second = await prepare(gateway, env.case)
        assert first.code == "VAL-AGND-001"
        assert second.code == "CON-AGND-001"
        assert runtime.failure.code == "VAL-AGND-001"
        assert "PRIVATE" not in repr(runtime.failure)
        assert not owner.receipts_after() and not runtime.producer_pending
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_all_runtime_owner_and_workspace_io_is_off_event_loop(env, monkeypatch):
    from audiagentic.components.agents.gateway.node import recipient_runtime

    owner, runtime, calls = setup(env, monkeypatch)
    loop_thread = threading.get_ident()
    checked = set()
    for name in ("observe_connection", "handoff_if_quiescent", "snapshot", "connection_lost"):
        original = getattr(NodeExecutionOwner, name)

        def checked_call(self, *args, _original=original, _name=name, **kwargs):
            assert threading.get_ident() != loop_thread, _name
            checked.add(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(NodeExecutionOwner, name, checked_call)
    original_validate = recipient_runtime.validate_recipient_workspace

    def validate(*args, **kwargs):
        assert threading.get_ident() != loop_thread, "workspace validation"
        checked.add("workspace")
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(recipient_runtime, "validate_recipient_workspace", validate)
    entered, release, worker_calls = worker_io(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 3)
        assert (await runtime.wait_producer()).state == "terminal"
    finally:
        await close(node, gateway)
    assert checked == {
        "observe_connection",
        "handoff_if_quiescent",
        "snapshot",
        "connection_lost",
        "workspace",
    }


@pytest.mark.asyncio
async def test_control_receiver_progresses_while_real_source_validation_waits(env, monkeypatch):
    from tests.unit.agents.test_gateway_node_transport import wait_until

    from audiagentic.components.agents.gateway.node import recipient_runtime

    owner, runtime, calls = setup(env, monkeypatch)
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original = recipient_runtime.validate_recipient_workspace

    def blocked(*args, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(recipient_runtime, "validate_recipient_workspace", blocked)
    node, gateway, _ = await pair(runtime)
    request = asyncio.create_task(prepare(gateway, env.case))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert not calls
        before = node._received_sequence
        await gateway.heartbeat()
        await wait_until(lambda: node._received_sequence == before + 1)
        assert not request.done()
        release.set()
        assert type((await request)[2]) is PreparedReply
        assert len(calls) == 1 and not owner.receipts_after()
    finally:
        release.set()
        await asyncio.gather(request, return_exceptions=True)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_partial_async_configuration_failure_notifies_loss_without_start(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)

    def fail(self):
        raise RuntimeError("PRIVATE service failure")

    monkeypatch.setattr(NodeExecutionOwner, "handoff_if_quiescent", fail)
    a, b = Socket(), Socket()
    a.peer, b.peer = b, a
    node = NodeConnection(
        a,
        NodeConnectionIdentity("node", "boot", "gateway", 1),
        role="node",
        grant_revision=1,
        capability="active",
    )
    with pytest.raises(AudiaGenticError):
        await runtime.configure_work(node)
    assert runtime.current_connection is None
    assert owner.snapshot().control is None
    assert not runtime.producer_pending and "PRIVATE" not in repr(runtime.failure)
    with pytest.raises(AudiaGenticError):
        node.start()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["denied", "request", "identity"])
async def test_nonmatching_or_denied_authorization_never_reaches_producer(env, monkeypatch, bad):
    owner, runtime, calls = setup(env, monkeypatch)

    async def authorize(gateway, frame, message):
        identity = (
            message.identity
            if bad != "identity"
            else replace(message.identity, request_id="foreign")
        )
        payload = {
            "identity": identity.to_mapping(),
            "authorization-request-id": "foreign" if bad == "request" else frame.message_id,
        }
        if bad == "denied":
            await gateway.send_work("effect-denied", payload | {"code": "CON-AGND-001"})
        else:
            await gateway.send_work(
                "effect-authorized", payload | {"authorization-id": "grant", "authorized": True}
            )

    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("uncorrelated authorization executed"),
    )
    node, gateway, _ = await pair(runtime, authorize=authorize)
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(node.wait_closed(), 3)
        assert not runtime.producer_pending and not owner.receipts_after()
        assert runtime.failure is not None
    finally:
        await close(node, gateway)
