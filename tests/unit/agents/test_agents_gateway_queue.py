"""Unit tests for agents_gateway_queue — FIFO ordering, per-profile
concurrency, cancel, wait, and queue-full rejection (AG09), using a
deterministic fake runner (no real provider dispatch)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import gateway_timeline_path
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import queue as queue_mod
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.time import now_iso_z


@pytest.fixture(autouse=True)
def _fresh_event_bus():
    """Fresh bus per test; teardown restores an open bus so import-time
    observer subscriptions (memory, ledger, providers) survive this module."""
    from audiagentic.foundation.event import event_bus as event_bus_mod

    saved_config = event_bus_mod._bus_instance.config if event_bus_mod._bus_instance else None
    reset_bus()
    yield
    # Don't restore the old bus — reset_bus() closed it. Create a fresh open one.
    reset_bus(config=saved_config)


def _submit(manager: queue_mod.GatewayQueueManager, tmp_path: Path, profile_id: str, params: dict, runner) -> dict:
    record = store.build_record(execution_profile_id=profile_id, prompt_body="x")
    store.write_record(tmp_path, record)
    return manager.enqueue(tmp_path, record, params, runner)


def _blocking_runner(hold: threading.Event, started: threading.Event | None = None):
    def runner(project_root: Path, record: dict) -> dict:
        if started is not None:
            started.set()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )
    return runner


def _immediate_runner(project_root: Path, record: dict) -> dict:
    return store.transition_record(
        project_root, record["request-id"], "completed",
        updates={"output": "done", "finished-at": now_iso_z()},
    )


def _failing_runner(project_root: Path, record: dict) -> dict:
    raise AudiaGenticError(code="EXT-FAKE-001", kind="providers", message="boom")


# ---------------------------------------------------------------------------
# param resolution
# ---------------------------------------------------------------------------

def test_resolve_max_concurrency_default():
    assert queue_mod.resolve_max_concurrency({}) == 1


def test_resolve_max_concurrency_rejects_wrong_type():
    with pytest.raises(AudiaGenticError) as exc_info:
        queue_mod.resolve_max_concurrency({"max-concurrency": "two"})
    assert exc_info.value.code == "VAL-AGW-020"


def test_resolve_max_concurrency_rejects_below_minimum():
    with pytest.raises(AudiaGenticError) as exc_info:
        queue_mod.resolve_max_concurrency({"max-concurrency": 0})
    assert exc_info.value.code == "VAL-AGW-021"


def test_resolve_queue_max_size_default():
    assert queue_mod.resolve_queue_max_size({}, 1) == 8
    assert queue_mod.resolve_queue_max_size({}, 5) == 10


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------

def test_max_concurrency_one_serializes_requests(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)

    record1 = store.build_record(execution_profile_id="p1", prompt_body="a")
    store.write_record(tmp_path, record1)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record1, {"max-concurrency": 1}, runner))
    t.start()
    assert started.wait(timeout=2)

    depth = manager.queue_depth("p1")
    assert depth["running"] == 1

    record2 = store.build_record(execution_profile_id="p1", prompt_body="b")
    store.write_record(tmp_path, record2)
    manager.enqueue(tmp_path, record2, {"max-concurrency": 1}, runner)
    # second stays queued while first still holds
    assert store.read_record(tmp_path, record2["request-id"])["state"] == "queued"

    hold.set()
    t.join(timeout=5)
    result2 = manager.wait(tmp_path, record2["request-id"], timeout_seconds=5)
    assert result2["state"] == "completed"


def test_max_concurrency_two_runs_two_third_waits(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started_count = threading.Semaphore(0)

    def runner(project_root: Path, record: dict) -> dict:
        started_count.release()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    records = [store.build_record(execution_profile_id="p2", prompt_body=str(i)) for i in range(3)]
    for r in records:
        store.write_record(tmp_path, r)

    threads = [
        threading.Thread(target=manager.enqueue, args=(tmp_path, r, {"max-concurrency": 2}, runner))
        for r in records
    ]
    for t in threads:
        t.start()

    assert started_count.acquire(timeout=2)
    assert started_count.acquire(timeout=2)
    time.sleep(0.1)  # let the third settle into queued state
    depth = manager.queue_depth("p2")
    assert depth["running"] == 2
    assert depth["pending"] == 1
    assert store.read_record(tmp_path, records[2]["request-id"])["state"] == "queued"

    hold.set()
    for t in threads:
        t.join(timeout=5)
    for r in records:
        result = manager.wait(tmp_path, r["request-id"], timeout_seconds=5)
        assert result["state"] == "completed"


def test_session_workers_share_one_profile_compute_slot(tmp_path: Path):
    """AS15: waiting session turns progress without exceeding profile capacity."""
    manager = queue_mod.GatewayQueueManager()
    workers_entered = threading.Semaphore(0)
    allow_turn_start = threading.Event()
    release_compute = threading.Event()
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        nonlocal active, max_active
        workers_entered.release()
        allow_turn_start.wait(timeout=5)
        asyncio.run(queue_mod.notify_turn_starting(record["request-id"]))
        try:
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            release_compute.wait(timeout=5)
        finally:
            with active_lock:
                active -= 1
            asyncio.run(queue_mod.notify_turn_done(record["request-id"]))
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    records = [
        store.build_record(
            execution_profile_id="session-profile",
            prompt_body=str(index),
            session_id=f"session-{index}",
        )
        for index in range(2)
    ]
    for record in records:
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, {"max-concurrency": 1}, runner)

    assert workers_entered.acquire(timeout=2)
    assert workers_entered.acquire(timeout=2)
    assert manager.queue_depth("session-profile")["running"] == 2

    allow_turn_start.set()
    release_compute.set()
    for record in records:
        assert manager.wait(tmp_path, record["request-id"], timeout_seconds=5)["state"] == "completed"
    assert max_active == 1


def test_fifo_ordering(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    order: list[str] = []
    order_lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        with order_lock:
            order.append(record["request-id"])
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    first = store.build_record(execution_profile_id="p3", prompt_body="first")
    store.write_record(tmp_path, first)
    t1 = threading.Thread(target=manager.enqueue, args=(tmp_path, first, {"max-concurrency": 1}, runner))
    t1.start()
    time.sleep(0.05)  # ensure first claims the only slot before second/third submit

    second = store.build_record(execution_profile_id="p3", prompt_body="second")
    third = store.build_record(execution_profile_id="p3", prompt_body="third")
    store.write_record(tmp_path, second)
    store.write_record(tmp_path, third)
    manager.enqueue(tmp_path, second, {"max-concurrency": 1}, runner)
    t3 = threading.Thread(target=manager.enqueue, args=(tmp_path, third, {"max-concurrency": 1}, runner))
    t3.start()
    time.sleep(0.05)

    hold.set()
    t1.join(timeout=5)
    t3.join(timeout=5)
    for r in (first, second, third):
        manager.wait(tmp_path, r["request-id"], timeout_seconds=5)

    assert order == [first["request-id"], second["request-id"], third["request-id"]]


# ---------------------------------------------------------------------------
# queue full / cancel / wait / failure
# ---------------------------------------------------------------------------

def test_queue_full_rejects(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    running = store.build_record(execution_profile_id="p4", prompt_body="running")
    store.write_record(tmp_path, running)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"max-concurrency": 1, "queue-max-size": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(execution_profile_id="p4", prompt_body="queued")
    store.write_record(tmp_path, queued)
    manager.enqueue(tmp_path, queued, {"max-concurrency": 1, "queue-max-size": 1}, runner)

    overflow = store.build_record(execution_profile_id="p4", prompt_body="overflow")
    store.write_record(tmp_path, overflow)
    result = manager.enqueue(tmp_path, overflow, {"max-concurrency": 1, "queue-max-size": 1}, runner)

    assert result["state"] == "rejected"
    assert "queue full" in result["error"]["message"]

    hold.set()
    t.join(timeout=5)
    manager.wait(tmp_path, queued["request-id"], timeout_seconds=5)


def test_cancel_queued_request(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    running = store.build_record(execution_profile_id="p5", prompt_body="running")
    store.write_record(tmp_path, running)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"max-concurrency": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(execution_profile_id="p5", prompt_body="queued")
    store.write_record(tmp_path, queued)
    manager.enqueue(tmp_path, queued, {"max-concurrency": 1}, runner)

    cancelled = manager.cancel(tmp_path, "p5", queued["request-id"])
    assert cancelled["state"] == "cancelled"

    hold.set()
    t.join(timeout=5)


def test_cancel_running_request_persists_cancel_requested_flag(tmp_path: Path):
    """RV22 HIGH: cancel intent against a running request must be observable
    on the persisted record, not just held in the queue manager's memory."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)

    record = store.build_record(execution_profile_id="p9", prompt_body="x")
    store.write_record(tmp_path, record)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"max-concurrency": 1}, runner))
    t.start()
    assert started.wait(timeout=2)

    result = manager.cancel(tmp_path, "p9", record["request-id"])
    assert result["state"] == "running"  # not force-terminated
    assert result["cancel-requested"] is True

    fetched = store.read_record(tmp_path, record["request-id"])
    assert fetched["cancel-requested"] is True

    hold.set()
    t.join(timeout=5)


