from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import (
    EndpointInfo,
    ManagedServiceRecord,
    ManagedServiceStore,
    ProcessEvidence,
    ServiceKey,
)


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> str:
        return self.value.isoformat().replace("+00:00", "Z")

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _running_store(
    tmp_path: Path, clock: Clock | None = None
) -> tuple[ManagedServiceStore, ManagedServiceRecord]:
    store = ManagedServiceStore(ServiceKey("gateway", "default"), root=tmp_path, clock=clock or Clock())
    created = store.create(protocol_version="v1", owner_epoch="epoch-a")
    process = ProcessEvidence(
        pid=123, scope="shared-service-host", command_fingerprint="sha256:abc",
        ownership_proof_kind="launch-lock", owner_epoch=created.owner_epoch,
    )
    running = store.transition(
        "running", expected_revision=created.revision, expected_epoch=created.owner_epoch,
        process=process, endpoint=EndpointInfo("local-http", "127.0.0.1:9000", "gateway-auth"),
        health_facts={"ready": True},
    )
    return store, running


def test_create_round_trips_one_atomic_record(tmp_path: Path) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "default"), root=tmp_path, clock=Clock())
    record = store.create(protocol_version="v1", owner_epoch="epoch-a")

    assert store.read() == record
    assert record.state == "starting"
    assert record.revision == 1
    assert store.record_path.is_file()
    assert store.timeline_path.is_file()


def test_transition_rejects_illegal_and_stale_writers(tmp_path: Path) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "default"), root=tmp_path, clock=Clock())
    created = store.create(protocol_version="v1", owner_epoch="epoch-a")

    with pytest.raises(AudiaGenticError, match="CON-MSVC-015"):
        store.transition("stopped", expected_revision=1, expected_epoch="epoch-a")
    with pytest.raises(AudiaGenticError, match="CON-MSVC-014"):
        store.transition("running", expected_revision=99, expected_epoch="epoch-a")

    assert store.read() == created


def test_lease_release_and_expiry_remain_distinguishable(tmp_path: Path) -> None:
    clock = Clock()
    store, running = _running_store(tmp_path, clock)
    first_record, first = store.acquire_lease(
        "client-a", ttl_seconds=10, expected_epoch=running.owner_epoch
    )
    second_record, second = store.acquire_lease(
        "client-b", ttl_seconds=10, expected_epoch=running.owner_epoch
    )
    assert first_record.active_lease_count == 1
    assert second_record.active_lease_count == 2

    released = store.release_lease(first.lease_id, expected_epoch=running.owner_epoch)
    clock.advance(11)
    expired = store.expire_leases(expected_epoch=running.owner_epoch)

    states = {lease.lease_id: lease.state for lease in expired.leases}
    assert states[first.lease_id] == "released"
    assert states[second.lease_id] == "expired"
    assert released.revision < expired.revision
    assert expired.active_lease_count == 0
    assert store.get_lease(first.lease_id).state == "released"


def test_heartbeat_updates_health_without_lifecycle_transition(tmp_path: Path) -> None:
    store, running = _running_store(tmp_path)

    heartbeat = store.heartbeat(
        {"ready": True, "queue-depth": 0},
        expected_epoch=running.owner_epoch,
    )

    assert heartbeat.state == "running"
    assert heartbeat.revision == running.revision + 1
    assert heartbeat.health_facts == {"ready": True, "queue-depth": 0}


def test_lease_history_is_bounded_and_active_authority_expires_idle_lease(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store, running = _running_store(tmp_path, clock)
    for index in range(300):
        _, lease = store.acquire_lease(
            f"client-{index}", ttl_seconds=10, expected_epoch=running.owner_epoch
        )
        store.release_lease(lease.lease_id, expected_epoch=running.owner_epoch)

    assert len(store.read().leases) <= 256

    _, expiring = store.acquire_lease(
        "client-expiring", ttl_seconds=1, expected_epoch=running.owner_epoch
    )
    clock.advance(2)
    with pytest.raises(AudiaGenticError, match="CON-MSVC-019"):
        store.require_active_lease(
            expiring.lease_id, expected_epoch=running.owner_epoch
        )
    assert store.get_lease(expiring.lease_id).state == "expired"


def test_v1_rejects_non_machine_scope() -> None:
    with pytest.raises(AudiaGenticError, match="VAL-MSVC-001"):
        ServiceKey("gateway", "default", scope="project")


def test_lease_metadata_reuses_shared_denylist(tmp_path: Path) -> None:
    store, running = _running_store(tmp_path)
    with pytest.raises(AudiaGenticError, match="VAL-MSVC-003"):
        store.acquire_lease(
            "client-a", ttl_seconds=10, expected_epoch=running.owner_epoch,
            facts={"nested": {"api_key": "secret"}},
        )


def test_concurrent_lease_acquires_do_not_lose_updates(tmp_path: Path) -> None:
    store, running = _running_store(tmp_path)

    def acquire(index: int) -> str:
        _, lease = store.acquire_lease(
            f"client-{index}", ttl_seconds=60, expected_epoch=running.owner_epoch
        )
        return lease.lease_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        lease_ids = list(pool.map(acquire, range(16)))

    record = store.read()
    assert record.active_lease_count == 16
    assert len(set(lease_ids)) == 16
    assert record.revision == running.revision + 16


def test_foundation_module_has_no_component_runtime_or_mcp_dependency() -> None:
    import audiagentic.foundation.system.managed_service as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "audiagentic.components" not in source
    assert "audiagentic.runtime" not in source
    assert "audiagentic.foundation.mcp" not in source
