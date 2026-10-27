"""Standalone recipient host qualification using fake interfaces, not native proof."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.node import host as recipient_host
from audiagentic.foundation.contracts.errors import AudiaGenticError

# They prove host ownership and shutdown ordering, never native execution.


class _HostConnection:
    def __init__(self, *, close_gate=None):
        self.closed = asyncio.Event()
        self.events = asyncio.Queue()
        self.failure_summary = None
        self.close_gate = close_gate
        self.cleanup_done = False

    async def wait_closed(self):
        await self.closed.wait()

    async def close(self):
        self.closed.set()
        if self.close_gate is not None:
            await self.close_gate.wait()
        self.cleanup_done = True


class _HostRuntime:
    def __init__(self):
        self.failure = None
        self.producer = asyncio.Event()
        self.waiting = asyncio.Event()
        self.producer.set()

    async def wait_producer(self):
        self.waiting.set()
        await self.producer.wait()


class _HostSender:
    def __init__(self):
        self.running = 0
        self.maximum = 0
        self.calls = 0
        self.started = asyncio.Queue()

    async def run(self, connection):
        self.running += 1
        self.maximum = max(self.maximum, self.running)
        self.calls += 1
        self.started.put_nowait(connection)
        try:
            await connection.closed.wait()
        finally:
            self.running -= 1


class _HostClient:
    def __init__(self, connections):
        self.connections = iter(connections)
        self.calls = 0
        self.previous = None

    async def connect(self):
        assert self.previous is None or self.previous.cleanup_done
        self.calls += 1
        value = next(self.connections)
        if isinstance(value, Exception):
            raise value
        self.previous = value
        return value


def _recipient_scaffold(tmp_path, monkeypatch, connections, *, runtime=None, policy=None):
    retired, observations = [], []
    store = SimpleNamespace(
        key=SimpleNamespace(service_id="node"),
        timeline_path=tmp_path / "timeline",
        heartbeat=lambda facts, **kwargs: observations.append(dict(facts)),
    )
    owner = SimpleNamespace(retire=lambda **kwargs: retired.append(kwargs))
    monkeypatch.setattr(recipient_host, "record_timeline_event", lambda *args, **kwargs: None)
    runtime = runtime or _HostRuntime()
    sender, client = _HostSender(), _HostClient(connections)
    host = recipient_host.NodeRecipientHost(
        store,
        owner,
        "owner",
        "boot",
        runtime,
        client,
        sender,
        policy or recipient_host.NodeReconnectPolicy(3, 0.001, 60),
    )
    return host, retired, observations


@pytest.mark.asyncio
async def test_recipient_stop_is_event_only_and_claim_waits_for_producer(tmp_path, monkeypatch):
    connection = _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [connection])
    host.runtime.producer.clear()
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.sender.started.get(), 2)
    host.request_stop()
    assert not retired
    await asyncio.wait_for(host.runtime.waiting.wait(), 2)
    assert connection.cleanup_done and host.sender.running == 0
    assert not run.done() and not retired
    host.runtime.producer.set()
    await asyncio.wait_for(run, 2)
    assert retired == [{"expected_epoch": "owner"}]


@pytest.mark.asyncio
async def test_recipient_cancel_and_disconnect_preserve_same_producer_and_one_sender(
    tmp_path, monkeypatch
):
    first, second = _HostConnection(), _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [first, second])
    host.runtime.producer.clear()
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.sender.started.get(), 2)
    first.closed.set()
    assert await asyncio.wait_for(host.sender.started.get(), 2) is second
    assert host.sender.maximum == 1 and not retired
    run.cancel()
    await asyncio.wait_for(host.runtime.waiting.wait(), 2)
    run.cancel()  # A second cancellation cannot detach the producer barrier.
    await asyncio.sleep(0)
    assert not run.done() and not retired
    host.runtime.producer.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run, 2)
    assert host.sender.running == 0 and second.cleanup_done
    assert len(retired) == 1 and host.node_epoch == "boot"


@pytest.mark.asyncio
async def test_recipient_reconnect_awaits_old_cleanup(tmp_path, monkeypatch):
    gate = asyncio.Event()
    first, second = _HostConnection(close_gate=gate), _HostConnection()
    host, _, _ = _recipient_scaffold(tmp_path, monkeypatch, [first, second])
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.sender.started.get(), 2)
    first.closed.set()
    await asyncio.sleep(0)
    assert host.client.calls == 1
    gate.set()
    assert await asyncio.wait_for(host.sender.started.get(), 2) is second
    host.request_stop()
    await asyncio.wait_for(run, 2)
    assert host.sender.maximum == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,attempts",
    [
        (ConnectionRefusedError("/private/token=secret"), 3),
        (FileNotFoundError("/private/token=secret"), 1),
        (ValueError("/private/token=secret"), 1),
    ],
)
async def test_recipient_finite_failure_budget_and_safe_diagnostics(
    tmp_path, monkeypatch, error, attempts
):
    host, retired, observations = _recipient_scaffold(tmp_path, monkeypatch, [error] * 4)

    def broken_logger(*args, **kwargs):
        raise RuntimeError("/private/token=secret")

    monkeypatch.setattr(recipient_host, "record_timeline_event", broken_logger)
    await asyncio.wait_for(host.run(), 2)
    assert host.client.calls == attempts and len(retired) == 1
    assert "secret" not in repr(observations) + repr(host.failure)
    assert host.failure == {
        "code": "IO-AGND-001",
        "stage": "observe",
        "reason": "node-reconciliation-required",
    }


@pytest.mark.asyncio
async def test_recipient_successful_but_flapping_connect_does_not_reset_budget(
    tmp_path, monkeypatch
):
    connections = [_HostConnection() for _ in range(4)]
    for connection in connections:
        connection.closed.set()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, connections)
    await asyncio.wait_for(host.run(), 2)
    assert host.client.calls == 3 and len(retired) == 1
    assert host.sender.maximum <= 1


@pytest.mark.asyncio
async def test_recipient_control_and_cursor_failures_do_not_reconnect(tmp_path, monkeypatch):
    connection = _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [connection])

    async def fail_sender(channel):
        raise AudiaGenticError(
            "CON-AGND-001",
            "agents-node",
            "private cursor",
            details={"reason_code": "receipt-cursor-contradiction"},
        )

    host.sender.run = fail_sender
    await asyncio.wait_for(host.run(), 2)
    assert host.client.calls == 1 and len(retired) == 1
    assert connection.cleanup_done


@pytest.mark.asyncio
async def test_recipient_stop_interrupts_reconnect_delay(tmp_path, monkeypatch):
    host, retired, _ = _recipient_scaffold(
        tmp_path,
        monkeypatch,
        [ConnectionRefusedError("offline")],
        policy=recipient_host.NodeReconnectPolicy(3, 600, 60),
    )
    run = asyncio.create_task(host.run())
    # Wait on the existing diagnostic publication rather than a timing sleep.
    while host.failure is None:
        await asyncio.sleep(0)
    host.request_stop()
    await asyncio.wait_for(run, 2)
    assert host.client.calls == 1 and len(retired) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_failures": True},
        {"max_failures": 0},
        {"delay_seconds": float("inf")},
        {"stable_seconds": 0},
    ],
)
def test_recipient_reconnect_policy_rejects_unbounded_values(kwargs):
    with pytest.raises(AudiaGenticError) as caught:
        recipient_host.NodeReconnectPolicy(**kwargs)
    assert caught.value.code == "VAL-AGND-001"


def test_recipient_create_composes_one_process_owner_without_gateway_graph(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig

    calls = []
    config = SharedGatewayNodeConfig(
        "node", "server", "wss://localhost:1234", tmp_path / "token", tmp_path, {}
    )
    store = SimpleNamespace()
    execution = object()
    runtime = SimpleNamespace(configure_work=object())
    sender = object()

    def store_factory(key, *, root):
        assert key.service_kind == "execution-node" and key.service_id == "node"
        assert root == config.state_root
        calls.append("store")
        return store

    def claim(**kwargs):
        assert kwargs["evidence_factory"]("epoch") == "current-process-proof"
        calls.append("claim")
        return SimpleNamespace(owner_epoch="epoch")

    owner = SimpleNamespace(claim=claim)
    monkeypatch.setattr(recipient_host, "ManagedServiceStore", store_factory)
    monkeypatch.setattr(recipient_host, "ManagedServiceOwner", lambda service: owner)
    monkeypatch.setattr(
        recipient_host,
        "current_process_evidence",
        lambda **kwargs: "current-process-proof" if kwargs == {"owner_epoch": "epoch"} else None,
    )

    def open_owner(selected, **kwargs):
        assert selected is config and kwargs["service_store"] is store
        assert kwargs["service_owner_epoch"] == "epoch"
        calls.append(("execution", kwargs["node_epoch"]))
        return execution

    monkeypatch.setattr(recipient_host, "NodeExecutionOwner", SimpleNamespace(open=open_owner))

    def collector(root):
        return {"explicit": {}}

    def prepare(selected, **kwargs):
        assert kwargs == {"component_context_reader": collector}
        calls.append("preparer")
        return "preparer"

    monkeypatch.setattr(recipient_host, "NodeLocalPreparer", prepare)

    def make_runtime(selected, selected_owner, **kwargs):
        assert (
            selected is config
            and selected_owner is execution
            and kwargs == {"preparer": "preparer"}
        )
        calls.append("runtime")
        return runtime

    monkeypatch.setattr(recipient_host, "NodeRecipientRuntime", make_runtime)

    def client(selected, **kwargs):
        assert selected is config and kwargs["configure_work"] is runtime.configure_work
        calls.append(("client", kwargs["node_epoch"]))
        return "client"

    monkeypatch.setattr(recipient_host, "NodeTransportClient", client)

    def make_sender(selected):
        assert selected is runtime
        calls.append("sender")
        return sender

    monkeypatch.setattr(recipient_host, "NodeReceiptSender", make_sender)
    host = recipient_host.NodeRecipientHost.create(config, component_context_reader=collector)
    assert calls == [
        "store",
        "claim",
        ("execution", host.node_epoch),
        "preparer",
        "runtime",
        ("client", host.node_epoch),
        "sender",
    ]
    assert host.runtime is runtime and host.sender is sender


@pytest.mark.asyncio
async def test_recipient_create_rejects_loop_before_claim():
    with pytest.raises(AudiaGenticError, match="off the event loop"):
        recipient_host.NodeRecipientHost.create(None, component_context_reader=lambda root: {})


@pytest.mark.asyncio
async def test_recipient_connect_cancel_race_closes_undelivered_channel(tmp_path, monkeypatch):
    connection = _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [])
    entered = asyncio.Event()

    async def connect():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # Simulate a connect whose welcome completed as cancellation arrived.
            return connection

    host.client.connect = connect
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(entered.wait(), 2)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run, 2)
    assert connection.cleanup_done and len(retired) == 1


@pytest.mark.asyncio
async def test_recipient_late_cancel_waits_and_propagates_after_barrier(tmp_path, monkeypatch):
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [])
    host.runtime.producer.clear()
    host.request_stop()
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.runtime.waiting.wait(), 2)
    run.cancel()
    await asyncio.sleep(0)
    assert not run.done() and not retired
    host.runtime.producer.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run, 2)
    assert len(retired) == 1


@pytest.mark.asyncio
async def test_recipient_stable_duration_resets_consecutive_budget(tmp_path, monkeypatch):
    connections = [_HostConnection() for _ in range(5)]
    for connection in connections:
        connection.closed.set()
    host, _, _ = _recipient_scaffold(tmp_path, monkeypatch, connections)
    # One short failure, one stable connection, then three short failures.
    # Set only the owner module's clock, leaving event-loop time untouched.
    ticks = iter((0, 0, 0, 61, 0, 0, 0, 0))
    monkeypatch.setattr(recipient_host, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    await asyncio.wait_for(host.run(), 2)
    assert host.client.calls == 4


@pytest.mark.asyncio
async def test_drain_keeps_sender_and_historical_channel_open(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.node.connection import ControlEvent

    consumed = asyncio.Event()

    class Controls(asyncio.Queue):
        calls = 0

        async def get(self):
            self.calls += 1
            if self.calls == 3:
                consumed.set()
            return await super().get()

    connection = _HostConnection()
    connection.events = Controls()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [connection])
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.sender.started.get(), 2)
    connection.capability = "drain"  # Applied by NodeConnection before event delivery.
    connection.events.put_nowait(ControlEvent("revoke", grant_revision=2, capability="drain"))
    connection.events.put_nowait(ControlEvent("revoke", grant_revision=3, capability="drain"))
    await asyncio.wait_for(consumed.wait(), 2)
    assert not connection.cleanup_done and not retired and not run.done()
    assert host.sender.running == 1 and host.sender.calls == 1
    assert connection.capability == "drain"
    # Historical handlers remain on this same connection; the host neither
    # replaces nor disables them or emits fresh readiness on a drain event.
    host.request_stop()
    await asyncio.wait_for(run, 2)
    assert connection.cleanup_done and len(retired) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "receipt-cursor-mismatch",
        "receipt-log-changed",
        "receipt-resume-mismatch",
        "receipt-cursor-contradiction",
        "receipt-ack-timeout",
        "receipt-resume-timeout",
        "receipt-sender-failed",
    ],
)
async def test_sender_primary_reason_survives_cleanup_failure(tmp_path, monkeypatch, reason):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    connection = _HostConnection()
    host, retired, observations = _recipient_scaffold(tmp_path, monkeypatch, [connection])

    async def sender(channel):
        raise conflict(1, "/private/token=secret", reason_code=reason)

    async def broken_close():
        raise OSError("/secondary/private/token=secret")

    host.sender.run = sender
    connection.close = broken_close
    await asyncio.wait_for(host.run(), 2)
    assert host.failure == {"code": "CON-AGND-001", "stage": "observe", "reason": reason}
    assert "secret" not in repr(host.failure) + repr(observations)
    assert host.client.calls == 1 and len(retired) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"component_context_reader": None},
        {"component_context_reader": lambda root: {}, "reconnect": False},
    ],
)
def test_create_configuration_errors_use_registered_contract(tmp_path, kwargs):
    from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig

    config = SharedGatewayNodeConfig(
        "node", "server", "wss://localhost/node", tmp_path / "token", tmp_path, {}
    )
    with pytest.raises(AudiaGenticError) as caught:
        recipient_host.NodeRecipientHost.create(config, **kwargs)
    assert caught.value.code == "VAL-AGND-001"


def test_actual_claim_retirement_keeps_process_owner_fence(tmp_path):
    from audiagentic.components.agents.gateway.node.connection import NODE_PATH
    from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig

    config = SharedGatewayNodeConfig(
        "node",
        "server",
        "wss://localhost" + NODE_PATH,
        tmp_path / "unused-token",
        tmp_path / "state",
        {},
    )
    host = recipient_host.NodeRecipientHost.create(config, component_context_reader=lambda root: {})
    before = host.service_store.read()
    assert before.state == "running" and before.process is not None
    assert before.process.owner_epoch == host.owner_epoch
    assert host.client.node_epoch == host.node_epoch
    assert host.runtime.execution_owner.snapshot().producer_running is False
    try:
        # No transport or native execution: stop before run begins.
        host.request_stop()
        asyncio.run(host.run())
        assert host.service_store.read().state == "stopped"
        # A strong reference to the old owner remains. Managed retirement does
        # not authorize a new boot within this process or clear its root fence.
        with pytest.raises(AudiaGenticError) as caught:
            recipient_host.NodeRecipientHost.create(
                config, component_context_reader=lambda root: {}
            )
        assert caught.value.code == "CON-AGND-001"
        assert "already holds this state root" in str(caught.value)
        assert host.service_store.read().state == "stopped"
    finally:
        assert not host.runtime.producer_pending


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["error", "unsupported"])
async def test_actual_error_or_unsupported_control_stops_without_reconnect(
    tmp_path, monkeypatch, kind
):
    connection = _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [connection])
    connection.events.put_nowait(SimpleNamespace(type=kind, code="VAL-AGND-001"))
    await asyncio.wait_for(host.run(), 2)
    assert connection.cleanup_done and host.client.calls == 1
    assert len(retired) == 1 and host.sender.running == 0
    assert host.failure["code"] == ("VAL-AGND-001" if kind == "error" else "CON-AGND-001")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["receipt-ack-timeout", "receipt-resume-timeout"])
@pytest.mark.parametrize("ordering", ["sender-first", "closed-first"])
async def test_timeout_orderings_reconnect_after_cleanup_and_preserve_producer(
    tmp_path, monkeypatch, reason, ordering
):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    first, second = _HostConnection(), _HostConnection()
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [first, second])
    host.runtime.producer.clear()
    selected, release, resumed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_wait = asyncio.wait
    checked = False

    async def observe_selection(tasks, **kwargs):
        nonlocal checked
        done, pending = await original_wait(tasks, **kwargs)
        if len(tasks) == 4 and not checked:
            checked = True
            if ordering == "closed-first":
                assert tasks[1] in done and tasks[0] not in done
            else:
                assert tasks[0] in done and tasks[1] not in done
            selected.set()
        return done, pending

    monkeypatch.setattr(recipient_host.asyncio, "wait", observe_selection)

    async def sender(connection):
        if connection is first:
            if ordering == "closed-first":
                first.closed.set()
                await release.wait()
            raise conflict(1, "private", reason_code=reason)
        resumed.set()
        await connection.closed.wait()

    host.sender.run = sender
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(selected.wait(), 2)
    release.set()
    await asyncio.wait_for(resumed.wait(), 2)
    assert first.cleanup_done and host.client.calls == 2 and not retired
    assert host.failure["reason"] == reason
    host.request_stop()
    await asyncio.wait_for(host.runtime.waiting.wait(), 2)
    assert second.cleanup_done and not retired and not run.done()
    host.runtime.producer.set()
    await asyncio.wait_for(run, 2)
    assert len(retired) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["receipt-ack-timeout", "receipt-resume-timeout"])
async def test_sender_timeout_exhaustion_keeps_claim_until_producer_barrier(
    tmp_path, monkeypatch, reason
):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    connections = [_HostConnection() for _ in range(4)]
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, connections)
    host.runtime.producer.clear()

    async def sender(connection):
        raise conflict(1, "private", reason_code=reason)

    host.sender.run = sender
    run = asyncio.create_task(host.run())
    await asyncio.wait_for(host.runtime.waiting.wait(), 2)
    assert host.client.calls == 3
    assert all(connection.cleanup_done for connection in connections[:3])
    assert not retired and not run.done()
    host.runtime.producer.set()
    await asyncio.wait_for(run, 2)
    assert len(retired) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,reason",
    [
        ("IO-AGND-001", "receipt-ack-timeout"),
        ("CON-AGND-001", "receipt-sender-failed"),
        ("CON-AGND-001", "receipt-cursor-contradiction"),
        ("VAL-AGND-001", "receipt-resume-timeout"),
    ],
)
async def test_retry_requires_explicit_typed_con_timeout(tmp_path, monkeypatch, code, reason):
    host, retired, _ = _recipient_scaffold(tmp_path, monkeypatch, [_HostConnection()])

    async def sender(connection):
        raise AudiaGenticError(code, "agents-node", "private", details={"reason_code": reason})

    host.sender.run = sender
    await asyncio.wait_for(host.run(), 2)
    assert host.client.calls == 1 and len(retired) == 1