def test_cancel_running_request_completion_still_wins(tmp_path: Path):
    """RV22 MEDIUM: if the runner finishes normally despite a cancel request
    (no cooperative check inside it), the actual terminal state must be
    reported honestly — not silently overridden to 'cancelled'."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)

    record = store.build_record(execution_profile_id="p10", prompt_body="x")
    store.write_record(tmp_path, record)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"max-concurrency": 1}, runner))
    t.start()
    assert started.wait(timeout=2)

    manager.cancel(tmp_path, "p10", record["request-id"])
    hold.set()
    t.join(timeout=5)

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"
    assert result["cancel-requested"] is True  # intent preserved even though it didn't take effect
    t.join(timeout=5)


def test_wait_times_out_for_long_running(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    record = store.build_record(execution_profile_id="p6", prompt_body="x")
    store.write_record(tmp_path, record)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"max-concurrency": 1}, runner))
    t.start()

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=0.2)
    assert result["state"] == "running"

    hold.set()
    t.join(timeout=5)


def test_cancel_after_dequeue_before_claim_is_terminal_not_stranded(tmp_path: Path, monkeypatch):
    """RV677: durable cancellation wins the queue-to-claim hand-off race."""
    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p5-race", prompt_body="queued")
    store.write_record(tmp_path, record)
    claim_entered = threading.Event()
    release_claim = threading.Event()
    original_claim = store.claim_dispatch

    def paused_claim(*args, **kwargs):
        claim_entered.set()
        assert release_claim.wait(timeout=5)
        return original_claim(*args, **kwargs)

    monkeypatch.setattr(queue_mod.store, "claim_dispatch", paused_claim)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _immediate_runner)
    assert claim_entered.wait(timeout=2)

    cancelled = manager.cancel(tmp_path, "p5-race", record["request-id"])
    assert cancelled["state"] == "cancelled"
    release_claim.set()
    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)

    assert result["state"] == "cancelled"
    assert manager.queue_depth("p5-race")["pending"] == 0
    # Terminal state is durable before the worker thread's ``finally`` block
    # removes its in-memory slot.  Wait for that cleanup explicitly rather
    # than asserting an incidental scheduling order.
    deadline = time.monotonic() + 2
    while manager.queue_depth("p5-race")["running"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.queue_depth("p5-race")["running"] == 0


def test_wait_uses_bounded_full_read_fallback_for_unchanged_record(tmp_path: Path, monkeypatch):
    """RV639: an unchanged durable record must not be parsed every 50ms."""
    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p6", prompt_body="x")
    store.write_record(tmp_path, record)

    original_read = store.read_record
    read_count = 0

    def _counting_read(project_root: Path, request_id: str) -> dict:
        nonlocal read_count
        read_count += 1
        return original_read(project_root, request_id)

    clock = [0.0]

    def _monotonic() -> float:
        return clock[0]

    def _sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(queue_mod.store, "read_record", _counting_read)
    monkeypatch.setattr(queue_mod.time, "monotonic", _monotonic)
    monkeypatch.setattr(queue_mod.time, "sleep", _sleep)

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=0.9)

    assert result["state"] == "queued"
    # Initial validation plus one 500ms safety refresh; the former 50ms loop
    # would have required nineteen full record reads for this timeout.
    assert read_count == 2


def test_wait_observes_terminal_write_from_independent_process(tmp_path: Path, monkeypatch):
    """The mtime/size hint keeps a local waiter correct for an external writer."""
    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p6", prompt_body="x")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")

    initial_observation = threading.Event()
    original_signature = queue_mod._record_signature

    def _observed_signature(path: Path):
        signature = original_signature(path)
        initial_observation.set()
        return signature

    monkeypatch.setattr(queue_mod, "_record_signature", _observed_signature)
    result: dict[str, dict] = {}
    waiter = threading.Thread(
        target=lambda: result.setdefault(
            "record", manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
        ),
    )
    waiter.start()
    assert initial_observation.wait(timeout=2)

    writer_code = "\n".join((
        "import sys",
        "from pathlib import Path",
        "from audiagentic.components.agents.gateway import store as store",
        "from audiagentic.foundation.time import now_iso_z",
        "store.transition_record(Path(sys.argv[1]), sys.argv[2], 'completed', updates={'output': 'external', 'finished-at': now_iso_z()})",
    ))
    repo_root = Path(__file__).resolve().parents[3]
    source_root = repo_root / "src"
    subprocess_env = dict(os.environ)
    existing_pythonpath = subprocess_env.get("PYTHONPATH")
    subprocess_env["PYTHONPATH"] = (
        f"{source_root}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath else str(source_root)
    )
    completed = subprocess.run(
        [sys.executable, "-c", writer_code, str(tmp_path), record["request-id"]],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        cwd=repo_root,
        env=subprocess_env,
    )
    assert completed.returncode == 0, completed.stderr

    waiter.join(timeout=5)
    assert not waiter.is_alive()
    assert result["record"]["state"] == "completed"
    assert result["record"]["output"] == "external"


def test_wait_returns_completed_result(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p7", prompt_body="x")
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _immediate_runner)
    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"
    assert result["output"] == "done"
    events = [entry["event"] for entry in load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))]
    assert "queue.queued" in events
    assert "queue.started" in events
    assert "queue.finished" in events


def test_failing_runner_transitions_to_failed(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p8", prompt_body="x")
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _failing_runner)
    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "failed"
    assert result["error"]["code"] == "EXT-FAKE-001"


def test_terminal_lifecycle_event_carries_provider_and_attempt_info(tmp_path: Path):
    """RV31: an observer must be able to tell what happened from the
    lifecycle event alone, without reading record.json."""
    manager = queue_mod.GatewayQueueManager()
    received = []
    done = threading.Event()

    def on_completed(event_type, payload, metadata):
        received.append(payload)
        done.set()

    get_bus().subscribe("agents.execution.completed", on_completed)

    record = store.build_record(execution_profile_id="p11", prompt_body="x")
    store.write_record(tmp_path, record)

    def runner(project_root: Path, rec: dict) -> dict:
        store.append_attempt(
            project_root, rec["request-id"],
            execution_profile_id="p11", provider_id="local-openai", model_id="gpt-4o",
            state="completed", started_at=now_iso_z(),
        )
        return store.transition_record(
            project_root, rec["request-id"], "completed",
            updates={"output": "done", "provider-id": "local-openai", "model-id": "gpt-4o", "finished-at": now_iso_z()},
        )

    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, runner)
    assert done.wait(timeout=5)

    payload = received[0]
    assert payload["provider-id"] == "local-openai"
    assert payload["model-id"] == "gpt-4o"
    assert payload["attempt_count"] == 1
    assert payload["error"] is None


def test_lifecycle_event_publish_failure_does_not_crash_worker(tmp_path: Path, monkeypatch):
    """RV38: a misbehaving subscriber or a broken event bus must not prevent
    the request from reaching its real terminal state."""
    def _broken_publish(*args, **kwargs):
        raise RuntimeError("event bus is on fire")

    monkeypatch.setattr(get_bus(), "publish", _broken_publish)

    manager = queue_mod.GatewayQueueManager()
    record = store.build_record(execution_profile_id="p12", prompt_body="x")
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _immediate_runner)

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"


# ---------------------------------------------------------------------------
# AS16 immutable-snapshot / race invariants
# ---------------------------------------------------------------------------

def test_snapshot_invariants_under_concurrent_modifications(tmp_path: Path):
    """_snapshot_all returns internally consistent data even while profiles
    mutate concurrently: running >= idle, active_running == running - idle,
    active_running <= max_concurrency."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Semaphore(0)

    def runner(project_root: Path, record: dict) -> dict:
        started.release()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    # Two profiles, one running request each (max-concurrency 2 so both start)
    params = {"max-concurrency": 2}
    records = [
        store.build_record(execution_profile_id=f"pA{i}", prompt_body=str(i))
        for i in range(4)
    ]
    for r in records:
        store.write_record(tmp_path, r)

    threads = [
        threading.Thread(target=manager.enqueue, args=(tmp_path, r, params, runner))
        for r in records
    ]
    for t in threads:
        t.start()

    # Wait for all to start running
    for _ in range(4):
        assert started.acquire(timeout=2)

    # Rapidly take snapshots while state may change under concurrent turns
    invariant_violations = []
    for _ in range(50):
        snap = manager._snapshot_all()
        for pid, depth in snap.items():
            if depth["running"] < depth["idle"]:
                invariant_violations.append(f"{pid}: running({depth['running']}) < idle({depth['idle']})")
            if depth["active_running"] != depth["running"] - depth["idle"]:
                invariant_violations.append(
                    f"{pid}: active_running({depth['active_running']}) != running({depth['running']}) - idle({depth['idle']})"
                )
            if depth["active_running"] > depth["max_concurrency"]:
                invariant_violations.append(
                    f"{pid}: active_running({depth['active_running']}) > max_concurrency({depth['max_concurrency']})"
                )
            if depth["pending"] < 0:
                invariant_violations.append(f"{pid}: pending({depth['pending']}) < 0")

    hold.set()
    for t in threads:
        t.join(timeout=5)

    assert not invariant_violations, "Snapshot invariants violated:\n" + "\n".join(invariant_violations)


