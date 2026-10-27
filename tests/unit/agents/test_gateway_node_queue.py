"""Inactive node queue variant: scheduling only, no native execution."""
import threading
from dataclasses import replace

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.placement import NodeAdmissionPlacement
from audiagentic.components.agents.gateway.queue import queue as queue_mod

from .test_gateway_node_dispatch_store import apply, authorize, bind, identity, receipt

pytestmark = pytest.mark.no_parallel


def node_record(root, *, profile="profile", node="node", workspace="workspace"):
    selected = NodeAdmissionPlacement("server", node, workspace, "principal", "server-project", 1)
    record = store.build_record(
        execution_profile_id=profile, prompt_body="hello", node_placement=selected.to_record_mapping(),
    )
    store.write_record(root, record)
    return record, selected


def enqueue(manager, root, pair, runner, *, policy=None):
    record, selected = pair
    return manager.enqueue_node(
        root, record, placement=selected,
        policy=policy or queue_mod.NodeQueuePolicy(record["execution-profile-id"], "generation", "digest", 8),
        runner=runner, dispatch_owner_epoch="owner", dispatch_service_root=root.parent / "service",
    )


def finish(root, record):
    return store.transition_record(root, record["request-id"], "completed")


def test_node_bypasses_local_profiles_instances_and_physical_binding(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("node scheduling entered local provider/profile resolution or physical binding")
    monkeypatch.setattr(queue_mod.profiles_mod, "snapshot_from_record", forbidden)
    monkeypatch.setattr(queue_mod.profiles_mod, "get_snapshot_validator", forbidden)
    monkeypatch.setattr(store, "bind_and_start_owned_attempt", forbidden)
    monkeypatch.setattr("audiagentic.components.agents.gateway.instances.resolve_instance_facts", forbidden)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    pair = node_record(tmp_path)
    observed = []
    def runner(root, record):
        observed.append(record)
        assert record["worker-id"] and record["attempt-epoch"] == 1
        assert record["state"] == "running"
        for key in ("resolved-source-id", "resolved-model-id", "resolved-capacity-generation"):
            assert record.get(key) is None
        return finish(root, record)
    enqueue(manager, tmp_path, pair, runner)
    assert manager.wait(tmp_path, pair[0]["request-id"], 3)["state"] == "completed"
    assert len(observed) == 1
    status = manager.source_capacity_status()["node:server:node"]
    assert status["in-flight"]["node:server:node"] == 0


def test_same_node_cross_profiles_and_workspaces_share_one_slot(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    manager = queue_mod.GatewayQueueManager(node_project_roots=(a, b), node_server_id="server")
    hold, started, next_started = threading.Event(), threading.Event(), threading.Event()
    first = node_record(a)
    second = node_record(b, profile="other", workspace="other-workspace")
    def runner(root, record):
        started.set()
        assert hold.wait(3)
        return finish(root, record)
    try:
        enqueue(manager, a, first, runner)
        assert started.wait(3)
        enqueue(manager, b, second, lambda root, record: (next_started.set(), finish(root, record))[1])
        assert manager.request_slot_status("other", second[0]["request-id"]) == "pending"
        assert not next_started.is_set()
        assert manager.queue_depth("other")["pending"] == 1
        assert manager.project_queue_depths(b)["other"]["pending"] == 1
    finally:
        hold.set()
    assert next_started.wait(3)
    assert manager.wait(b, second[0]["request-id"], 3)["state"] == "completed"


def test_different_nodes_can_run_and_pending_cancel_uses_shared_authority(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    manager = queue_mod.GatewayQueueManager(node_project_roots=(a, b), node_server_id="server")
    hold, first_started, second_started = threading.Event(), threading.Event(), threading.Event()
    def runner(event):
        def run(root, record):
            event.set()
            assert hold.wait(3)
            return finish(root, record)
        return run
    first, second, cancelled = node_record(a), node_record(b, node="other"), node_record(a)
    try:
        enqueue(manager, a, first, runner(first_started))
        enqueue(manager, b, second, runner(second_started))
        assert first_started.wait(3) and second_started.wait(3)
        enqueue(manager, a, cancelled, lambda *_: pytest.fail("cancelled pending runner called"))
        assert manager.cancel(a, "profile", cancelled[0]["request-id"])["state"] == "cancelled"
        assert manager.request_slot_status("profile", cancelled[0]["request-id"]) is None
    finally:
        hold.set()
    for root, pair in ((a, first), (b, second)):
        manager.wait(root, pair[0]["request-id"], 3)


@pytest.mark.parametrize("stage", [None, "effect-intent", "native-accepted"])
def test_uncertain_effect_holds_after_outer_timeout_and_new_manager(tmp_path, stage):
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    pair = node_record(tmp_path)
    def disconnected(root, record):
        record = authorize(root, bind(root, record))
        if stage:
            record = apply(root, record, receipt(identity(record), 1, stage))
        return store.transition_record(root, record["request-id"], "failed")
    enqueue(manager, tmp_path, pair, disconnected)
    assert manager.wait(tmp_path, pair[0]["request-id"], 3)["state"] == "failed"
    assert manager.source_capacity_status()["node:server:node"]["in-flight"]["node:server:node"] == 1
    successor = node_record(tmp_path, profile="other")
    new_manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    called = threading.Event()
    enqueue(new_manager, tmp_path, successor, lambda root, record: (called.set(), finish(root, record))[1])
    assert not called.is_set()
    assert new_manager.request_slot_status("other", successor[0]["request-id"]) == "pending"
    current = store.read_record(tmp_path, pair[0]["request-id"])
    current = apply(tmp_path, current, receipt(identity(current), 2, "terminal", "a" * 64))
    for _ in range(2):
        manager._drain_all()
        new_manager._drain_all()
    assert called.wait(3)
    assert new_manager.wait(tmp_path, successor[0]["request-id"], 3)["state"] == "completed"
    assert manager.source_capacity_status()["node:server:node"]["in-flight"]["node:server:node"] == 0


def test_mixed_local_node_project_fifo_and_fair_rotation(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    manager = queue_mod.GatewayQueueManager(node_project_roots=(a, b), node_server_id="server")
    drain = manager._drain_all
    monkeypatch.setattr(manager, "_drain_all", lambda: None)
    order, started = [], {name: threading.Event() for name in ("a-local", "b-node", "a-node", "b-local")}
    releases = {name: threading.Event() for name in started}
    def runner(name):
        def run(root, record):
            order.append(name)
            started[name].set()
            assert releases[name].wait(5)
            return finish(root, record)
        return run
    records = []
    for root, name, is_node in ((a, "a-local", False), (a, "a-node", True), (b, "b-node", True), (b, "b-local", False)):
        if is_node:
            pair = node_record(root, profile="node-profile", node=name)
            enqueue(manager, root, pair, runner(name), policy=queue_mod.NodeQueuePolicy("node-profile", "g", "d", 8, global_capacity=1))
            record = pair[0]
        else:
            record = store.build_record(execution_profile_id="local-profile", prompt_body="x")
            store.write_record(root, record)
            manager.enqueue(root, record, {"global-capacity": 1}, runner(name))
        records.append((root, record))
    monkeypatch.setattr(manager, "_drain_all", drain)
    try:
        drain()
        for name in ("a-local", "b-node", "a-node", "b-local"):
            assert started[name].wait(3)
            assert order[-1] == name
            releases[name].set()
    finally:
        for release in releases.values():
            release.set()
    for root, record in records:
        assert manager.wait(root, record["request-id"], 3)["state"] == "completed"
    assert order == ["a-local", "b-node", "a-node", "b-local"]


@pytest.mark.parametrize("change", [
    {"server_id": "other"}, {"node_id": "other"}, {"workspace_id": "other"},
    {"principal_id": "other"}, {"server_project_id": "other"}, {"grant_revision": 2},
])
def test_node_queue_refuses_unconfigured_root_or_changed_placement(tmp_path, change):
    pair = node_record(tmp_path)
    manager = queue_mod.GatewayQueueManager()
    with pytest.raises(ValueError, match="outside configured"):
        enqueue(manager, tmp_path, pair, finish)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    with pytest.raises(ValueError, match="canonical admission"):
        enqueue(manager, tmp_path, (pair[0], replace(pair[1], **change)), finish)


@pytest.mark.parametrize("scope", ["global", "project"])
def test_local_and_node_share_capacity_overlays(tmp_path, scope):
    a, b = tmp_path / "a", tmp_path / "b"
    manager = queue_mod.GatewayQueueManager(node_project_roots=(a, b), node_server_id="server")
    hold, local_started, node_started = threading.Event(), threading.Event(), threading.Event()
    local = store.build_record(execution_profile_id="local-profile", prompt_body="x")
    store.write_record(a, local)
    def local_runner(root, record):
        local_started.set()
        assert hold.wait(5)
        return finish(root, record)
    policy = queue_mod.NodeQueuePolicy(
        "node-profile", "g", "d", 8,
        global_capacity=1 if scope == "global" else None,
        project_capacity=1 if scope == "project" else None,
    )
    params = {"global-capacity": 1} if scope == "global" else {
        "global-capacity": "unlimited", "project-capacity": 1,
    }
    # Global scope blocks across roots; project scope blocks on the same root.
    target = b if scope == "global" else a
    pending = node_record(target, profile="node-profile")
    try:
        manager.enqueue(a, local, params, local_runner)
        assert local_started.wait(3)
        enqueue(manager, target, pending, lambda root, record: (node_started.set(), finish(root, record))[1], policy=policy)
        assert manager.request_slot_status("node-profile", pending[0]["request-id"]) == "pending"
        assert not node_started.is_set()
        if scope == "project":
            independent = node_record(b, profile="node-profile", node="other")
            enqueue(manager, b, independent, finish, policy=policy)
            assert manager.wait(b, independent[0]["request-id"], 3)["state"] == "completed"
    finally:
        hold.set()
    assert node_started.wait(3)
    assert manager.wait(target, pending[0]["request-id"], 3)["state"] == "completed"
    manager.wait(a, local["request-id"], 3)


def test_pending_limit_and_running_cancel_do_not_interrupt_local_runtime(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("node cancellation must not signal a local provider session")
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions.peek_session_runtime", forbidden,
    )
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    hold, started = threading.Event(), threading.Event()
    first, pending, rejected = (node_record(tmp_path) for _ in range(3))
    policy = queue_mod.NodeQueuePolicy("profile", "generation", "digest", 1)
    def run(root, record):
        started.set()
        assert hold.wait(3)
        return finish(root, record)
    try:
        enqueue(manager, tmp_path, first, run, policy=policy)
        assert started.wait(3)
        enqueue(manager, tmp_path, pending, finish, policy=policy)
        result = enqueue(manager, tmp_path, rejected, finish, policy=policy)
        assert result["state"] == "rejected" and result["error"]["code"] == "VAL-AGW-025"
        result = manager.cancel(tmp_path, "profile", first[0]["request-id"])
        assert result["state"] == "running" and result["cancel-requested"]
    finally:
        hold.set()
    assert manager.wait(tmp_path, pending[0]["request-id"], 3)["state"] == "completed"


def test_incomplete_or_stale_snapshot_cannot_release_a_retained_slot(tmp_path):
    from audiagentic.components.agents.gateway.node.occupancy import NodeOccupancySnapshot

    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    pair = node_record(tmp_path)
    def disconnected(root, record):
        authorize(root, bind(root, record))
        raise ConnectionError("lost transport after authorization")
    enqueue(manager, tmp_path, pair, disconnected)
    assert manager.wait(tmp_path, pair[0]["request-id"], 1)["state"] == "running"
    manager._release_resolved_node_reservations(NodeOccupancySnapshot())
    assert manager.source_capacity_status()["node:server:node"]["in-flight"]["node:server:node"] == 1


def test_recovered_queued_owner_with_null_command_progresses(tmp_path):
    pair = node_record(tmp_path)
    claimed = store.claim_dispatch(
        tmp_path, pair[0]["request-id"], owner_epoch="owner", expected_revision=0,
    )
    assert claimed["state"] == "queued" and claimed["dispatch-owner-epoch"] == "owner"
    assert claimed["node-dispatch"] is None
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    calls = []
    def runner(root, record):
        calls.append(record["attempt-epoch"])
        return finish(root, record)
    enqueue(manager, tmp_path, pair, runner)
    assert manager.wait(tmp_path, pair[0]["request-id"], 3)["state"] == "completed"
    assert calls == [1]


def test_bound_authorized_command_rejects_fresh_attempt_and_blocks_other_request(tmp_path, monkeypatch):
    from audiagentic.components.agents.agents_paths import gateway_request_path

    from .test_gateway_node_occupancy import running_record

    current = authorize(tmp_path, bind(tmp_path, running_record(tmp_path)))
    selected = NodeAdmissionPlacement("server", "node", "workspace", "principal", "server-project", 1)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    before = gateway_request_path(tmp_path, current["request-id"]).read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("bound recovery cannot start a fresh attempt")
    monkeypatch.setattr(store, "start_owned_attempt", forbidden)
    with pytest.raises(ValueError, match="canonical admission"):
        enqueue(manager, tmp_path, (current, selected), forbidden)
    assert gateway_request_path(tmp_path, current["request-id"]).read_bytes() == before
    successor = node_record(tmp_path, profile="other")
    enqueue(manager, tmp_path, successor, forbidden)
    assert manager.request_slot_status("other", successor[0]["request-id"]) == "pending"
    assert manager.queue_depth("other")["pending"] == 1


def test_preparation_without_command_does_not_leak_reservation_after_runner_exit(tmp_path):
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    first, second = node_record(tmp_path), node_record(tmp_path, profile="other")
    enqueue(manager, tmp_path, first, lambda root, record: record)
    enqueue(manager, tmp_path, second, finish)
    assert manager.wait(tmp_path, second[0]["request-id"], 3)["state"] == "completed"
    assert store.read_record(tmp_path, first[0]["request-id"])["node-dispatch"] is None


def recoverable(root, *, bound=True, cancel=False):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    from .test_gateway_node_occupancy import running_record

    record = running_record(root)
    if bound:
        record = authorize(root, bind(root, record))
    if cancel:
        record = store.cancel_queued_or_mark_requested(root, record["request-id"])
    return store.defer_owned_recovery(
        root, record["request-id"], owner_epoch="owner", worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"], error=conflict(1, "Node unavailable"),
        phase="node-runtime-unavailable", side_effect_state="may-have-started" if bound else "not-started",
        retry_delay_seconds=None,
    )


def recover_enqueue(manager, root, record, runner):
    return manager.enqueue_recovered_node(
        root, record,
        placement=NodeAdmissionPlacement("server", "node", "workspace", "principal", "server-project", 1),
        policy=queue_mod.NodeQueuePolicy("profile", "generation", "digest", 8),
        runner=runner, dispatch_owner_epoch="owner", dispatch_service_root=root.parent / "service",
    )


def test_bound_observation_bypasses_blocked_project_head_without_replay(tmp_path, monkeypatch):
    current = recoverable(tmp_path, cancel=True)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    fresh = node_record(tmp_path, profile="other")
    enqueue(manager, tmp_path, fresh, finish)
    assert manager.request_slot_status("other", fresh[0]["request-id"]) == "pending"
    observed, hold = threading.Event(), threading.Event()
    calls = []

    def forbidden(*args, **kwargs):
        pytest.fail("bound observer must preserve the original attempt")

    monkeypatch.setattr(store, "start_owned_attempt", forbidden)

    def runner(root, record, *, reconcile_only=False):
        assert reconcile_only
        assert record["cancel-requested"]
        assert (record["worker-id"], record["attempt-epoch"]) == (current["worker-id"], current["attempt-epoch"])
        calls.append(record["request-id"])
        observed.set()
        assert hold.wait(3)
        return record

    try:
        recover_enqueue(manager, tmp_path, current, runner)
        assert observed.wait(3)
        recover_enqueue(manager, tmp_path, current, runner)
        assert len(calls) == 1
        assert manager.request_slot_status("other", fresh[0]["request-id"]) == "pending"
    finally:
        hold.set()
    manager.wait(tmp_path, current["request-id"], 3)
    assert store.read_record(tmp_path, current["request-id"])["state"] == "running"
    assert manager.source_capacity_status()["node-observer:server:node"]["in-flight"]["node-observer:server:node"] == 0
    assert manager.request_slot_status("other", fresh[0]["request-id"]) == "pending"


@pytest.mark.parametrize("bound", [False, True])
def test_node_deferred_recovery_persists_truth_without_synthetic_progress(tmp_path, bound):
    from audiagentic.components.agents.gateway.node.contracts import conflict
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred

    before = recoverable(tmp_path, bound=bound)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")

    def runner(root, record, **kwargs):
        assert bool(kwargs.get("reconcile_only")) is bound
        raise RecoveryDeferred(conflict(1, "Node disconnected"), phase="node-disconnected",
            side_effect_state="may-have-started" if bound else "not-started")

    recover_enqueue(manager, tmp_path, before, runner)
    manager.wait(tmp_path, before["request-id"], 3)
    after = store.read_record(tmp_path, before["request-id"])
    assert after["state"] == "running"
    assert after["recovery-required"]
    assert after["recovery"]["phase"] == "node-disconnected"
    assert after["recovery"]["next-retry-at"] is None
    assert after["worker-id"] == before["worker-id"]
    assert after["attempt-epoch"] == before["attempt-epoch"]
    assert after["node-dispatch"] == before["node-dispatch"]


def test_recovered_node_rejects_stale_owner(tmp_path):
    current = recoverable(tmp_path)
    current = {**current, "dispatch-owner-epoch": "other"}
    store.write_record(tmp_path, current)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    with pytest.raises(ValueError, match="canonical ownership"):
        recover_enqueue(manager, tmp_path, current, lambda *_: pytest.fail("stale owner ran"))


def test_receipt_settlement_allows_fresh_work_only_after_reconciliation(tmp_path):
    current = recoverable(tmp_path)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    fresh = node_record(tmp_path, profile="other")
    called = threading.Event()
    enqueue(manager, tmp_path, fresh, lambda root, record: (called.set(), finish(root, record))[1])
    assert not called.is_set()

    def runner(root, record, *, reconcile_only):
        assert reconcile_only
        settled = apply(root, record, receipt(identity(record), 1, "terminal", "a" * 64))
        return finish(root, settled)

    recover_enqueue(manager, tmp_path, current, runner)
    assert manager.wait(tmp_path, current["request-id"], 3)["state"] == "completed"
    assert called.wait(3)
    assert manager.wait(tmp_path, fresh[0]["request-id"], 3)["state"] == "completed"


def test_observers_share_one_bounded_slot_across_projects_and_duplicate_notifications(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    first, second = recoverable(a), recoverable(b)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(a, b), node_server_id="server")
    started, hold, next_started = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def run(root, record, *, reconcile_only):
        assert reconcile_only
        calls.append(record["request-id"])
        started.set()
        assert hold.wait(3)
        return record

    try:
        recover_enqueue(manager, a, first, run)
        assert started.wait(3)
        recover_enqueue(manager, b, second, lambda root, record, **kw: (next_started.set(), record)[1])
        recover_enqueue(manager, b, second, lambda *_: pytest.fail("duplicate pending observer ran"))
        assert not next_started.is_set()
        assert manager.request_slot_status("profile", second["request-id"]) == "pending"
    finally:
        hold.set()
    assert next_started.wait(3)
    assert len(calls) == 1


@pytest.mark.parametrize("domain", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
def test_node_observer_errors_preserve_effect_and_canonical_terminal_winner(tmp_path, domain, terminal):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    before = recoverable(tmp_path, cancel=True)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    def runner(root, record, **kwargs):
        if terminal:
            settled = apply(root, record, receipt(identity(record), 1, "terminal", "a" * 64))
            finish(root, settled)
        raise conflict(1, "PRIVATE exception content") if domain else RuntimeError("PRIVATE exception content")
    recover_enqueue(manager, tmp_path, before, runner)
    manager.wait(tmp_path, before["request-id"], 1)
    after = store.read_record(tmp_path, before["request-id"])
    assert after["state"] == ("completed" if terminal else "running")
    assert after["worker-id"] == before["worker-id"] and after["attempt-epoch"] == before["attempt-epoch"]
    assert after["node-dispatch"]["identity"] == before["node-dispatch"]["identity"]
    assert after["cancel-requested"]
    if not terminal:
        assert after["recovery"]["phase"] == "node-runner-error"
        assert after["recovery"]["next-retry-at"] is None
        assert "PRIVATE" not in str(after["recovery"])


@pytest.mark.parametrize("change", ["terminal", "owner", "placement", "recovery", "command"])
def test_pending_observer_discards_changed_canonical_identity(tmp_path, monkeypatch, change):
    current = recoverable(tmp_path)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    drain = manager._drain_all
    monkeypatch.setattr(manager, "_drain_all", lambda: None)
    recover_enqueue(manager, tmp_path, current, lambda *_ , **kw: pytest.fail("stale observer ran"))
    if change == "terminal":
        settled = apply(tmp_path, current, receipt(identity(current), 1, "terminal", "a" * 64))
        finish(tmp_path, settled)
    else:
        current = dict(current)
        if change == "owner":
            current["dispatch-owner-epoch"] = "other"
        elif change == "placement":
            current["node-placement"] = {**current["node-placement"], "workspace-id": "other"}
        elif change == "recovery":
            current["recovery-required"] = False
        else:
            current["node-dispatch"] = None
        store.write_record(tmp_path, current)
    monkeypatch.setattr(manager, "_drain_all", drain)
    drain()
    manager.wait(tmp_path, current["request-id"], 1)
    assert store.read_record(tmp_path, current["request-id"])["attempt-epoch"] == current["attempt-epoch"]


def test_node_recovery_claim_checks_revision_before_running_shortcut(tmp_path):
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    current = recoverable(tmp_path)
    with pytest.raises(AudiaGenticError, match="revision changed"):
        store.claim_dispatch(tmp_path, current["request-id"], owner_epoch="owner",
                             expected_revision=current["revision"] - 1)


def test_unclaimed_node_deferral_keeps_null_attempt_and_can_reenqueue(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.node.contracts import conflict

    pair = node_record(tmp_path)
    current = store.claim_dispatch(tmp_path, pair[0]["request-id"], owner_epoch="owner", expected_revision=0)
    current = store.defer_owned_queued_recovery(tmp_path, current["request-id"], owner_epoch="owner",
        worker_id=None, attempt_epoch=0, expected_revision=current["revision"],
        error=conflict(1, "Node unavailable"), phase="node-runtime-unavailable",
        side_effect_state="not-started", retry_delay_seconds=None)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    drain = manager._drain_all
    monkeypatch.setattr(manager, "_drain_all", lambda: None)
    recover_enqueue(manager, tmp_path, current, finish)
    entry = manager._pending_authority.get(current["request-id"]).value
    after = manager._defer_node(entry, current, conflict(1, "PRIVATE content"), phase="node-disconnected")
    assert after["state"] == "queued" and after["worker-id"] is None and after["attempt-epoch"] == 0
    assert after["recovery"]["next-retry-at"] is None
    assert "PRIVATE" not in str(after["recovery"])
    recover_enqueue(manager, tmp_path, after, finish)
    monkeypatch.setattr(manager, "_drain_all", drain)
    drain()
    assert manager.wait(tmp_path, current["request-id"], 3)["state"] == "completed"


def test_actual_queue_preserves_validated_node_failure_stage_without_private_details(tmp_path):
    from audiagentic.components.agents.gateway.diagnostics import ObservationPhase
    from audiagentic.components.agents.gateway.node.diagnostics import sanitize_node_error
    from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    before = recoverable(tmp_path)
    manager = queue_mod.GatewayQueueManager(node_project_roots=(tmp_path,), node_server_id="server")
    def runner(root, record, **kwargs):
        safe = sanitize_node_error(AudiaGenticError("IO-AGND-001", "agents-node", "PRIVATE raw error",
            {"stage": "retain-prepared", "reason-code": "prepared-evidence-unavailable", "payload": "PRIVATE"}))
        raise RecoveryDeferred(safe, phase=ObservationPhase.PRE_SUBMIT, side_effect_state="not-started")
    recover_enqueue(manager, tmp_path, before, runner)
    manager.wait(tmp_path, before["request-id"], 1)
    after = store.read_record(tmp_path, before["request-id"])
    assert after["state"] == "running"
    assert after["recovery"]["last-error-code"] == "IO-AGND-001"
    assert after["recovery"]["last-error-details"] == {
        "stage": "retain-prepared", "reason-code": "prepared-evidence-unavailable", "phase": "pre-submit",
    }
    assert after["recovery"]["side-effect-state"] == "may-have-started"
    assert "PRIVATE" not in str(after["recovery"])
