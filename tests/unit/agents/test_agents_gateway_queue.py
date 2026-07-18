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

from audiagentic.components.agents import agents_gateway_queue as queue_mod
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_paths import gateway_timeline_path
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
    record = store.build_record(agent_profile_id=profile_id, prompt_body="x")
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

    record1 = store.build_record(agent_profile_id="p1", prompt_body="a")
    store.write_record(tmp_path, record1)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record1, {"max-concurrency": 1}, runner))
    t.start()
    assert started.wait(timeout=2)

    depth = manager.queue_depth("p1")
    assert depth["running"] == 1

    record2 = store.build_record(agent_profile_id="p1", prompt_body="b")
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

    records = [store.build_record(agent_profile_id="p2", prompt_body=str(i)) for i in range(3)]
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
            agent_profile_id="session-profile",
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

    first = store.build_record(agent_profile_id="p3", prompt_body="first")
    store.write_record(tmp_path, first)
    t1 = threading.Thread(target=manager.enqueue, args=(tmp_path, first, {"max-concurrency": 1}, runner))
    t1.start()
    time.sleep(0.05)  # ensure first claims the only slot before second/third submit

    second = store.build_record(agent_profile_id="p3", prompt_body="second")
    third = store.build_record(agent_profile_id="p3", prompt_body="third")
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

    running = store.build_record(agent_profile_id="p4", prompt_body="running")
    store.write_record(tmp_path, running)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"max-concurrency": 1, "queue-max-size": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(agent_profile_id="p4", prompt_body="queued")
    store.write_record(tmp_path, queued)
    manager.enqueue(tmp_path, queued, {"max-concurrency": 1, "queue-max-size": 1}, runner)

    overflow = store.build_record(agent_profile_id="p4", prompt_body="overflow")
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

    running = store.build_record(agent_profile_id="p5", prompt_body="running")
    store.write_record(tmp_path, running)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"max-concurrency": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(agent_profile_id="p5", prompt_body="queued")
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

    record = store.build_record(agent_profile_id="p9", prompt_body="x")
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

    record = store.build_record(agent_profile_id="p10", prompt_body="x")
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

    record = store.build_record(agent_profile_id="p6", prompt_body="x")
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
    record = store.build_record(agent_profile_id="p5-race", prompt_body="queued")
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
    record = store.build_record(agent_profile_id="p6", prompt_body="x")
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
    record = store.build_record(agent_profile_id="p6", prompt_body="x")
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
        "from audiagentic.components.agents import agents_gateway_store as store",
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
    record = store.build_record(agent_profile_id="p7", prompt_body="x")
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
    record = store.build_record(agent_profile_id="p8", prompt_body="x")
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

    get_bus().subscribe("agents.llm.completed", on_completed)

    record = store.build_record(agent_profile_id="p11", prompt_body="x")
    store.write_record(tmp_path, record)

    def runner(project_root: Path, rec: dict) -> dict:
        store.append_attempt(
            project_root, rec["request-id"],
            agent_profile_id="p11", provider_id="local-openai", model_id="gpt-4o",
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
    record = store.build_record(agent_profile_id="p12", prompt_body="x")
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"max-concurrency": 1}, _immediate_runner)

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"


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
        record = store.build_record(agent_profile_id="p12", prompt_body="x")
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