class TestGatewayLifecycleSuffixMap:
    """BU02 validation V6: suffix→topic map correctness and unknown-suffix safety."""

    def test_every_suffix_maps_to_registered_topic(self):
        """Every allowed suffix in the lifecycle map resolves to a registered agents-owned topic."""
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )

        mod._registry_instance = None
        load_all_event_topics()
        registry = get_topic_registry()

        for suffix, topic in queue_mod._LIFECYCLE_SUFFIX_TOPIC_MAP.items():
            assert registry.is_registered(topic), (
                f"Suffix {suffix!r} maps to {topic!r} which is not a registered topic"
            )

    def test_unknown_suffix_does_not_publish(self, tmp_path: Path):
        """Unknown lifecycle event suffix logs error and skips publish."""
        received = []

        def _track(topic, payload, metadata=None):
            received.append((topic, payload))

        bus = get_bus()
        bus.publish = _track  # type: ignore[method-assign]

        manager = queue_mod.GatewayQueueManager()
        record = store.build_record(execution_profile_id="p12", prompt_body="x")
        store.write_record(tmp_path, record)

        def _runner_with_unknown_suffix(project_root, rec):
            queue_mod._publish_lifecycle_event("unknown_suffix", rec)
            store.transition_record(
                project_root, rec["request-id"], "completed",
                updates={"output": "done", "finished-at": now_iso_z()},
            )
            return rec

        manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _runner_with_unknown_suffix)
        result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
        assert result["state"] == "completed"

        unknown_topics = [t for t, _ in received if "unknown" in t.lower()]
        assert not unknown_topics, (
            f"Unknown suffix produced unexpected publishes: {unknown_topics}"
        )


