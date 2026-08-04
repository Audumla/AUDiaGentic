"""SH10 — gateway lifecycle: quiescence-gated drain/stop, idle self-shutdown,
and record-only unprovable-owner recovery."""
from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from audiagentic.components.agents.gateway.service import lifecycle as lifecycle_mod
from audiagentic.components.agents.gateway.service.host import GATEWAY_SERVICE_KEY
from audiagentic.components.agents.gateway.service.lifecycle import (
    GatewayLifecycleController,
    recover_unprovable_owner,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import current_process_evidence
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner

QUIET = {
    "pending-requests": 0, "running-requests": 0, "live-sessions": 0,
    "ingress-pending": 0, "quiescent": True,
}
BUSY = {**QUIET, "running-requests": 1, "quiescent": False}


@pytest.fixture
def claimed_store(tmp_path):
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=tmp_path / "svc")
    record = ManagedServiceOwner(store).claim(
        protocol_version="test-1",
        endpoint=EndpointInfo("loopback-http", "127.0.0.1:1", None),
        evidence_factory=lambda epoch: current_process_evidence(owner_epoch=epoch),
        health_facts={"ready": True},
    )
    return store, record


def _controller(store, record, *, idle_grace=0.0, interval=0.02, shutdowns=None):
    shutdowns = shutdowns if shutdowns is not None else []
    return GatewayLifecycleController(
        store, record.owner_epoch, lambda: shutdowns.append(True),
        service_root=store.root.parents[2],
        idle_grace_seconds=idle_grace, check_interval_seconds=interval,
    ), shutdowns


def test_status_reports_quiescence_and_policy(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(QUIET))
    controller, _ = _controller(store, record, idle_grace=42.0)
    status = controller.status()
    assert status["state"] == "running"
    assert status["idle-grace-seconds"] == 42.0
    assert status["quiescence"]["quiescent"] is True


def test_drain_and_resume_transitions(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(QUIET))
    controller, _ = _controller(store, record)
    assert controller.request_drain()["state"] == "draining"
    assert controller.request_drain()["state"] == "draining"  # idempotent
    assert controller.request_resume()["state"] == "running"


def test_graceful_stop_refuses_while_busy_force_reports_work(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(BUSY))
    controller, shutdowns = _controller(store, record)

    with pytest.raises(AudiaGenticError, match="CON-AGLC-001"):
        controller.request_stop(force=False)
    assert shutdowns == []

    outcome = controller.request_stop(force=True)
    assert outcome["forced"] is True
    assert outcome["affected-work"]["running-requests"] == 1
    assert shutdowns == [True]
    assert store.read().state == "draining"
    assert controller.exit_reason == "operator-force-stop"


def test_other_active_lease_blocks_graceful_stop(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(QUIET))
    # Two leases: the caller's own plus another client's.
    store.acquire_lease("caller", ttl_seconds=60, expected_epoch=record.owner_epoch)
    store.acquire_lease("other", ttl_seconds=60, expected_epoch=record.owner_epoch)
    controller, shutdowns = _controller(store, record)
    with pytest.raises(AudiaGenticError, match="CON-AGLC-001"):
        controller.request_stop(force=False)
    assert shutdowns == []


def _wait_for(predicate, timeout=3.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_idle_grace_elapsed_drains_and_shuts_down(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(QUIET))
    controller, shutdowns = _controller(store, record, idle_grace=0.05)
    controller.start()
    try:
        assert _wait_for(lambda: shutdowns)
        assert store.read().state == "draining"
        assert controller.exit_reason == "idle-grace-elapsed"
    finally:
        controller.stop()


def test_active_lease_keeps_service_warm(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(QUIET))
    store.acquire_lease("client-a", ttl_seconds=300, expected_epoch=record.owner_epoch)
    controller, shutdowns = _controller(store, record, idle_grace=0.05)
    controller.start()
    try:
        import time
        time.sleep(0.4)
        assert shutdowns == []
        assert store.read().state == "running"
    finally:
        controller.stop()


def test_active_work_keeps_service_warm(claimed_store, monkeypatch):
    store, record = claimed_store
    monkeypatch.setattr(lifecycle_mod, "gateway_quiescence_facts", lambda root=None: dict(BUSY))
    controller, shutdowns = _controller(store, record, idle_grace=0.05)
    controller.start()
    try:
        import time
        time.sleep(0.4)
        assert shutdowns == []
        assert store.read().state == "running"
    finally:
        controller.stop()


def test_idle_zero_disables_self_shutdown(claimed_store, monkeypatch):
    store, record = claimed_store
    controller, shutdowns = _controller(store, record, idle_grace=0.0)
    controller.start()  # no-op when disabled
    assert controller._thread is None
    controller.stop()


# ── record-only unprovable-owner recovery ───────────────────────────


def _make_unprovable(store, record):
    """Give the record process evidence whose ownership proof cannot match."""
    fake = replace(
        record.process,
        creation_identity="filetime:0",
        command_fingerprint="sha256:" + "0" * 64,
        group_identity=None,
    )
    return store.transition(
        "draining",
        expected_revision=record.revision,
        expected_epoch=record.owner_epoch,
        process=fake,
    )


def test_recover_refuses_provable_owner(claimed_store):
    store, _record = claimed_store
    with pytest.raises(AudiaGenticError, match="CON-AGLC-003"):
        recover_unprovable_owner(service_root=store.root.parents[2], confirm=True)


def test_recover_requires_explicit_confirmation(claimed_store):
    store, record = claimed_store
    _make_unprovable(store, record)
    with pytest.raises(AudiaGenticError, match="VAL-AGLC-004"):
        recover_unprovable_owner(service_root=store.root.parents[2], confirm=False)


def test_recover_marks_failed_preserves_diagnostics_never_signals(claimed_store):
    store, record = claimed_store
    _make_unprovable(store, record)
    outcome = recover_unprovable_owner(
        service_root=store.root.parents[2], confirm=True, reason="operator ticket 42"
    )
    assert outcome["recovered"] is True
    current = store.read()
    assert current.state == "failed"
    assert current.failure["failure-class"] == "unprovable-owner-recovered"
    assert current.failure["recorded-pid"] == record.process.pid
    assert current.failure["reason"] == "operator ticket 42"
    # The recorded process (this test process) was never signalled — we are
    # still alive to assert it.
    assert threading.current_thread().is_alive()
