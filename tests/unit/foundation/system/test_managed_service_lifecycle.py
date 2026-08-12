from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import DetachedLaunch, ProcessIdentity
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import (
    EndpointInfo,
    ProcessEvidence,
    ServiceKey,
)
from audiagentic.foundation.system.managed_service_lifecycle import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ManagedServiceLifecycle,
    ServiceHandshake,
)


class FakeService:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.launch_count = 0
        self.signal_count = 0
        self.alive: dict[int, str] = {}
        self.ready = True
        self.is_quiescent = True
        self.stop_on_request = True

    def launch(self, _launch: DetachedLaunch, *, owner_epoch: str) -> ProcessEvidence:
        with self.guard:
            self.launch_count += 1
            pid = 1000 + self.launch_count
            creation = f"created-{pid}"
            self.alive[pid] = creation
        return ProcessEvidence(
            pid=pid,
            scope="shared-service-host",
            command_fingerprint="sha256:fake",
            ownership_proof_kind="creation-identity",
            owner_epoch=owner_epoch,
            creation_identity=creation,
        )

    def observe(self, evidence: ProcessEvidence) -> ProcessIdentity | None:
        creation = self.alive.get(evidence.pid)
        return None if creation is None else ProcessIdentity(evidence.pid, creation_identity=creation)

    def handshake(self, record):
        return ServiceHandshake(
            ready=self.ready,
            owner_epoch=record.owner_epoch,
            protocol_version=record.protocol_version,
            endpoint=record.endpoint,
            health_facts={"ready": self.ready},
        )

    def quiescent(self, _record) -> bool:
        return self.is_quiescent

    def request_stop(self, record) -> None:
        if self.stop_on_request:
            self.alive.pop(record.process.pid, None)

    def signal(self, evidence, observed, *, force: bool) -> None:
        assert observed.creation_identity == self.alive[evidence.pid]
        assert force is True
        self.signal_count += 1
        self.alive.pop(evidence.pid, None)

    def hooks(self) -> ManagedServiceHooks:
        return ManagedServiceHooks(
            handshake=self.handshake,
            quiescent=self.quiescent,
            request_stop=self.request_stop,
            observe=self.observe,
            launch=self.launch,
            signal=self.signal,
        )


def _lifecycle(tmp_path: Path) -> tuple[ManagedServiceLifecycle, ManagedServiceStore, FakeService, ManagedServiceDeclaration]:
    key = ServiceKey("gateway", "shared")
    store = ManagedServiceStore(key, root=tmp_path)
    service = FakeService()
    lifecycle = ManagedServiceLifecycle(store, service.hooks())
    declaration = ManagedServiceDeclaration(
        key=key,
        process=DetachedLaunch(("fake-gateway",)),
        endpoint=EndpointInfo("local-http", "127.0.0.1:9191", "gateway-auth"),
        protocol_version="v1",
        readiness_timeout=0.2,
        readiness_poll_interval=0.005,
    )
    return lifecycle, store, service, declaration


def test_concurrent_cold_start_launches_once_and_leases_every_client(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)

    def attach(index: int):
        return lifecycle.start_or_attach(
            declaration, client_instance_id=f"client-{index}", lease_ttl_seconds=60
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attach, range(12)))

    assert service.launch_count == 1
    assert sum(result.disposition == "started" for result in results) == 1
    assert {result.disposition for result in results} <= {"attached", "started"}
    assert store.read().active_lease_count == 12


def test_readiness_window_must_fit_cross_process_lock_budget(tmp_path: Path) -> None:
    key = ServiceKey("gateway", "bounded-lock")
    store = ManagedServiceStore(key, root=tmp_path, lock_timeout=1.0)
    service = FakeService()
    lifecycle = ManagedServiceLifecycle(store, service.hooks())
    declaration = ManagedServiceDeclaration(
        key=key,
        process=DetachedLaunch(("fake-gateway",)),
        endpoint=EndpointInfo("local-http", "127.0.0.1:9191", "gateway-auth"),
        protocol_version="v1",
        readiness_timeout=1.0,
    )

    with pytest.raises(AudiaGenticError, match="VAL-MSVC-037"):
        lifecycle.start_or_attach(
            declaration, client_instance_id="client-a", lease_ttl_seconds=60
        )
    assert service.launch_count == 0