# ---------------------------------------------------------------------------
# AS16: immutable-snapshot / impossible-count race tests
# ---------------------------------------------------------------------------

def test_snapshot_invariants_idle_is_subset_of_running(tmp_path: Path):
    """Idle requests are always a subset of running — the snapshot must never show idle > running."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    # Enqueue 3 requests with max_concurrency=2; first two run immediately, third is pending.
    request_ids: list[str] = []
    for i in range(3):
        record = store.build_record(execution_profile_id="snap1", prompt_body=f"x{i}")
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, {"max-concurrency": 2}, runner)
        request_ids.append(record["request-id"])

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth("snap1")
        if depth["running"] == 2 and depth["pending"] == 1:
            break
        time.sleep(0.02)

    depth = manager.queue_depth("snap1")
    assert depth["running"] == 2, f"expected 2 running, got {depth}"
    assert depth["idle"] <= depth["running"], f"idle ({depth['idle']}) > running ({depth['running']})"
    assert depth["active_running"] == depth["running"] - depth["idle"]

    hold.set()
    for rid in request_ids:
        manager.wait(tmp_path, rid, timeout_seconds=5)


def test_snapshot_invariants_active_running_arithmetic(tmp_path: Path):
    """active_running = running - idle must hold from a single lock acquisition."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    profile_id = "snap2"
    for i in range(4):
        record = store.build_record(execution_profile_id=profile_id, prompt_body=f"x{i}")
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, {"max-concurrency": 3}, runner)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth(profile_id)
        if depth["running"] == 3 and depth["pending"] == 1:
            break
        time.sleep(0.02)

    # Take multiple snapshots under contention and verify invariants hold for each.
    for _ in range(20):
        depth = manager.queue_depth(profile_id)
        assert depth["active_running"] == depth["running"] - depth["idle"], (
            f"active_running ({depth['active_running']}) != running ({depth['running']}) - idle ({depth['idle']})"
        )
        assert depth["idle"] <= depth["running"], (
            f"idle ({depth['idle']}) > running ({depth['running']})"
        )
        assert depth["active_running"] >= 0, (
            f"negative active_running: {depth}"
        )

    hold.set()


def test_snapshot_no_impossible_slot_count(tmp_path: Path):
    """pending + running must never exceed queue_max_size + max_concurrency from one snapshot."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    profile_id = "snap3"
    params = {"max-concurrency": 2, "queue-max-size": 4}
    # Submit max_concurrency + queue_max_size = 6 requests; all admitted.
    for i in range(6):
        record = store.build_record(execution_profile_id=profile_id, prompt_body=f"x{i}")
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, params, runner)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth(profile_id)
        if depth["running"] == 2 and depth["pending"] == 4:
            break
        time.sleep(0.02)

    max_slots = params["max-concurrency"] + params["queue-max-size"]
    for _ in range(20):
        depth = manager.queue_depth(profile_id)
        total = depth["pending"] + depth["running"]
        assert total <= max_slots, (
            f"slot overflow: pending ({depth['pending']}) + running ({depth['running']}) = {total} > {max_slots}"
        )

    hold.set()


def test_snapshot_under_concurrent_completion(tmp_path: Path):
    """Snapshot invariants hold while requests complete concurrently with new enqueues."""
    manager = queue_mod.GatewayQueueManager()
    started = threading.Event()

    def _slow_runner(project_root: Path, record: dict) -> dict:
        started.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    profile_id = "snap4"
    params = {"max-concurrency": 2, "queue-max-size": 4}
    records = []
    for i in range(6):
        record = store.build_record(execution_profile_id=profile_id, prompt_body=f"x{i}")
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, params, _slow_runner)
        records.append(record)

    # Wait until first 2 are running.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth(profile_id)
        if depth["running"] == 2 and depth["pending"] == 4:
            break
        time.sleep(0.02)

    # Release the first batch, verify invariants throughout.
    started.set()
    for _ in range(30):
        depth = manager.queue_depth(profile_id)
        assert depth["active_running"] == depth["running"] - depth["idle"], (
            f"arithmetic invariant broken: {depth}"
        )
        assert depth["idle"] <= depth["running"], f"idle > running: {depth}"
        assert depth["pending"] + depth["running"] <= params["max-concurrency"] + params["queue-max-size"], (
            f"slot overflow: {depth}"
        )
        time.sleep(0.02)


def test_request_slot_status_consistent_with_snapshot(tmp_path: Path):
    """request_slot_status and queue_depth agree on the same request at one point."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    profile_id = "snap5"
    record = store.build_record(execution_profile_id=profile_id, prompt_body="x")
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, runner)

    request_id = record["request-id"]

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth(profile_id)
        if depth["running"] == 1:
            break
        time.sleep(0.02)

    slot = manager.request_slot_status(profile_id, request_id)
    depth = manager.queue_depth(profile_id)
    assert slot == "active", f"expected active slot for running non-idle, got {slot}"
    assert depth["running"] == 1 and depth["idle"] == 0 and depth["active_running"] == 1

    hold.set()


