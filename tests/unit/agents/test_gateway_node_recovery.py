"""Node owner takeover preserves uncertain remote effects, never local fallback."""
import builtins
import json
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.components.agents.gateway.queue import recovery, work_index
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore

from .test_gateway_node_dispatch_store import apply, authorize, bind, identity, placement, receipt


@pytest.fixture
def service(tmp_path):
    owner = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=tmp_path / "service")
    created = owner.create(protocol_version="test", owner_epoch="new-owner")
    owner.transition("running", expected_revision=created.revision, expected_epoch="new-owner")
    return owner


def make_record(root, service, kind, *, cancel=False):
    record = store.build_record(execution_profile_id="profile", prompt_body="hello", node_placement=placement())
    store.write_record(root, record)
    work_index.write_work_index_entry(service.root, root, record["request-id"], phase="admitted")
    if kind != "queued-unclaimed":
        record = store.claim_dispatch(root, record["request-id"], owner_epoch="owner",
                                      expected_revision=record["revision"], service_root=service.root)
    if kind not in {"queued-unclaimed", "queued-claimed"}:
        record = store.start_owned_attempt(root, record["request-id"], owner_epoch="owner", worker_id="worker",
                                          expected_revision=record["revision"])
        work_index.write_work_index_entry(service.root, root, record["request-id"], phase="running", owner_epoch="owner")
    if kind in {"bound-prepared", "authorized", "native-receipt", "terminal-receipt"}:
        record = bind(root, record)
    if kind in {"authorized", "native-receipt", "terminal-receipt"}:
        record = authorize(root, record)
    if kind in {"native-receipt", "terminal-receipt"}:
        record = apply(root, record, receipt(identity(record), 3, "native-accepted"))
    if kind == "terminal-receipt":
        record = apply(root, record, receipt(identity(record), 4, "terminal", "a" * 64))
    if cancel:
        record = store.mark_cancel_requested(root, record["request-id"])
    return store.read_record(root, record["request-id"])


def recover(service):
    with service.owner_guard("new-owner"):
        return recovery.recover_gateway_requests(service.root, live_owner_epoch="new-owner")


def assert_markers(service, root, request_id):
    active = json.loads(store.active_work_path(service.root, request_id).read_text(encoding="utf-8"))
    assert active["owner-epoch"] == "new-owner" and active["project-root"] == str(root)
    entries, quarantined = work_index.recover_work_index_entries(service.root, live_owner_epoch="new-owner")
    assert not quarantined
    entry = next(entry for entry in entries if entry.request_id == request_id)
    assert entry.owner_epoch == "new-owner" and entry.project_root == root


@pytest.mark.parametrize("kind", ["queued-unclaimed", "queued-claimed", "running-unbound", "bound-prepared",
                                  "authorized", "native-receipt", "terminal-receipt"])
@pytest.mark.parametrize("cancel", [False, True])
def test_node_takeover_preserves_original_attempt_command_receipt_and_cancellation(service, tmp_path, kind, cancel):
    root = tmp_path / "project"
    before = make_record(root, service, kind, cancel=cancel)
    report = recover(service)
    current = store.read_record(root, before["request-id"])
    expected_items = ((root, before["request-id"]),)
    assert report.interrupted == report.replay_required == report.cleared == 0
    assert (report.queued if before["state"] == "queued" else report.running) == expected_items
    assert current["dispatch-owner-epoch"] == "new-owner"
    assert current["state"] == before["state"]
    assert current["recovery-required"] is (before["state"] == "running")
    for key in ("worker-id", "attempt-epoch", "attempts", "node-placement", "node-admission", "node-dispatch",
                "cancel-requested", "cancel-provenance", "error", "diagnostics", "finished-at",
                "session-id", "replay-required", "replay-reason"):
        assert current[key] == before[key], key
    if current["node-dispatch"] is not None:
        # The original command epoch stays historical, not rewritten to the new owner.
        assert CommandIdentity.from_mapping(current["node-dispatch"]["identity"]).gateway_owner_epoch == "owner"
    assert_markers(service, root, before["request-id"])
    repeated = recover(service)
    assert repeated.queued == repeated.running == ()
    assert store.read_record(root, before["request-id"]) == current


@pytest.mark.parametrize("failure", ["index", "active-marker"])
def test_partial_takeover_crash_repairs_common_markers_without_replacing_attempt(service, tmp_path, monkeypatch, failure):
    root = tmp_path / "project"
    before = make_record(root, service, "native-receipt", cancel=True)
    if failure == "index":
        target, name = work_index, "takeover_owner"
    else:
        target, name = store, "record_active_work"
    original = getattr(target, name)

    def crash(*args, **kwargs):
        raise OSError("simulated crash after canonical owner commit")

    monkeypatch.setattr(target, name, crash)
    with pytest.raises(OSError):
        recover(service)
    committed = store.read_record(root, before["request-id"])
    assert committed["dispatch-owner-epoch"] == "new-owner"
    assert committed["worker-id"] == before["worker-id"]
    assert committed["node-dispatch"] == before["node-dispatch"]
    monkeypatch.setattr(target, name, original)
    # Re-enter takeover completion after the canonical half committed before
    # marker publication. The existing common tail handles the old expected
    # owner and repairs both markers idempotently.
    with service.owner_guard("new-owner"):
        state, item = recovery._takeover_stale_request(
            service.root, root, before["request-id"], "owner", live_owner_epoch="new-owner",
        )
    assert state == "running" and item == (root, before["request-id"])
    assert store.read_record(root, before["request-id"]) == committed
    assert_markers(service, root, before["request-id"])


