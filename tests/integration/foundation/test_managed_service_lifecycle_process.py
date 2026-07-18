"""Real detached-process mutation gate for PR07 and the clean Docker suite."""
from __future__ import annotations

import json
import multiprocessing
import sys
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import (
    DetachedLaunch,
    observe_process,
    ownership_matches,
    signal_owned_process,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_lifecycle import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ManagedServiceLifecycle,
    ServiceHandshake,
)


def _declaration(ready_path: Path) -> ManagedServiceDeclaration:
    key = ServiceKey("test-service", "cold-start")
    host_script = Path(__file__).parents[2] / "fixtures" / "managed_service_host.py"
    executable = getattr(sys, "_base_executable", sys.executable)
    return ManagedServiceDeclaration(
        key=key,
        process=DetachedLaunch((executable, str(host_script), str(ready_path))),
        endpoint=EndpointInfo("test-file", str(ready_path)),
        protocol_version="v1",
        readiness_timeout=5,
        readiness_poll_interval=0.02,
    )


def _hooks(ready_path: Path) -> ManagedServiceHooks:
    def handshake(record) -> ServiceHandshake:
        payload = json.loads(ready_path.read_text(encoding="utf-8"))
        return ServiceHandshake(
            ready=payload["pid"] == record.process.pid,
            owner_epoch=payload["owner-epoch"],
            protocol_version="v1",
            endpoint=record.endpoint,
            health_facts={"ready": True},
        )

    def request_stop(record) -> None:
        observed = observe_process(record.process)
        signal_owned_process(record.process, observed, force=False)

    return ManagedServiceHooks(
        handshake=handshake,
        quiescent=lambda _record: True,
        request_stop=request_stop,
    )


def _attach_client(
    root: str,
    ready_path: str,
    client_index: int,
    barrier,
    results,
) -> None:
    declaration = _declaration(Path(ready_path))
    store = ManagedServiceStore(declaration.key, root=Path(root))
    lifecycle = ManagedServiceLifecycle(store, _hooks(Path(ready_path)))
    barrier.wait()
    try:
        result = lifecycle.start_or_attach(
            declaration,
            client_instance_id=f"client-{client_index}",
            lease_ttl_seconds=60,
        )
    except AudiaGenticError as exc:
        if exc.code == "CON-MPROC-003":
            results.put(("environment-gated", "", ""))
            return
        raise
    results.put((result.disposition, result.lease.lease_id, result.record.owner_epoch))


def test_independent_clients_launch_once_then_guardedly_stop(tmp_path: Path) -> None:
    ready_path = tmp_path / "ready.json"
    declaration = _declaration(ready_path)
    store = ManagedServiceStore(declaration.key, root=tmp_path)
    lifecycle = ManagedServiceLifecycle(store, _hooks(ready_path))
    context = multiprocessing.get_context("spawn")
    barrier = context.Event()
    results = context.Queue()
    clients = [
        context.Process(
            target=_attach_client,
            args=(str(tmp_path), str(ready_path), index, barrier, results),
        )
        for index in range(6)
    ]

    try:
        for client in clients:
            client.start()
        barrier.set()
        for client in clients:
            client.join(timeout=20)
            assert client.exitcode == 0
        outcomes = [results.get(timeout=2) for _ in clients]
        gated = [item for item in outcomes if item[0] == "environment-gated"]
        if gated:
            assert len(gated) == len(outcomes)
            pytest.skip("Windows client Job Objects deny detached-process breakaway")
        assert sum(disposition == "started" for disposition, _, _ in outcomes) == 1
        assert {disposition for disposition, _, _ in outcomes} <= {"started", "attached"}
        assert len({epoch for _, _, epoch in outcomes}) == 1
        assert store.read().active_lease_count == len(clients)

        epoch = outcomes[0][2]
        for _, lease_id, _ in outcomes:
            store.release_lease(lease_id, expected_epoch=epoch)
        current = store.read()
        lifecycle.request_drain(
            expected_revision=current.revision,
            expected_epoch=current.owner_epoch,
        )
        stopped = lifecycle.stop_if_quiescent(
            expected_epoch=current.owner_epoch,
            graceful_timeout=5,
            force_timeout=2,
        )
        assert stopped.outcome == "stopped"
        assert stopped.record.process is None
    finally:
        if store.record_path.exists():
            record = store.read()
            if record.process is not None:
                observed = observe_process(record.process)
                if ownership_matches(record.process, observed):
                    signal_owned_process(record.process, observed, force=True)
