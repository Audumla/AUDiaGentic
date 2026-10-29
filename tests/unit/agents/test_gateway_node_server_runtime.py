"""Standalone composition over real queue, canonical stores and loopback peers."""
from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml
from websockets.asyncio.client import connect

from audiagentic.components.agents.gateway import api, store
from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.node.connection import NODE_PATH, SUBPROTOCOL
from audiagentic.components.agents.gateway.node.contracts import Frame
from audiagentic.components.agents.gateway.node.server_runtime import (
    NodeQueuePorts,
    NodeServerRuntime,
)
from audiagentic.components.agents.gateway.queue import work_index
from audiagentic.components.agents.gateway.service.host import GatewayServiceHost
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.bootstrap import gateway_service_composition as composition

from .test_gateway_node_admission_owner import admission as admission
from .test_gateway_node_admission_owner import submit
from .test_gateway_node_host import _config, install_graph
from .test_gateway_node_transport import hello


@pytest.fixture
def runtime(admission, monkeypatch):
    admission.raw["node-listen"]["port"] = 0
    admission.config_path.write_text(yaml.safe_dump(admission.raw))
    config = load_shared_server_config(admission.config_path)
    admission.authority = NodeGrantAuthority(config, service_root=admission.service.root)
    admission.owner._authority = admission.authority
    ports = NodeQueuePorts()
    previous = api.get_queue_manager()
    queue = composition._build_gateway_queue_manager(node_config=config, node_ports=ports)
    monkeypatch.setattr(api, "_QUEUE_MANAGER", queue)
    runtime = NodeServerRuntime(config, admission.service, admission.authority, queue, "owner", ports,
        shutdown_timeout=3)
    try:
        yield runtime
    finally:
        runtime.close()
        api.set_queue_manager(previous)


async def until(predicate):
    async def poll():
        while not await asyncio.to_thread(predicate):
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), 4)


@asynccontextmanager
async def peer(runtime):
    async with connect(f"ws://127.0.0.1:{runtime.transport.port}{NODE_PATH}", proxy=None,
            subprotocols=[SUBPROTOCOL], additional_headers={"Authorization": "Bearer credential-node"}) as socket:
        await socket.send(hello(node_epoch="peer-boot").to_bytes())
        welcome = Frame.from_bytes(await socket.recv())
        yield socket, welcome


def wire(welcome, sequence, kind, payload):
    return Frame(1, kind, f"message-{sequence}", welcome.node_id, welcome.node_epoch,
        welcome.gateway_owner_epoch, sequence,
        {**payload, "connection-generation": welcome.payload["connection-generation"]})


@pytest.mark.asyncio
async def test_actual_zero_cursor_ready_wakes_same_queue_and_fresh_prepare(runtime, admission):
    assert runtime.queue is api.get_queue_manager() is runtime.admission._queue
    assert not runtime.ports.ready(admission.context)  # Unbound ports do not consult authority.
    record = await asyncio.to_thread(runtime.admission.submit, admission.root, context=admission.context,
        arguments={"agent_id": "reviewer", "prompt_body": "inspect"}, owner_epoch="owner")
    assert record["state"] == "queued"
    await asyncio.to_thread(runtime.start)
    async with peer(runtime) as (socket, welcome):
        log = str(uuid4())
        await socket.send(wire(welcome, 2, "reconcile", {"kind": "receipt-resume",
            "log-incarnation-id": log, "through-sequence": 0, "through-receipt-sha256": None}).to_bytes())
        resume = Frame.from_bytes(await asyncio.wait_for(socket.recv(), 2))
        assert resume.payload["after-sequence"] == 0
        await socket.send(wire(welcome, 3, "reconcile", {"kind": "receipt-ready",
            "log-incarnation-id": log, "through-sequence": 0, "through-receipt-sha256": None}).to_bytes())
        prepare = Frame.from_bytes(await asyncio.wait_for(socket.recv(), 4))
        assert prepare.payload["kind"] == "prepare"
        current = store.read_record(admission.root, record["request-id"])
        worker, attempt = current["worker-id"], current["attempt-epoch"]
        assert worker and attempt == 1 and current["node-dispatch"] is None
        await socket.send(wire(welcome, 4, "reconcile-result", {"kind": "prepare-rejected",
            "in-reply-to": prepare.message_id, "code": "VAL-AGND-001"}).to_bytes())
        await until(lambda: store.read_record(admission.root, record["request-id"]).get("recovery-required") is True)
        await socket.send(wire(welcome, 5, "reconcile", {"kind": "receipt-ready",
            "log-incarnation-id": log, "through-sequence": 0, "through-receipt-sha256": None}).to_bytes())
        second = Frame.from_bytes(await asyncio.wait_for(socket.recv(), 4))
        assert second.payload["kind"] == "prepare"
        assert second.payload["worker-id"] == worker and second.payload["attempt-epoch"] == attempt
        assert store.read_record(admission.root, record["request-id"])["node-dispatch"] is None