def test_index_epoch_conflict_uses_existing_marker_repair_tail(service, tmp_path, monkeypatch):
    root = tmp_path / "project"
    before = make_record(root, service, "authorized")
    original = work_index.takeover_owner
    calls = []

    def conflict_once(*args, **kwargs):
        calls.append(kwargs["expected_owner_epoch"])
        if len(calls) == 1:
            raise AudiaGenticError("CON-AGW-106", "agents", "index epoch conflict")
        return original(*args, **kwargs)

    monkeypatch.setattr(work_index, "takeover_owner", conflict_once)
    recover(service)
    assert calls == ["owner", None]
    assert_markers(service, root, before["request-id"])


def test_stale_owner_cannot_mutate_receipts_or_takeover_another_live_generation(service, tmp_path):
    root = tmp_path / "project"
    before = make_record(root, service, "native-receipt")
    recover(service)
    current = store.read_record(root, before["request-id"])
    with pytest.raises(AudiaGenticError):
        store.apply_owned_node_receipt(
            root, before["request-id"], receipt=receipt(identity(before), 4, "terminal", "a" * 64),
            owner_epoch="owner", worker_id=before["worker-id"], attempt_epoch=before["attempt-epoch"],
            expected_revision=current["revision"],
        )
    with pytest.raises(AudiaGenticError, match="CON-AGW-083"):
        recovery._takeover_stale_request(service.root, root, before["request-id"], "owner", live_owner_epoch="third-owner")
    assert store.read_record(root, before["request-id"]) == current
    assert_markers(service, root, before["request-id"])


@pytest.mark.parametrize("kind", ["queued-unclaimed", "running-unbound", "authorized"])
def test_node_record_never_enters_ordinary_provider_recovery_factory(service, tmp_path, monkeypatch, kind):
    root = tmp_path / "project"
    before = make_record(root, service, kind)
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in {"audiagentic.components.agents.gateway.api", "audiagentic.components.agents.gateway.queue.dispatch"} or name.startswith("audiagentic.components.providers"):
            pytest.fail("node recovery attempted ordinary Provider imports")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(AudiaGenticError) as caught:
        recovery.recovery_runner(before, project_root=root)
    assert caught.value.code == "CON-AGND-001"
    assert store.read_record(root, before["request-id"]) == before


@pytest.mark.parametrize("invalid", ["owner", "revision", "missing-revision"])
def test_unclaimed_node_deferral_requires_exact_current_owner_and_revision(service, tmp_path, invalid):
    root = tmp_path / "project"
    before = make_record(root, service, "queued-unclaimed")
    recover(service)
    current = store.read_record(root, before["request-id"])
    with pytest.raises(AudiaGenticError):
        store.defer_owned_queued_recovery(root, current["request-id"],
            owner_epoch="old-owner" if invalid == "owner" else "new-owner", worker_id=None, attempt_epoch=0,
            expected_revision=None if invalid == "missing-revision" else current["revision"] + (invalid == "revision"),
            error=None, phase="node-runtime-unavailable", side_effect_state="not-started", retry_delay_seconds=None)
    assert store.read_record(root, before["request-id"]) == current


def test_unclaimed_ordinary_request_cannot_use_node_deferral(service, tmp_path):
    root = tmp_path / "project"
    current = store.build_record(execution_profile_id="ordinary", prompt_body="hello")
    store.write_record(root, current)
    current = store.read_record(root, current["request-id"])
    with pytest.raises(AudiaGenticError, match="VAL-AGW-085"):
        store.defer_owned_queued_recovery(root, current["request-id"], owner_epoch="new-owner",
            worker_id=None, attempt_epoch=0, expected_revision=current["revision"],
            error=None, phase="node-runtime-unavailable", side_effect_state="not-started", retry_delay_seconds=None)
    assert store.read_record(root, current["request-id"]) == current


def test_trace_and_warning_sink_failure_cannot_reverse_committed_node_deferral(service, tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.store import _transitions

    root = tmp_path / "project"
    before = make_record(root, service, "queued-unclaimed")
    recover(service)
    current = store.read_record(root, before["request-id"])
    failures = store.recovery_trace_failure_count()
    monkeypatch.setattr(_transitions, "record_gateway_timeline", Mock(side_effect=OSError("PRIVATE trace error")))
    monkeypatch.setattr(_transitions.logger, "warning", Mock(side_effect=OSError("PRIVATE logger error")))
    updated = store.defer_owned_queued_recovery(root, current["request-id"], owner_epoch="new-owner",
        worker_id=None, attempt_epoch=0, expected_revision=current["revision"],
        error=None, phase="node-runtime-unavailable", side_effect_state="not-started", retry_delay_seconds=None)
    assert store.read_record(root, current["request-id"]) == updated
    assert updated["recovery"]["phase"] == "node-runtime-unavailable"
    assert store.recovery_trace_failure_count() == failures + 1
    assert "PRIVATE" not in json.dumps(updated)