# ---------------------------------------------------------------------------
# SH07: per-request dispatch isolation
# ---------------------------------------------------------------------------

def test_sh07_per_request_dispatch_isolation(tmp_path: Path):
    """SH07: two requests on the same profile with max_concurrency=1 must not
    substitute caller context. Each runner receives its own project_root and
    its own record (distinct request-id)."""
    manager = queue_mod.GatewayQueueManager()
    hold_first = threading.Event()
    dispatch_log: list[tuple[Path, str]] = []
    log_lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        with log_lock:
            dispatch_log.append((project_root, record["request-id"]))
        hold_first.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    # Two distinct project roots
    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()

    profile_id = "sh07-profile"
    params = {"max-concurrency": 1}

    record_a = store.build_record(execution_profile_id=profile_id, prompt_body="prompt_a")
    store.write_record(root_a, record_a)
    # Enqueue A — it starts immediately (only slot)
    t1 = threading.Thread(
        target=manager.enqueue,
        args=(root_a, record_a, params, runner),
    )
    t1.start()
    time.sleep(0.1)  # let A claim the slot

    record_b = store.build_record(execution_profile_id=profile_id, prompt_body="prompt_b")
    store.write_record(root_b, record_b)
    # Enqueue B — it goes pending behind A
    manager.enqueue(root_b, record_b, params, runner)

    # Release A so B can run
    hold_first.set()
    t1.join(timeout=5)
    # Wait for B to complete
    result_b = manager.wait(root_b, record_b["request-id"], timeout_seconds=5)
    assert result_b["state"] == "completed"

    with log_lock:
        assert len(dispatch_log) == 2
        # First dispatch: A ran with root_a and record_a's ID
        assert dispatch_log[0] == (root_a, record_a["request-id"])
        # Second dispatch: B ran with root_b and record_b's ID
        assert dispatch_log[1] == (root_b, record_b["request-id"])


def test_sh07_cancel_pending_entry_with_two_entries(tmp_path: Path):
    """Cancel of a pending request removes the correct QueuedDispatch entry
    when two entries are pending in the same profile queue."""
    manager = queue_mod.GatewayQueueManager()
    hold_first = threading.Event()

    def runner(project_root: Path, record: dict) -> dict:
        hold_first.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    profile_id = "sh07-cancel"
    params = {"max-concurrency": 1}

    record_first = store.build_record(execution_profile_id=profile_id, prompt_body="first")
    store.write_record(tmp_path, record_first)

    t1 = threading.Thread(
        target=manager.enqueue,
        args=(tmp_path, record_first, params, runner),
    )
    t1.start()
    time.sleep(0.1)  # let first claim the slot

    record_second = store.build_record(execution_profile_id=profile_id, prompt_body="second")
    store.write_record(tmp_path, record_second)
    manager.enqueue(tmp_path, record_second, params, runner)

    time.sleep(0.1)  # let second settle into pending

    # Cancel the pending second request
    cancelled = manager.cancel(tmp_path, profile_id, record_second["request-id"])
    assert cancelled["state"] == "cancelled"

    # First should still be running; cancel of second must not have affected it
    depth = manager.queue_depth(profile_id)
    assert depth["pending"] == 0
    assert depth["running"] == 1

    hold_first.set()
    t1.join(timeout=5)

    result_first = manager.wait(tmp_path, record_first["request-id"], timeout_seconds=5)
    assert result_first["state"] == "completed"


# ---------------------------------------------------------------------------
# SH07 C2: lane-key isolation and public-id safety
# ---------------------------------------------------------------------------