def test_ports_bind_once_and_clear_cannot_reenable(runtime):
    assert runtime.ports._snapshot() is None
    runtime.ports.bind(runtime)
    runtime.ports.clear()
    assert runtime.ports._snapshot() is None
    with pytest.raises(AudiaGenticError):
        runtime.ports.bind(runtime)


def test_graph_factory_keeps_configured_installed_manager(admission, monkeypatch):
    config = load_shared_server_config(admission.config_path)
    ports = NodeQueuePorts()
    monkeypatch.setattr(composition, "_build_shared_gateway_registry_factory", lambda: lambda: admission.registry)
    monkeypatch.setattr(composition, "_shutdown_gpt_auto_runtimes", lambda owner: None)
    monkeypatch.setattr(composition, "_shutdown_session_runtime", lambda owner: None)
    graph = composition.build_gateway_service_graph(node_config=config, node_ports=ports)
    try:
        manager = graph.root(composition.QUEUE_MANAGER)
        assert manager is api.get_queue_manager()
        assert manager._node_occupancy.project_roots == tuple(config.projects.values())
        assert manager._node_ready.__self__ is ports
    finally:
        graph.shutdown()


def test_current_owner_wake_uses_descriptor_policy_and_never_takes_over(runtime, admission, monkeypatch):
    record = submit(admission)
    record = store.claim_dispatch(admission.root, record["request-id"], owner_epoch="owner",
        expected_revision=record["revision"], service_root=admission.service.root)
    record = store.start_owned_attempt(admission.root, record["request-id"], owner_epoch="owner",
        worker_id="original-worker", expected_revision=record["revision"])
    record = store.defer_owned_recovery(admission.root, record["request-id"], owner_epoch="owner",
        worker_id="original-worker", attempt_epoch=record["attempt-epoch"], expected_revision=record["revision"],
        error=None, phase="node-runtime-unavailable", side_effect_state="not-started", retry_delay_seconds=None)
    enqueued = Mock(return_value=record)
    monkeypatch.setattr(runtime.queue, "enqueue_recovered_node", enqueued)
    monkeypatch.setattr(store, "takeover_nonterminal_owner", Mock(side_effect=AssertionError("no takeover")))
    runtime.wake("node")
    enqueued.assert_called_once()
    kwargs = enqueued.call_args.kwargs
    assert kwargs["policy"].generation == record["node-admission"]["policy"]["generation"]
    assert kwargs["placement"].to_record_mapping() == record["node-placement"]
    assert enqueued.call_args.args[1]["worker-id"] == "original-worker"
    runtime.wake("unconfigured")
    assert enqueued.call_count == 1


def test_revoke_refresh_runs_after_authority_unlock(runtime, monkeypatch):
    runtime.start()
    async def refreshed(node):
        assert await asyncio.to_thread(runtime.authority.serialize, lambda: True)
        return "drain"
    monkeypatch.setattr(runtime.transport, "refresh_capability", refreshed)
    assert runtime.revoke("node", expected_grant_revision=1) == 2
    assert runtime.revoke("node", expected_grant_revision=1) == 2


