"""Filesystem mutation gate for PR06; runs in the clean Docker suite too."""
from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore, ServiceKey


def _acquire(root: str, client_index: int, epoch: str) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "docker-mutation"), root=Path(root))
    store.acquire_lease(f"client-{client_index}", ttl_seconds=2, expected_epoch=epoch)


def _release(root: str, lease_id: str, epoch: str) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "docker-mutation"), root=Path(root))
    store.release_lease(lease_id, expected_epoch=epoch)


def _expire(root: str, epoch: str) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "docker-mutation"), root=Path(root))
    store.expire_leases(expected_epoch=epoch)


def _reject_stale_epoch(root: str) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "docker-mutation"), root=Path(root))
    try:
        store.acquire_lease("stale-client", ttl_seconds=1, expected_epoch="stale-epoch")
    except AudiaGenticError as exc:
        if exc.code == "CON-MSVC-014":
            return
        raise
    raise AssertionError("stale epoch unexpectedly acquired a lease")


def _join_cleanly(processes: list[multiprocessing.Process]) -> None:
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0


def test_multiple_processes_mutate_one_service_without_lost_updates(tmp_path: Path) -> None:
    store = ManagedServiceStore(ServiceKey("gateway", "docker-mutation"), root=tmp_path)
    created = store.create(protocol_version="v1", owner_epoch="epoch-docker")
    running = store.transition(
        "running", expected_revision=created.revision, expected_epoch=created.owner_epoch
    )

    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_acquire, args=(str(tmp_path), index, running.owner_epoch)) for index in range(8)]
    for process in processes:
        process.start()
    _join_cleanly(processes)

    acquired = store.read()
    assert acquired.active_lease_count == 8
    assert acquired.revision == running.revision + 8

    stale = context.Process(target=_reject_stale_epoch, args=(str(tmp_path),))
    stale.start()
    _join_cleanly([stale])

    time.sleep(2.1)
    mutations = [
        context.Process(target=_release, args=(str(tmp_path), lease.lease_id, running.owner_epoch))
        for lease in acquired.leases[:4]
    ]
    mutations.append(context.Process(target=_expire, args=(str(tmp_path), running.owner_epoch)))
    for process in mutations:
        process.start()
    _join_cleanly(mutations)

    final = store.read()
    assert final.active_lease_count == 0
    assert {lease.state for lease in final.leases} <= {"released", "expired"}
    assert len(final.leases) == 8
    assert not list(tmp_path.rglob("*.tmp"))