def test_sh07c2_same_params_share_one_lane(tmp_path: Path):
    """Two projects with the same non-secret params share one global lane limit."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    # Same profile, same non-secret params → same snapshot digest → one lane
    base_params = {"max-concurrency": 2, "provider_id": "local", "model_id": "m"}

    snap_a = profiles_mod.snapshot_from_resolved_profile(
        profile_id="shared-profile",
        provider_id=base_params["provider_id"],
        model_id=base_params["model_id"],
        params=base_params,
    )
    snap_b = profiles_mod.snapshot_from_resolved_profile(
        profile_id="shared-profile",
        provider_id=base_params["provider_id"],
        model_id=base_params["model_id"],
        params=dict(base_params),  # fresh dict, same content
    )

    assert snap_a.config_digest == snap_b.config_digest
    assert snap_a.lane_key() == snap_b.lane_key()
    # Same lane key means one shared queue

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Semaphore(0)

    def runner(project_root: Path, record: dict) -> dict:
        started.release()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()

    # Enqueue from project A — takes one of two slots
    record_a = store.build_record(execution_profile_id="shared-profile", prompt_body="from_a")
    store.write_record(root_a, record_a)
    manager.enqueue(root_a, record_a, base_params, runner)

    # Enqueue from project B — takes second slot (same lane)
    record_b = store.build_record(execution_profile_id="shared-profile", prompt_body="from_b")
    store.write_record(root_b, record_b)
    manager.enqueue(root_b, record_b, base_params, runner)

    assert started.acquire(timeout=2)
    assert started.acquire(timeout=2)

    # Both slots filled; a third request should go pending
    record_c = store.build_record(execution_profile_id="shared-profile", prompt_body="from_a_2")
    store.write_record(root_a, record_c)
    manager.enqueue(root_a, record_c, base_params, runner)

    depth = manager.queue_depth("shared-profile")
    assert depth["running"] == 2
    assert depth["pending"] == 1

    hold.set()
    manager.wait(root_a, record_a["request-id"], timeout_seconds=5)
    manager.wait(root_b, record_b["request-id"], timeout_seconds=5)
    manager.wait(root_a, record_c["request-id"], timeout_seconds=5)


def test_sh07c2_different_params_create_separate_lanes(tmp_path: Path):
    """Same profile id but different non-secret params → separate lane keys."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    params_a = {"max-concurrency": 1, "provider_id": "local", "model_id": "m"}
    params_b = {"max-concurrency": 2, "provider_id": "local", "model_id": "m"}  # different concurrency

    snap_a = profiles_mod.snapshot_from_resolved_profile(
        profile_id="same-profile",
        provider_id=params_a["provider_id"],
        model_id=params_a["model_id"],
        params=params_a,
    )
    snap_b = profiles_mod.snapshot_from_resolved_profile(
        profile_id="same-profile",
        provider_id=params_b["provider_id"],
        model_id=params_b["model_id"],
        params=params_b,
    )

    # Different non-secret params → different config digest → separate lanes
    assert snap_a.config_digest != snap_b.config_digest
    assert snap_a.lane_key() != snap_b.lane_key()


def test_sh07c2_all_queue_depths_public_ids_no_paths(tmp_path: Path):
    """all_queue_depths returns redacted lane public ids with no project paths."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(execution_profile_id="test-profile", prompt_body="x")
    store.write_record(tmp_path, record)
    params = {"max-concurrency": 1, "provider_id": "local"}
    manager.enqueue(tmp_path, record, params, _immediate_runner)

    depths = manager.all_queue_depths()

    # Keys are public ids, not bare profile ids or paths
    for key in depths:
        assert tmp_path.as_posix() not in key, f"Project path leaked in lane public id: {key}"
        # Public id format: profile_id/generation/short_digest
        parts = key.split("/")
        assert len(parts) == 3, f"Expected profile/gen/digest format, got: {key}"
        assert parts[0] == "test-profile"


def test_sh07c2_queue_depth_public_ids_no_secrets(tmp_path: Path):
    """queue_depth still works by bare profile id; all_queue_depths uses public ids."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(execution_profile_id="prod-profile", prompt_body="x")
    store.write_record(tmp_path, record)
    params = {"max-concurrency": 1, "provider_id": "local"}
    manager.enqueue(tmp_path, record, params, _immediate_runner)

    # queue_depth accepts bare profile id
    depth = manager.queue_depth("prod-profile")
    assert depth["max_concurrency"] == 1

    # all_queue_depths uses redacted public ids — no project paths or auth tokens
    depths = manager.all_queue_depths()
    for key in depths:
        assert tmp_path.as_posix() not in key
        assert "api-key" not in key.lower()
        assert "token" not in key.lower()


# ---------------------------------------------------------------------------
# SH07 C2: gateway-owned registry — shared-mode authority
# ---------------------------------------------------------------------------

def _setup_shared_registry():
    """Install an InMemoryExecutionProfileRegistry for shared-mode tests."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    registry = profiles_mod.InMemoryExecutionProfileRegistry()
    profiles_mod.set_gateway_registry(registry)
    return registry


def _teardown_shared_registry():
    """Remove the shared gateway registry, restoring embedded mode."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    profiles_mod.set_gateway_registry(None)


@pytest.fixture(autouse=False)
def shared_registry():
    """Install and tear down a shared-mode InMemoryExecutionProfileRegistry."""
    reg = _setup_shared_registry()
    yield reg
    _teardown_shared_registry()


def test_sh07c2_shared_mode_cross_project_lane_limit(tmp_path: Path, shared_registry):
    """Two project roots submit same gateway profile; global max_concurrency=1
    is enforced across both while each request sees its own project root."""
    # Register a shared gateway profile with max_concurrency=1
    shared_registry.register(
        "shared-gw-profile",
        provider_id="local",
        model_id="m",
        max_concurrency=1,
    )
    snap = shared_registry.resolve_snapshot("shared-gw-profile")
    lane_key = snap.lane_key()
    snapshot_identity = {
        "gateway_profile_id": snap.profile_id,
        "gateway_profile_generation": snap.generation,
        "gateway_profile_config_digest": snap.config_digest,
        "gateway_execution_lane_key": lane_key.public_id(),
        "resolved_provider_id": snap.provider_id,
        "resolved_model_id": snap.model_id,
        "resolved_queue_limits": {"max-concurrency": snap.max_concurrency, "queue-max-size": snap.queue_max_size},
        "admission_policy_digest": snap.admission_policy_digest,
    }

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Semaphore(0)

    def runner(project_root: Path, record: dict) -> dict:
        started.release()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    root_a = tmp_path / "project_a"
    root_b = tmp_path / "project_b"
    root_a.mkdir()
    root_b.mkdir()

    # Both projects build records with the SAME registry snapshot identity.
    record_a = store.build_record(
        execution_profile_id="shared-gw-profile", prompt_body="from_a", **snapshot_identity,
    )
    store.write_record(root_a, record_a)

    record_b = store.build_record(
        execution_profile_id="shared-gw-profile", prompt_body="from_b", **snapshot_identity,
    )
    store.write_record(root_b, record_b)

    # Enqueue from project A — takes the only slot (registry says max_concurrency=1)
    t1 = threading.Thread(
        target=manager.enqueue,
        args=(root_a, record_a, {"max-concurrency": 99}, runner),
    )
    t1.start()
    assert started.acquire(timeout=2)

    # Enqueue from project B — must go pending (global limit = 1)
    manager.enqueue(root_b, record_b, {"max-concurrency": 99}, runner)

    depth = manager.queue_depth("shared-gw-profile")
    assert depth["running"] == 1
    assert depth["pending"] == 1

    hold.set()
    t1.join(timeout=5)
    manager.wait(root_b, record_b["request-id"], timeout_seconds=5)