@pytest.mark.asyncio
async def test_close_waits_for_bridge_before_loop_stop_and_disables_ports(runtime, monkeypatch):
    await asyncio.to_thread(runtime.start)
    entered, release = threading.Event(), threading.Event()
    def runner(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        assert runtime.loop.is_running()
        return {}
    monkeypatch.setattr(runtime, "runner", runner)
    worker = asyncio.create_task(asyncio.to_thread(runtime.run, None, {}))
    assert await asyncio.to_thread(entered.wait, 2)
    closer = asyncio.create_task(asyncio.to_thread(runtime.close))
    await until(lambda: runtime.ports._snapshot() is None)
    assert runtime.queue._shutdown_event.is_set() and not closer.done()
    release.set()
    await worker
    await closer
    assert runtime.loop.is_closed() and not runtime._thread.is_alive()


def test_host_startup_orders_provider_checks_listener_readiness_and_http(tmp_path, monkeypatch):
    install_graph(monkeypatch)
    config = _config(tmp_path)
    host = GatewayServiceHost.create(shared_config=config, application=object())
    from audiagentic.components.agents.gateway.service import known_projects
    from audiagentic.components.providers import providers_api
    order = []
    monkeypatch.setattr(providers_api, "validate_gpt_auto_configuration", lambda: order.append("providers"))
    monkeypatch.setattr(known_projects, "scan_known_gpt_auto_projects", lambda *a, **kw: order.append("projects"))
    start = host._node_runtime.start
    def started():
        assert host.service_store.read().health_facts.get("ready") is False
        order.append("listener")
        start()
    monkeypatch.setattr(host._node_runtime, "start", started)
    for name in ("_start_ingress_poller", "_start_operations_poller"):
        monkeypatch.setattr(host, name, lambda: None)
    monkeypatch.setattr(host.lifecycle, "start", lambda: None)
    def served(**kwargs):
        assert host.service_store.read().health_facts["ready"] is True
        assert host.server.application._node_admission is host._node_runtime.admission
        order.append("http")
    monkeypatch.setattr(host.server, "serve_forever", served)
    try:
        host.serve_forever()
        assert order == ["providers", "projects", "listener", "http"]
    finally:
        host.close()


@pytest.mark.asyncio
async def test_unknown_work_does_not_reach_effect_or_receipt_owners(runtime, monkeypatch):
    captured = {}
    connection = SimpleNamespace(enable_work=lambda handler, **kw: captured.update(handler=handler))
    effect = Mock(side_effect=AssertionError("unexpected effect"))
    receipt = Mock(side_effect=AssertionError("unexpected receipt"))
    monkeypatch.setattr(runtime.runner, "handle_effect_authorize", effect)
    monkeypatch.setattr(runtime.receipts, "handle_work", receipt)
    await runtime._configure(connection)
    with pytest.raises(AudiaGenticError, match="unsupported work"):
        await captured["handler"](object(), object())
    effect.assert_not_called()
    receipt.assert_not_called()


def test_failed_revoke_refresh_retries_without_second_revision(runtime, monkeypatch):
    runtime.start()
    calls = []
    async def refresh(node):
        calls.append(node)
        if len(calls) == 1:
            raise OSError("refresh interrupted")
    monkeypatch.setattr(runtime.transport, "refresh_capability", refresh)
    with pytest.raises(OSError):
        runtime.revoke("node", expected_grant_revision=1)
    assert runtime.revoke("node", expected_grant_revision=1) == 2
    assert load_shared_server_config(runtime.config.config_path).nodes[0].revision == 2
    assert calls == ["node", "node"]


def test_listener_start_failure_keeps_first_cause_and_stops_thread(runtime, monkeypatch):
    async def fail(**_kwargs):
        raise OSError("first startup failure")
    closed = runtime.transport.close
    async def close_then_fail():
        await closed()
        raise RuntimeError("secondary close failure")
    monkeypatch.setattr(runtime.transport, "start", fail)
    monkeypatch.setattr(runtime.transport, "close", close_then_fail)
    with pytest.raises(OSError, match="first startup failure"):
        runtime.start()
    assert runtime.loop.is_closed() and not runtime._thread.is_alive()
    assert runtime.ports._snapshot() is None


def test_close_failure_after_listener_retirement_still_stops_loop(runtime, monkeypatch):
    runtime.start()
    close = runtime.transport.close
    async def close_then_fail():
        await close()
        raise OSError("close notification failure")
    monkeypatch.setattr(runtime.transport, "close", close_then_fail)
    with pytest.raises(OSError, match="close notification failure"):
        runtime.close()
    assert runtime.loop.is_closed() and not runtime._thread.is_alive()
    assert runtime.transport._server is None
    runtime.close()


def test_dirty_wake_retried_only_by_existing_operations_maintenance_despite_logger_fault(tmp_path, monkeypatch):
    import time

    from audiagentic.components.agents.gateway.service import host as host_module

    install_graph(monkeypatch)
    host = GatewayServiceHost.create(shared_config=_config(tmp_path), application=object())
    runtime = host._node_runtime
    woke = threading.Event()
    attempts = []
    def wake(node):
        attempts.append(node)
        if len(attempts) == 1:
            raise OSError("temporary work index failure")
        woke.set()
    monkeypatch.setattr(runtime, "wake", wake)
    # Activate the existing ports only; no node loop or additional timer needed.
    runtime.ports.bind(runtime)
    runtime.queue.notify_node_changed("node")
    assert attempts == ["node"] and not woke.is_set()
    retry = runtime.queue.retry_node_notifications
    calls = []
    def maintenance():
        calls.append(True)
        if len(calls) == 1:
            raise OSError("maintenance interrupted")
        retry()
    monkeypatch.setattr(runtime.queue, "retry_node_notifications", maintenance)
    monkeypatch.setattr(host_module.logger, "warning", Mock(side_effect=OSError("logger failure")))
    monkeypatch.setattr(host, "run_watchdog_pass", lambda: ())
    host._journal_maintenance_at = time.monotonic() + 3600
    try:
        host._start_operations_poller(interval_seconds=0.01)
        assert woke.wait(2)
        assert host._operations_thread.is_alive()
        assert len(calls) >= 2 and attempts == ["node", "node"]
    finally:
        host.close()


def test_host_seeds_running_nodes_before_queued_then_starts_listener(runtime, admission, monkeypatch):
    from audiagentic.components.agents.gateway.queue import recovery
    from audiagentic.components.agents.gateway.service import known_projects
    from audiagentic.components.providers import providers_api

    first = submit(admission)
    second = submit(admission, metadata={"idempotency_key": "second"})
    running = store.claim_dispatch(admission.root, first["request-id"], owner_epoch="owner",
        expected_revision=first["revision"], service_root=admission.service.root)
    running = store.start_owned_attempt(admission.root, first["request-id"], owner_epoch="owner",
        worker_id="original-worker", expected_revision=running["revision"])
    events = []
    monkeypatch.setattr(recovery, "recover_gateway_requests", lambda *a, **kw:
        SimpleNamespace(running=((admission.root, running["request-id"]),),
            queued=((admission.root, second["request-id"]),)))
    monkeypatch.setattr(runtime, "enqueue_recovered", lambda root, record: events.append(record["state"]))
    monkeypatch.setattr(runtime, "start", lambda: events.append("listener"))
    monkeypatch.setattr(providers_api, "validate_gpt_auto_configuration", lambda: events.append("providers"))
    monkeypatch.setattr(known_projects, "scan_known_gpt_auto_projects", lambda *a, **kw: None)
    server = SimpleNamespace(serve_forever=lambda **kw: events.append("http"))
    host = GatewayServiceHost(server, admission.service, Mock(), "owner", admission.config_path,
        application=object(), node_runtime=runtime)
    monkeypatch.setattr(host, "_start_ingress_poller", lambda: None)
    monkeypatch.setattr(host, "_start_operations_poller", lambda: None)
    host.serve_forever()
    assert events == ["running", "queued", "providers", "listener", "http"]


def test_current_owner_wake_filters_foreign_roots_before_reading(runtime, admission, monkeypatch, tmp_path):
    other = tmp_path / "foreign"
    other.mkdir()
    work_index.write_work_index_entry(admission.service.root, other, "req_foreign", phase="admitted")
    monkeypatch.setattr(store, "read_record", Mock(side_effect=AssertionError("foreign root read")))
    runtime.wake("node")


def test_replacement_service_owner_denies_old_ready_and_recovery_writes(runtime):
    from audiagentic.components.agents.gateway.node.placement import NodeAdmissionPlacement

    from .test_gateway_node_checkpoints import _restart

    _restart(runtime.service, "replacement")
    placement = NodeAdmissionPlacement("server", "node", "workspace", "caller", "project", 1)
    with pytest.raises(AudiaGenticError):
        runtime.ready(placement)
    with pytest.raises(AudiaGenticError):
        runtime.wake("node")


@pytest.mark.parametrize("kind", ["running-unbound", "authorized", "terminal-receipt"])
def test_host_watchdog_never_probes_or_terminalizes_node_work(runtime, admission, monkeypatch, kind):
    from audiagentic.components.agents.gateway.queue import dispatch, watchdog_registry

    from .test_gateway_node_recovery import make_record

    record = make_record(admission.root, admission.service, kind, cancel=True)
    registry = watchdog_registry.WatchdogRequestRegistry()
    registry.register(admission.root, record)
    monkeypatch.setattr(watchdog_registry, "_REGISTRY", registry)
    forbidden = Mock(side_effect=AssertionError("node reached local provider watchdog"))
    monkeypatch.setattr(dispatch, "diagnose_activity_lease", forbidden)
    monkeypatch.setattr(api, "complete_execution_from_provider", forbidden)
    monkeypatch.setattr(api, "recover_execution_request", forbidden)
    host = GatewayServiceHost(SimpleNamespace(), admission.service, Mock(), "owner", admission.config_path,
        application=object(), node_runtime=runtime)
    assert host.run_watchdog_pass() == ()
    forbidden.assert_not_called()
    assert store.read_record(admission.root, record["request-id"]) == record


def test_shutdown_timeout_keeps_loop_and_owner_fence_for_retry(runtime, monkeypatch):
    runtime.start()
    runtime.shutdown_timeout = 0.01
    with runtime._condition:
        runtime._workers = 1
    with pytest.raises(AudiaGenticError, match="workers have not retired"):
        runtime.close()
    assert runtime.loop.is_running() and not runtime._closed
    assert runtime.service.read().owner_epoch == "owner"
    assert runtime.ports._snapshot() is None
    with runtime._condition:
        runtime._workers = 0
    runtime.close()
    assert runtime.loop.is_closed()


def test_node_thread_start_failure_closes_unstarted_loop(runtime, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("thread creation failed")
    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(OSError, match="thread creation failed"):
        runtime.start()
    assert runtime.loop.is_closed() and runtime.ports._snapshot() is None


def test_host_constructor_failure_after_claim_retires_claim_without_masking_cause(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.node import server_runtime
    from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
    from audiagentic.foundation.system.managed_service import ManagedServiceStore

    install_graph(monkeypatch)
    config = _config(tmp_path)
    monkeypatch.setattr(server_runtime, "NodeServerRuntime", Mock(side_effect=OSError("composition failed")))
    with pytest.raises(OSError, match="composition failed"):
        GatewayServiceHost.create(shared_config=config, application=object())
    record = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=config.service_root).read()
    assert record.state == "stopped"


def test_host_listener_start_failure_never_readies_and_retires_managed_claim(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.service import known_projects
    from audiagentic.components.providers import providers_api

    install_graph(monkeypatch)
    host = GatewayServiceHost.create(shared_config=_config(tmp_path), application=object())
    runtime = host._node_runtime
    async def failed(**_kwargs):
        raise OSError("listener bind failed")
    monkeypatch.setattr(runtime.transport, "start", failed)
    monkeypatch.setattr(providers_api, "validate_gpt_auto_configuration", lambda: None)
    monkeypatch.setattr(known_projects, "scan_known_gpt_auto_projects", lambda *a, **kw: None)
    served = Mock()
    monkeypatch.setattr(host.server, "serve_forever", served)
    with pytest.raises(OSError, match="listener bind failed"):
        host.serve_forever()
    served.assert_not_called()
    assert host.service_store.read().state == "stopped"
    assert runtime.loop.is_closed() and runtime.ports._snapshot() is None
    assert host._closed


@pytest.mark.asyncio
async def test_ready_callback_failure_retains_dirty_and_keeps_actual_peer_healthy(runtime, monkeypatch):
    calls = []
    def wake(node):
        calls.append(node)
        if len(calls) == 1:
            raise OSError("work index temporarily unavailable")
    await asyncio.to_thread(runtime.start)
    monkeypatch.setattr(runtime, "wake", wake)
    async with peer(runtime) as (socket, welcome):
        await socket.send(wire(welcome, 2, "reconcile", {"kind": "receipt-ready",
            "log-incarnation-id": str(uuid4()), "through-sequence": 0,
            "through-receipt-sha256": None}).to_bytes())
        await until(lambda: len(calls) == 1)
        assert "node" in runtime.queue._node_wake_dirty
        pong = await socket.ping()
        await asyncio.wait_for(pong, 2)
        slot = await asyncio.to_thread(runtime.authority.serialize,
            lambda: runtime.connections.current_slot("node"))
        assert slot.connection.failure is None and slot.connection.close_reason is None
        assert await asyncio.to_thread(runtime.authority.serialize,
            lambda: runtime.connections.is_ready(slot.connection, grant_revision=1))
        await asyncio.to_thread(runtime.queue.retry_node_notifications)
        assert calls == ["node", "node"] and "node" not in runtime.queue._node_wake_dirty


@pytest.mark.asyncio
async def test_revoke_port_retires_actual_channel_without_historical_evidence(runtime):
    from websockets.exceptions import ConnectionClosed

    await asyncio.to_thread(runtime.start)
    async with peer(runtime) as (socket, welcome):
        await until(lambda: runtime.authority.serialize(
            lambda: runtime.connections.current_slot("node")) is not None)
        assert await asyncio.to_thread(runtime.revoke, "node", expected_grant_revision=1) == 2
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(socket.recv(), 2)
        assert not load_shared_server_config(runtime.config.config_path).nodes[0].enabled
