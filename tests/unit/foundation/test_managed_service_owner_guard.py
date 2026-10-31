"""Neutral owner guard shares the lifecycle store's existing writer lock."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


def running(tmp_path):
    store = ManagedServiceStore(ServiceKey("gateway", "guard"), root=tmp_path)
    record = store.create(protocol_version="test", owner_epoch="owner")
    store.transition("running", expected_revision=record.revision, expected_epoch="owner")
    return store


def test_owner_guard_yields_current_record_without_writing(tmp_path):
    store = running(tmp_path)
    before = store.record_path.read_bytes()
    with store.owner_guard("owner") as record:
        assert record.state == "running"
        assert record.owner_epoch == "owner"
    assert store.record_path.read_bytes() == before


@pytest.mark.parametrize("epoch", ["stale", "", None])
def test_owner_guard_rejects_wrong_epoch_before_entering_body(tmp_path, epoch):
    store = running(tmp_path)
    with pytest.raises(AudiaGenticError, match="CON-MSVC-014"):
        with store.owner_guard(epoch):
            pytest.fail("stale owner entered guard")


@pytest.mark.parametrize("state", ["starting", "draining", "stopping", "failed", "stopped"])
def test_owner_guard_requires_running(tmp_path, state):
    store = running(tmp_path)
    if state == "starting":
        # A fresh starting store is not ready to protect service work.
        store = ManagedServiceStore(ServiceKey("gateway", "starting"), root=tmp_path)
        store.create(protocol_version="test", owner_epoch="owner")
    else:
        record = store.read()
        store.transition(
            state if state != "stopped" else "stopping",
            expected_revision=record.revision, expected_epoch="owner",
        )
        if state == "stopped":
            record = store.read()
            store.transition("stopped", expected_revision=record.revision, expected_epoch="owner")
    with pytest.raises(AudiaGenticError, match="CON-MSVC-018"):
        with store.owner_guard("owner"):
            pytest.fail("non-running service entered guard")


@pytest.mark.parametrize("replace_owner", [False, True])
def test_guard_orders_retirement_and_replacement_on_existing_lock(tmp_path, replace_owner):
    store = running(tmp_path)
    started = Event()
    finished = Event()

    def transition():
        started.set()
        record = store.read()
        store.transition(
            "stopping", expected_revision=record.revision, expected_epoch="owner",
            new_owner_epoch="replacement" if replace_owner else None,
        )
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.owner_guard("owner"):
            future = pool.submit(transition)
            assert started.wait(5)
            assert not finished.wait(0.1)
            assert store.read().owner_epoch == "owner"
        future.result(timeout=5)
    assert finished.is_set()
    with pytest.raises(AudiaGenticError):
        with store.owner_guard("owner"):
            pytest.fail("retired/replaced owner entered guard")


def test_guard_exception_releases_existing_lock(tmp_path):
    store = running(tmp_path)
    with pytest.raises(RuntimeError):
        with store.owner_guard("owner"):
            raise RuntimeError("local mutation failed")
    with store.owner_guard("owner"):
        pass


@pytest.mark.parametrize("action", ["claim", "retire"])
def test_real_owner_claim_and_retire_share_guard_lock(tmp_path, action):
    from audiagentic.foundation.system.managed_process import ProcessIdentity
    from audiagentic.foundation.system.managed_service_contracts import (
        EndpointInfo,
        ProcessEvidence,
    )
    from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner

    store = ManagedServiceStore(ServiceKey("gateway", "real-owner"), root=tmp_path)
    alive = {"value": True}
    def evidence(epoch):
        alive["value"] = True  # newly launched owner has observable evidence
        return ProcessEvidence(
            pid=12345, scope="external-adopted", command_fingerprint="test",
            ownership_proof_kind="creation-identity", owner_epoch=epoch, creation_identity="test-created",
        )
    def observe(process):
        return ProcessIdentity(process.pid, creation_identity=process.creation_identity) if alive["value"] else None
    owner = ManagedServiceOwner(store, observe=observe)
    endpoint = EndpointInfo("local-http", "127.0.0.1:9999", "test-auth")
    record = owner.claim(protocol_version="test", endpoint=endpoint, evidence_factory=evidence)
    entered, finished = Event(), Event()
    def change_owner():
        entered.set()
        if action == "retire":
            result = owner.retire(expected_epoch=record.owner_epoch)
        else:
            result = owner.claim(protocol_version="test", endpoint=endpoint, evidence_factory=evidence)
        finished.set()
        return result
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.owner_guard(record.owner_epoch):
            if action == "claim":
                alive["value"] = False  # prior process proven dead by test observer
            future = pool.submit(change_owner)
            assert entered.wait(5)
            assert not finished.wait(0.1)
        changed = future.result(timeout=5)
    assert finished.is_set()
    if action == "claim":
        assert changed.owner_epoch != record.owner_epoch
    else:
        assert changed.state == "stopped"