def test_sh07c2_shared_mode_project_cannot_override_limits(tmp_path: Path, shared_registry):
    """Project-local same-name profile cannot increase/decrease shared gateway
    queue limits; limits come from the gateway registry snapshot."""
    # Registry says max_concurrency=2
    shared_registry.register(
        "controlled-profile",
        provider_id="local",
        model_id="m",
        max_concurrency=2,
        queue_max_size=4,
    )

    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started_count = 0
    started_lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        nonlocal started_count
        with started_lock:
            started_count += 1
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    # Build records with registry snapshot identity.
    snap = shared_registry.resolve_snapshot("controlled-profile")
    lane_key = snap.lane_key()
    snapshot_identity = {
        "gateway_profile_id": snap.profile_id,
        "gateway_profile_generation": snap.generation,
        "gateway_profile_config_digest": snap.config_digest,
        "gateway_execution_lane_key": lane_key.public_id(),
        "resolved_provider_id": snap.provider_id,
        "resolved_model_id": snap.model_id,
        "resolved_queue_limits": {"max-concurrency": snap.max_concurrency, "queue-max-size": snap.queue_max_size},
        "admission_policy_digest": snap.admission_policy_digest,
    }

    # Project tries to submit with max_concurrency=10 (should be ignored)
    params = {"max-concurrency": 10, "provider_id": "local", "model_id": "m"}

    records = []
    for i in range(4):
        record = store.build_record(
            execution_profile_id="controlled-profile", prompt_body=f"x{i}",
            **snapshot_identity,
        )
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, params, runner)
        records.append(record)

    # Registry says max_concurrency=2; only 2 should start running
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with started_lock:
            if started_count >= 2:
                break
        time.sleep(0.05)

    assert started_count == 2, f"expected 2 running (registry limit), got {started_count}"

    depth = manager.queue_depth("controlled-profile")
    assert depth["max_concurrency"] == 2, f"queue max_concurrency should be registry value 2, got {depth['max_concurrency']}"
    assert depth["running"] == 2
    assert depth["pending"] == 2

    hold.set()
    for r in records:
        manager.wait(tmp_path, r["request-id"], timeout_seconds=5)


