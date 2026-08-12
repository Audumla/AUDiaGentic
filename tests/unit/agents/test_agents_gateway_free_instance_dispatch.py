"""AS105/AS101 validation: free-instance dispatch against gated model-sources
sources -- multi-instance binding, structural over-subscription-impossibility,
overlapping profile sets, and the drain-before-swap anti-starvation guard.

Uses GatewayQueueManager directly with synthetic records (bypassing real
admission) -- consistent with this repo's existing queue-mechanics test
pattern (test_agents_gateway_queue.py).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import profiles as profiles_mod
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import queue as queue_mod
from audiagentic.foundation.time import now_iso_z


@pytest.fixture()
def home(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(home_dir))
    return home_dir


def _add_source(source_id: str, *, resource_id: str, concurrency: int, model_id: str | None = None) -> None:
    from audiagentic.components.providers import providers_api

    providers_api.model_source_add_global(
        source_id,
        {
            "source-class": "local-endpoint",
            "connector": "openai-compatible",
            "base-url": "http://127.0.0.1:9/v1",
            "model-id": model_id or source_id,
            "resource-id": resource_id,
            "concurrency": concurrency,
        },
    )


def _snapshot_for(project_root: Path, profile_id: str, instances: tuple[str, ...]) -> profiles_mod.ResolvedExecutionProfile:
    return profiles_mod.snapshot_from_resolved_profile(
        profile_id=profile_id, provider_id="local", instances=instances, params={},
    )


def _enqueue_snapshot(
    manager: queue_mod.GatewayQueueManager,
    project_root: Path,
    snapshot: profiles_mod.ResolvedExecutionProfile,
    runner,
    *,
    prompt: str = "x",
) -> dict:
    record = store.build_record(
        execution_profile_id=snapshot.profile_id,
        prompt_body=prompt,
        gateway_profile_id=snapshot.profile_id,
        gateway_profile_generation=snapshot.generation,
        gateway_profile_config_digest=snapshot.config_digest,
        resolved_provider_id=snapshot.provider_id,
        resolved_instance_ids=list(snapshot.instances),
    )
    store.write_record(project_root, record)
    return manager.enqueue(project_root, record, {}, runner)


def _blocking_runner(hold: threading.Event, started_counter: list, lock: threading.Lock):
    def runner(project_root: Path, record: dict) -> dict:
        with lock:
            started_counter.append(record.get("resolved-model-id"))
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )
    return runner


def test_same_model_two_instances_dispatches_to_whichever_is_free(tmp_path, home):
    """AS105's motivating scenario: the same underlying model loaded on two
    GPUs (m27b1, m27b2) as distinct instances -- a profile naming both
    dispatches to whichever has spare capacity."""
    _add_source("m27b1", resource_id="local-gpu-0", concurrency=1, model_id="qwen3-27b")
    _add_source("m27b2", resource_id="local-gpu-1", concurrency=1, model_id="qwen3-27b")

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started: list = []
    lock = threading.Lock()
    runner = _blocking_runner(hold, started, lock)

    snapshot = _snapshot_for(tmp_path, "dual-instance", ("m27b1", "m27b2"))

    t1 = threading.Thread(target=_enqueue_snapshot, args=(manager, tmp_path, snapshot, runner))
    t2 = threading.Thread(target=_enqueue_snapshot, args=(manager, tmp_path, snapshot, runner))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    deadline = time.monotonic() + 2
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)

    # Both requests dispatched -- one to each instance, both instances free
    # simultaneously (concurrency=1 each, two distinct resource-ids).
    assert len(started) == 2
    assert set(started) == {"qwen3-27b"}

    hold.set()


def test_over_subscription_structurally_impossible(tmp_path, home):
    """Three requests against a profile naming two concurrency=1 instances:
    exactly two ever run at once, never three -- capacity is measured, not
    configured, so there is no limit that could be set wrong."""
    _add_source("m27b1", resource_id="local-gpu-0", concurrency=1)
    _add_source("m27b2", resource_id="local-gpu-1", concurrency=1)

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started: list = []
    lock = threading.Lock()
    runner = _blocking_runner(hold, started, lock)

    snapshot = _snapshot_for(tmp_path, "over-sub", ("m27b1", "m27b2"))

    threads = [
        threading.Thread(target=_enqueue_snapshot, args=(manager, tmp_path, snapshot, runner))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    deadline = time.monotonic() + 2
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.2)  # give a would-be third dispatch a chance to (wrongly) start

    assert len(started) == 2, f"expected exactly 2 concurrent dispatches, got {len(started)}"

    hold.set()


def test_overlapping_instance_sets_share_capacity_correctly(tmp_path, home):
    """Two profiles with overlapping instance sets (A: [x,y], B: [y,z]) --
    y admits work up to its own limit regardless of which profile wanted it."""
    _add_source("x", resource_id="res-x", concurrency=1)
    _add_source("y", resource_id="res-y", concurrency=1)
    _add_source("z", resource_id="res-z", concurrency=1)

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started: list = []
    lock = threading.Lock()
    runner = _blocking_runner(hold, started, lock)

    snap_a = _snapshot_for(tmp_path, "profile-a", ("x", "y"))
    snap_b = _snapshot_for(tmp_path, "profile-b", ("y", "z"))

    # Saturate y first via profile A alone (only x and y available to A,
    # y has room, x has room -- both could take it; run x and y to capacity).
    threads = [
        threading.Thread(target=_enqueue_snapshot, args=(manager, tmp_path, snap_a, runner)),
        threading.Thread(target=_enqueue_snapshot, args=(manager, tmp_path, snap_a, runner)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    deadline = time.monotonic() + 2
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(started) == 2  # x and y both now full (concurrency=1 each)

    # Profile B wants y or z. y is full; z is free -- B must land on z.
    _enqueue_snapshot(manager, tmp_path, snap_b, runner)
    deadline = time.monotonic() + 2
    while len(started) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert len(started) == 3, "profile B should have dispatched to the free instance z"

    hold.set()


def test_drain_before_swap_anti_starvation_guard(tmp_path, home, monkeypatch):
    """A resource shared by two sources (llama-swap style): steady same-source
    load must not starve a different-source request forever -- the bounded
    guard eventually forces a drain-and-swap."""
    from audiagentic.components.agents.gateway.queue import queue as queue_module

    # Shrink the starvation threshold so the test doesn't need to wait 30s.
    monkeypatch.setattr(queue_module, "_STARVATION_THRESHOLD_SECONDS", 0.05)

    _add_source("model-a", resource_id="swap-host", concurrency=1)
    _add_source("model-b", resource_id="swap-host", concurrency=1)

    manager = queue_mod.GatewayQueueManager()
    started_b = threading.Event()

    def runner_a(project_root: Path, record: dict) -> dict:
        # Keep resubmitting model-a work in the background to simulate
        # steady same-source load, until model-b has been dispatched.
        while not started_b.is_set():
            time.sleep(0.01)
            snap_a = _snapshot_for(project_root, "swap-profile-a", ("model-a",))
            _enqueue_snapshot(manager, project_root, snap_a, runner_a, prompt="more-a")
            break  # one resubmission is enough to keep a pending contender alive
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    def runner_b(project_root: Path, record: dict) -> dict:
        started_b.set()
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    snap_a = _snapshot_for(tmp_path, "swap-profile-a", ("model-a",))
    snap_b = _snapshot_for(tmp_path, "swap-profile-b", ("model-b",))

    # First model-a request occupies the resource.
    _enqueue_snapshot(manager, tmp_path, snap_a, runner_a, prompt="a1")
    # model-b request contends for the same resource, currently active on a.
    _enqueue_snapshot(manager, tmp_path, snap_b, runner_b, prompt="b1")

    assert started_b.wait(timeout=5), "model-b was starved past the anti-starvation threshold"


def test_pending_project_head_blocked_on_capacity_does_not_block_another_project(tmp_path, home):
    """AS101: one pending authority selects fair project heads across modes.

    A gated request whose physical source is saturated must not prevent an
    unrelated, ungated project head from being dispatched.
    """
    _add_source("gated", resource_id="gpu-0", concurrency=1)
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started: list[str] = []
    lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        with lock:
            started.append(record["execution-profile-id"])
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    gated = _snapshot_for(tmp_path, "gated-profile", ("gated",))
    ungated = _snapshot_for(tmp_path, "ungated-profile", ("plain-model",))
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    _enqueue_snapshot(manager, project_a, gated, runner, prompt="occupy")
    deadline = time.monotonic() + 2
    while len(started) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started == ["gated-profile"]

    _enqueue_snapshot(manager, project_a, gated, runner, prompt="blocked")
    _enqueue_snapshot(manager, project_b, ungated, runner, prompt="ready")
    deadline = time.monotonic() + 2
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert set(started) == {"gated-profile", "ungated-profile"}
    assert manager.queue_depth("gated-profile")["pending"] == 1
    hold.set()


def test_mixed_declared_and_plain_instances_use_one_placement_contract(tmp_path, home):
    """AS101: a profile may mix bounded and unbounded source candidates."""
    _add_source("bounded", resource_id="gpu-0", concurrency=1, model_id="bounded-model")
    manager = queue_mod.GatewayQueueManager()
    snapshot = _snapshot_for(tmp_path, "mixed-profile", ("bounded", "plain-model"))
    record = _enqueue_snapshot(
        manager,
        tmp_path,
        snapshot,
        lambda root, item: store.transition_record(
            root, item["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        ),
    )
    finished = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert finished["state"] == "completed"
    # AS101: even an un-declared/plain candidate must be durably bound under
    # the same admission fence as a resource-backed source.  This prevents a
    # restarted gateway from losing the exact placement used by the runner.
    assert finished["resolved-source-id"] in {"bounded", "plain-model"}
    assert finished["resolved-model-id"]