def test_stale_starting_record_is_recovered_after_starter_death(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    created = store.create(protocol_version="v1", owner_epoch="dead-owner")
    stale = replace(
        created,
        process=ProcessEvidence(
            pid=999,
            scope="shared-service-host",
            command_fingerprint="sha256:old",
            ownership_proof_kind="creation-identity",
            owner_epoch=created.owner_epoch,
            creation_identity="dead-process",
        ),
        endpoint=declaration.endpoint,
    )
    store._write_unlocked(stale, "test.stale-owner")

    result = lifecycle.start_or_attach(
        declaration, client_instance_id="client-new", lease_ttl_seconds=60
    )

    assert result.disposition == "recovered"
    assert result.record.owner_epoch != "dead-owner"
    assert service.launch_count == 1


def test_decoy_process_never_attaches_or_receives_stop_signal(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    initial = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    process = initial.record.process
    assert process is not None
    service.alive[process.pid] = "decoy-creation"

    with pytest.raises(AudiaGenticError, match="CON-MSVC-028"):
        lifecycle.start_or_attach(
            declaration, client_instance_id="client-b", lease_ttl_seconds=60
        )

    assert service.signal_count == 0
    assert store.read().active_lease_count == 1


def test_incompatible_protocol_does_not_attach_or_relaunch(tmp_path: Path) -> None:
    lifecycle, _store, service, declaration = _lifecycle(tmp_path)
    lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )

    with pytest.raises(AudiaGenticError, match="CON-MSVC-023"):
        lifecycle.start_or_attach(
            replace(declaration, protocol_version="v2"),
            client_instance_id="client-b",
            lease_ttl_seconds=60,
        )

    assert service.launch_count == 1


def test_failed_readiness_cleans_up_only_the_proven_launched_process(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    service.ready = False

    with pytest.raises(AudiaGenticError, match="CON-MSVC-029"):
        lifecycle.start_or_attach(
            replace(declaration, readiness_timeout=0.02),
            client_instance_id="client-a",
            lease_ttl_seconds=60,
        )

    assert service.signal_count == 1
    assert service.alive == {}
    assert store.read().state == "failed"


def test_native_launcher_failure_is_classified_at_public_boundary(tmp_path: Path) -> None:
    _lifecycle_value, store, service, declaration = _lifecycle(tmp_path)

    def fail_launch(_launch, *, owner_epoch):
        raise RuntimeError(f"launch unavailable for {owner_epoch}")

    lifecycle = ManagedServiceLifecycle(store, replace(service.hooks(), launch=fail_launch))
    with pytest.raises(AudiaGenticError, match="CON-MSVC-033"):
        lifecycle.start_or_attach(
            declaration, client_instance_id="client-a", lease_ttl_seconds=60
        )

    assert store.read().state == "failed"


def test_drain_blocks_new_attach_and_stop_rechecks_lease_and_quiescence(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    draining = lifecycle.request_drain(
        expected_revision=started.record.revision,
        expected_epoch=started.record.owner_epoch,
    )

    with pytest.raises(AudiaGenticError, match="CON-MSVC-026"):
        lifecycle.start_or_attach(
            declaration, client_instance_id="client-b", lease_ttl_seconds=60
        )
    assert lifecycle.stop_if_quiescent(expected_epoch=draining.owner_epoch).outcome == "active-leases"

    released = store.release_lease(started.lease.lease_id, expected_epoch=draining.owner_epoch)
    service.is_quiescent = False
    assert lifecycle.stop_if_quiescent(expected_epoch=released.owner_epoch).outcome == "not-quiescent"
    service.is_quiescent = True

    stopped = lifecycle.stop_if_quiescent(expected_epoch=released.owner_epoch)
    assert stopped.outcome == "stopped"
    assert stopped.forced is False
    assert stopped.record.process is None


def test_stale_draining_without_leases_restarts_through_normal_path(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    released = store.release_lease(started.lease.lease_id, expected_epoch=started.record.owner_epoch)
    draining = lifecycle.request_drain(
        expected_revision=released.revision, expected_epoch=released.owner_epoch
    )
    assert draining.state == "draining"
    assert draining.process is not None
    service.alive.pop(draining.process.pid, None)

    restarted = lifecycle.start_or_attach(
        declaration, client_instance_id="client-b", lease_ttl_seconds=60
    )
    assert restarted.disposition == "recovered"
    assert restarted.record.state == "running"
    assert service.launch_count == 2


def test_reconnect_expires_dead_client_lease_before_stale_drain_restart(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    process = started.record.process
    assert process is not None
    released = store.release_lease(
        started.lease.lease_id, expected_epoch=started.record.owner_epoch
    )
    draining = lifecycle.request_drain(
        expected_revision=released.revision, expected_epoch=released.owner_epoch
    )
    # Simulate a client that died after the drain snapshot but before its
    # lease-expiry sweep. The process is also gone, so reconnect is safe.
    service.alive.pop(process.pid, None)
    stale_lease = replace(
        started.lease,
        state="active",
        expires_at="2000-01-01T00:00:00Z",
    )
    store._write_unlocked(
        replace(draining, leases=(stale_lease,)), "test.expired-lease"
    )

    restarted = lifecycle.start_or_attach(
        declaration, client_instance_id="client-b", lease_ttl_seconds=60
    )
    assert restarted.record.state == "running"
    assert restarted.disposition == "recovered"
    assert restarted.record.active_lease_count == 1


def test_draining_with_live_process_refuses_restart_even_without_leases(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    released = store.release_lease(started.lease.lease_id, expected_epoch=started.record.owner_epoch)
    _draining = lifecycle.request_drain(
        expected_revision=released.revision, expected_epoch=released.owner_epoch
    )

    with pytest.raises(AudiaGenticError, match="CON-MSVC-028"):
        lifecycle.start_or_attach(
            declaration, client_instance_id="client-b", lease_ttl_seconds=60
        )
    assert service.launch_count == 1


def test_guarded_stop_forces_only_after_fresh_ownership_match(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    store.release_lease(started.lease.lease_id, expected_epoch=started.record.owner_epoch)
    current = store.read()
    lifecycle.request_drain(
        expected_revision=current.revision,
        expected_epoch=current.owner_epoch,
    )
    service.stop_on_request = False

    result = lifecycle.stop_if_quiescent(
        expected_epoch=current.owner_epoch,
        graceful_timeout=0.01,
        force_timeout=0.05,
    )

    assert result.outcome == "stopped"
    assert result.forced is True
    assert service.signal_count == 1


def test_guarded_stop_leaves_decoy_process_untouched(tmp_path: Path) -> None:
    lifecycle, store, service, declaration = _lifecycle(tmp_path)
    started = lifecycle.start_or_attach(
        declaration, client_instance_id="client-a", lease_ttl_seconds=60
    )
    store.release_lease(started.lease.lease_id, expected_epoch=started.record.owner_epoch)
    current = store.read()
    draining = lifecycle.request_drain(
        expected_revision=current.revision,
        expected_epoch=current.owner_epoch,
    )
    assert draining.process is not None
    service.alive[draining.process.pid] = "decoy-creation"

    result = lifecycle.stop_if_quiescent(expected_epoch=draining.owner_epoch)

    assert result.outcome == "ownership-unverified"
    assert result.record.state == "draining"
    assert service.signal_count == 0