def test_sh07c2_stale_generation_pending_rejected(tmp_path: Path):
    """Generation changes while a request is pending: the pending old request
    rejects with CON-AGW-101; new submission uses current generation and runs."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    registry = profiles_mod.InMemoryExecutionProfileRegistry()
    registry.register("gen-profile", provider_id="local", model_id="m", max_concurrency=1)
    snap_v1 = registry.resolve_snapshot("gen-profile")
    lane_key_v1 = snap_v1.lane_key()
    profiles_mod.set_gateway_registry(registry)

    try:
        manager = queue_mod.GatewayQueueManager()
        hold_first = threading.Event()

        def runner(project_root: Path, record: dict) -> dict:
            hold_first.wait(timeout=5)
            return store.transition_record(
                project_root, record["request-id"], "completed",
                updates={"output": "done", "finished-at": now_iso_z()},
            )

        # Request A with v1 snapshot
        record_a = store.build_record(
            execution_profile_id="gen-profile", prompt_body="v1",
            gateway_profile_id=snap_v1.profile_id,
            gateway_profile_generation=snap_v1.generation,
            gateway_profile_config_digest=snap_v1.config_digest,
            gateway_execution_lane_key=lane_key_v1.public_id(),
            resolved_provider_id=snap_v1.provider_id,
            resolved_model_id=snap_v1.model_id,
            resolved_queue_limits={"max-concurrency": snap_v1.max_concurrency, "queue-max-size": snap_v1.queue_max_size},
            admission_policy_digest=snap_v1.admission_policy_digest,
        )
        store.write_record(tmp_path, record_a)

        # Enqueue A — starts immediately (only slot)
        t1 = threading.Thread(
            target=manager.enqueue,
            args=(tmp_path, record_a, {"provider_id": "local"}, runner),
        )
        t1.start()
        time.sleep(0.1)

        # Request B with v1 snapshot — goes pending
        record_b = store.build_record(
            execution_profile_id="gen-profile", prompt_body="v1_pending",
            gateway_profile_id=snap_v1.profile_id,
            gateway_profile_generation=snap_v1.generation,
            gateway_profile_config_digest=snap_v1.config_digest,
            gateway_execution_lane_key=lane_key_v1.public_id(),
            resolved_provider_id=snap_v1.provider_id,
            resolved_model_id=snap_v1.model_id,
            resolved_queue_limits={"max-concurrency": snap_v1.max_concurrency, "queue-max-size": snap_v1.queue_max_size},
            admission_policy_digest=snap_v1.admission_policy_digest,
        )
        store.write_record(tmp_path, record_b)
        manager.enqueue(tmp_path, record_b, {"provider_id": "local"}, runner)

        # Now change generation in the registry (simulates profile update).
        # InMemoryExecutionProfileRegistry auto-increments version → new generation.
        registry.register("gen-profile", provider_id="local", model_id="m", max_concurrency=2)
        snap_v2 = registry.resolve_snapshot("gen-profile")
        assert snap_v2.generation != snap_v1.generation, "generation must change on re-register"

        # Request B is still pending with v1 snapshot. When _run_one picks it up,
        # the stale check should reject it with CON-AGW-101.
        hold_first.set()  # release A so worker can drain to B
        t1.join(timeout=5)

        result_b = manager.wait(tmp_path, record_b["request-id"], timeout_seconds=5)
        assert result_b["state"] == "rejected", (
            f"pending request with stale snapshot should be rejected, got {result_b['state']}"
        )
        assert result_b.get("error", {}).get("code") == "CON-AGW-101"

        # New submission with v2 can run normally
        record_c = store.build_record(
            execution_profile_id="gen-profile", prompt_body="v2_new",
            gateway_profile_id=snap_v2.profile_id,
            gateway_profile_generation=snap_v2.generation,
            gateway_profile_config_digest=snap_v2.config_digest,
            gateway_execution_lane_key=snap_v2.lane_key().public_id(),
            resolved_provider_id=snap_v2.provider_id,
            resolved_model_id=snap_v2.model_id,
            resolved_queue_limits={"max-concurrency": snap_v2.max_concurrency, "queue-max-size": snap_v2.queue_max_size},
            admission_policy_digest=snap_v2.admission_policy_digest,
        )
        store.write_record(tmp_path, record_c)
        manager.enqueue(tmp_path, record_c, {"provider_id": "local"}, _immediate_runner)

        result_c = manager.wait(tmp_path, record_c["request-id"], timeout_seconds=5)
        assert result_c["state"] == "completed"
    finally:
        profiles_mod.set_gateway_registry(None)


def test_sh07c2_running_request_keeps_old_snapshot(tmp_path: Path):
    """Running request keeps its stored snapshot after profile generation changes.
    Only pending/queued work is rejected; running work completes under old limits."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    registry = profiles_mod.InMemoryExecutionProfileRegistry()
    registry.register("run-profile", provider_id="local", model_id="m", max_concurrency=1)
    snap_v1 = registry.resolve_snapshot("run-profile")
    lane_key_v1 = snap_v1.lane_key()
    profiles_mod.set_gateway_registry(registry)

    try:
        manager = queue_mod.GatewayQueueManager()
        hold = threading.Event()
        started = threading.Event()

        def runner(project_root: Path, record: dict) -> dict:
            started.set()
            # Change generation while this request is running
            registry.register("run-profile", provider_id="local", model_id="m", max_concurrency=2)
            hold.wait(timeout=5)
            return store.transition_record(
                project_root, record["request-id"], "completed",
                updates={"output": "done-v1", "finished-at": now_iso_z()},
            )

        # Request A with v1 snapshot — starts running
        record_a = store.build_record(
            execution_profile_id="run-profile", prompt_body="running_v1",
            gateway_profile_id=snap_v1.profile_id,
            gateway_profile_generation=snap_v1.generation,
            gateway_profile_config_digest=snap_v1.config_digest,
            gateway_execution_lane_key=lane_key_v1.public_id(),
            resolved_provider_id=snap_v1.provider_id,
            resolved_model_id=snap_v1.model_id,
            resolved_queue_limits={"max-concurrency": snap_v1.max_concurrency, "queue-max-size": snap_v1.queue_max_size},
            admission_policy_digest=snap_v1.admission_policy_digest,
        )
        store.write_record(tmp_path, record_a)

        t1 = threading.Thread(
            target=manager.enqueue,
            args=(tmp_path, record_a, {"provider_id": "local"}, runner),
        )
        t1.start()
        assert started.wait(timeout=2)

        # Generation has changed (see runner). A new submission with v2 should
        # create a separate lane and can run independently.
        snap_v2 = registry.resolve_snapshot("run-profile")
        assert snap_v2.generation != snap_v1.generation, "generation must change on re-register"

        record_c = store.build_record(
            execution_profile_id="run-profile", prompt_body="v2_new_lane",
            gateway_profile_id=snap_v2.profile_id,
            gateway_profile_generation=snap_v2.generation,
            gateway_profile_config_digest=snap_v2.config_digest,
            gateway_execution_lane_key=snap_v2.lane_key().public_id(),
            resolved_provider_id=snap_v2.provider_id,
            resolved_model_id=snap_v2.model_id,
            resolved_queue_limits={"max-concurrency": snap_v2.max_concurrency, "queue-max-size": snap_v2.queue_max_size},
            admission_policy_digest=snap_v2.admission_policy_digest,
        )
        store.write_record(tmp_path, record_c)
        manager.enqueue(tmp_path, record_c, {"provider_id": "local"}, _immediate_runner)

        # Release A
        hold.set()
        t1.join(timeout=5)

        # A completed under v1 snapshot (old limits)
        result_a = manager.wait(tmp_path, record_a["request-id"], timeout_seconds=5)
        assert result_a["state"] == "completed"
        assert result_a["output"] == "done-v1"

        # C completed on the new lane
        result_c = manager.wait(tmp_path, record_c["request-id"], timeout_seconds=5)
        assert result_c["state"] == "completed"
    finally:
        profiles_mod.set_gateway_registry(None)


def test_sh07c2_queue_overview_redacted_lanes(tmp_path: Path):
    """Queue overview groups by redacted lane public id and does not include
    project roots or secrets."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(
        execution_profile_id="overview-profile", prompt_body="x",
        gateway_profile_id="overview-profile",
        gateway_profile_generation="gen_test123",
        gateway_profile_config_digest="sha256:abcd1234",
        gateway_execution_lane_key="overview-profile/gen_test123/abcd1234",
        resolved_provider_id="local",
        resolved_model_id="m",
        resolved_queue_limits={"max-concurrency": 1, "queue-max-size": 8},
        admission_policy_digest="sha256:policy01",
    )
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"provider_id": "local"}, _immediate_runner)

    depths = manager.all_queue_depths()

    # Keys are lane public ids — no project paths
    for key in depths:
        assert tmp_path.as_posix() not in key, f"Project path leaked: {key}"
        assert "\\" not in key, f"Windows path separator in lane id: {key}"
        # Format: profile_id/generation/short_digest
        parts = key.split("/")
        assert len(parts) == 3, f"Expected profile/gen/digest format, got: {key}"
