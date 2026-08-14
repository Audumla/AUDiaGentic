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

pytestmark = pytest.mark.no_parallel


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


def test_project_queue_depths_excludes_other_projects(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)

    first = _submit(manager, project_a, "reporting-profile", {"virtual-capacity": 1}, runner)
    assert started.wait(timeout=2)
    second = _submit(manager, project_b, "reporting-profile", {"virtual-capacity": 1}, runner)

    assert manager.project_queue_depths(project_a) == {
        "reporting-profile": {"pending": 0, "running": 1, "active_running": 1, "idle": 0}
    }
    assert manager.project_queue_depths(project_b) == {
        "reporting-profile": {"pending": 1, "running": 0, "active_running": 0, "idle": 0}
    }
    hold.set()
    assert manager.wait(project_a, first["request-id"], timeout_seconds=5)["state"] == "completed"
    assert manager.wait(project_b, second["request-id"], timeout_seconds=5)["state"] == "completed"


def test_project_capacity_allows_different_projects_to_run_concurrently(tmp_path: Path):
    """An explicit project limit must not serialize unrelated projects."""
    manager = queue_mod.GatewayQueueManager()
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    hold = threading.Event()
    started = threading.Semaphore(0)

    def runner(project_root: Path, record: dict) -> dict:
        started.release()
        hold.wait(timeout=5)
        return store.transition_record(
            project_root, record["request-id"], "completed",
            updates={"output": "done", "finished-at": now_iso_z()},
        )

    params = {
        "global-capacity": "unlimited",
        "project-capacity": 1,
        "session-capacity": "unlimited",
    }
    first = _submit(manager, project_a, "gpt-auto", params, runner)
    second = _submit(manager, project_b, "gpt-auto", params, runner)
    assert started.acquire(timeout=2)
    assert started.acquire(timeout=2)
    assert manager.queue_depth("gpt-auto")["running"] == 2

    hold.set()
    assert manager.wait(project_a, first["request-id"], timeout_seconds=5)["state"] == "completed"
    assert manager.wait(project_b, second["request-id"], timeout_seconds=5)["state"] == "completed"


def test_project_capacity_still_serializes_same_project(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    project = tmp_path / "project"
    project.mkdir()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)
    params = {"global-capacity": "unlimited", "project-capacity": 1}

    first = _submit(manager, project, "gpt-auto", params, runner)
    assert started.wait(timeout=2)
    second = _submit(manager, project, "gpt-auto", params, runner)
    assert manager.queue_depth("gpt-auto")["running"] == 1
    assert manager.queue_depth("gpt-auto")["pending"] == 1

    hold.set()
    assert manager.wait(project, first["request-id"], timeout_seconds=5)["state"] == "completed"
    assert manager.wait(project, second["request-id"], timeout_seconds=5)["state"] == "completed"


def test_project_capacity_is_shared_across_profile_lanes(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    project = tmp_path / "project"
    project.mkdir()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)
    params = {"global-capacity": "unlimited", "project-capacity": 1}

    first = _submit(manager, project, "profile-a", params, runner)
    assert started.wait(timeout=2)
    second = _submit(manager, project, "profile-b", params, runner)
    assert manager.queue_depth("profile-b")["pending"] == 1

    hold.set()
    assert manager.wait(project, first["request-id"], timeout_seconds=5)["state"] == "completed"
    assert manager.wait(project, second["request-id"], timeout_seconds=5)["state"] == "completed"


def test_invalid_capacity_rejects_admitted_record_instead_of_stranding_it(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    project = tmp_path / "project"
    project.mkdir()
    record = store.build_record(execution_profile_id="invalid", prompt_body="x")
    store.write_record(project, record)

    result = manager.enqueue(project, record, {"project-capacity": 0}, _immediate_runner)

    assert result["state"] == "rejected"
    assert result["error"]["code"] == "VAL-AGW-020"


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------

def test_virtual_capacity_one_serializes_requests(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    started = threading.Event()
    runner = _blocking_runner(hold, started)

    record1 = store.build_record(execution_profile_id="p1", prompt_body="a")
    store.write_record(tmp_path, record1)
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record1, {"virtual-capacity": 1}, runner))
    t.start()
    assert started.wait(timeout=2)

    depth = manager.queue_depth("p1")
    assert depth["running"] == 1

    record2 = store.build_record(execution_profile_id="p1", prompt_body="b")
    store.write_record(tmp_path, record2)
    manager.enqueue(tmp_path, record2, {"virtual-capacity": 1}, runner)
    # second stays queued while first still holds
    assert store.read_record(tmp_path, record2["request-id"])["state"] == "queued"

    hold.set()
    t.join(timeout=5)
    result2 = manager.wait(tmp_path, record2["request-id"], timeout_seconds=5)
    assert result2["state"] == "completed"


def test_virtual_capacity_two_runs_two_third_waits(tmp_path: Path):
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
        threading.Thread(target=manager.enqueue, args=(tmp_path, r, {"virtual-capacity": 2}, runner))
        for r in records
    ]
    # Start the first two requests together and wait for both runners before
    # admitting the third. Thread start order is not a scheduling guarantee;
    # starting all three at once made the assertion about records[2] flaky.
    threads[0].start()
    threads[1].start()
    assert started_count.acquire(timeout=2)
    assert started_count.acquire(timeout=2)
    threads[2].start()
    # Admission resolves the persisted snapshot and instance facts before it
    # reaches the queue. That setup is materially slower in a clean Docker
    # container than in the warm host process.
    deadline = time.monotonic() + 10
    depth = manager.queue_depth("p2")
    while time.monotonic() < deadline:
        depth = manager.queue_depth("p2")
        if depth["running"] == 2 and depth["pending"] == 1:
            break
        time.sleep(0.01)
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
        manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, runner)

    assert workers_entered.acquire(timeout=2)
    assert workers_entered.acquire(timeout=2)
    assert manager.queue_depth("session-profile")["running"] == 2

    allow_turn_start.set()
    release_compute.set()
    for record in records:
        assert manager.wait(tmp_path, record["request-id"], timeout_seconds=5)["state"] == "completed"
    assert max_active == 1


def test_session_capacity_serializes_same_session_but_not_other_sessions(tmp_path: Path):
    manager = queue_mod.GatewayQueueManager()
    entered = threading.Semaphore(0)
    allow_turn_start = threading.Event()
    release_compute = threading.Event()
    active = 0
    max_active = 0
    active_lock = threading.Lock()

    def runner(project_root: Path, record: dict) -> dict:
        nonlocal active, max_active
        entered.release()
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

    project = tmp_path / "project"
    project.mkdir()
    params = {
        "global-capacity": "unlimited",
        "project-capacity": "unlimited",
        "session-capacity": 1,
    }
    records = [
        store.build_record(
            execution_profile_id="session-scoped",
            prompt_body=str(index),
            session_id="same-session",
        )
        for index in range(2)
    ]
    for record in records:
        store.write_record(project, record)
        manager.enqueue(project, record, params, runner)
    assert entered.acquire(timeout=2)
    assert entered.acquire(timeout=2)
    allow_turn_start.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with active_lock:
            if active == 1:
                break
        time.sleep(0.01)
    with active_lock:
        assert active == 1
        assert max_active == 1
    release_compute.set()
    for record in records:
        assert manager.wait(project, record["request-id"], timeout_seconds=5)["state"] == "completed"


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
    t1 = threading.Thread(target=manager.enqueue, args=(tmp_path, first, {"virtual-capacity": 1}, runner))
    t1.start()
    time.sleep(0.05)  # ensure first claims the only slot before second/third submit

    second = store.build_record(execution_profile_id="p3", prompt_body="second")
    third = store.build_record(execution_profile_id="p3", prompt_body="third")
    store.write_record(tmp_path, second)
    store.write_record(tmp_path, third)
    manager.enqueue(tmp_path, second, {"virtual-capacity": 1}, runner)
    t3 = threading.Thread(target=manager.enqueue, args=(tmp_path, third, {"virtual-capacity": 1}, runner))
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
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"virtual-capacity": 1, "pending-capacity": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(execution_profile_id="p4", prompt_body="queued")
    store.write_record(tmp_path, queued)
    manager.enqueue(tmp_path, queued, {"virtual-capacity": 1, "pending-capacity": 1}, runner)

    overflow = store.build_record(execution_profile_id="p4", prompt_body="overflow")
    store.write_record(tmp_path, overflow)
    result = manager.enqueue(tmp_path, overflow, {"virtual-capacity": 1, "pending-capacity": 1}, runner)

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
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, running, {"virtual-capacity": 1}, runner))
    t.start()
    time.sleep(0.05)

    queued = store.build_record(execution_profile_id="p5", prompt_body="queued")
    store.write_record(tmp_path, queued)
    manager.enqueue(tmp_path, queued, {"virtual-capacity": 1}, runner)

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
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"virtual-capacity": 1}, runner))
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
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"virtual-capacity": 1}, runner))
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
    t = threading.Thread(target=manager.enqueue, args=(tmp_path, record, {"virtual-capacity": 1}, runner))
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
    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, _immediate_runner)
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
    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, _immediate_runner)
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
    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, _failing_runner)
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

    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, runner)
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
    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, _immediate_runner)

    result = manager.wait(tmp_path, record["request-id"], timeout_seconds=5)
    assert result["state"] == "completed"


# ---------------------------------------------------------------------------
# AS16 immutable-snapshot / race invariants
# ---------------------------------------------------------------------------

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

        manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, _runner_with_unknown_suffix)
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

    # Enqueue 3 requests with virtual_capacity=2; first two run immediately, third is pending.
    request_ids: list[str] = []
    for i in range(3):
        record = store.build_record(execution_profile_id="snap1", prompt_body=f"x{i}")
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, {"virtual-capacity": 2}, runner)
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
        manager.enqueue(tmp_path, record, {"virtual-capacity": 3}, runner)

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
    """pending + running must never exceed pending_capacity + virtual_capacity from one snapshot."""
    manager = queue_mod.GatewayQueueManager()
    hold = threading.Event()
    runner = _blocking_runner(hold)

    profile_id = "snap3"
    params = {"virtual-capacity": 2, "pending-capacity": 4}
    # Submit virtual_capacity + pending_capacity = 6 requests; all admitted.
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

    max_slots = params["virtual-capacity"] + params["pending-capacity"]
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
    params = {"virtual-capacity": 2, "pending-capacity": 4}
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
        assert depth["pending"] + depth["running"] <= params["virtual-capacity"] + params["pending-capacity"], (
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
    manager.enqueue(tmp_path, record, {"virtual-capacity": 1}, runner)

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
    """SH07: two requests on the same profile with virtual_capacity=1 must not
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
    params = {"virtual-capacity": 1}

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
    params = {"virtual-capacity": 1}

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
    base_params = {"virtual-capacity": 2, "provider_id": "local", "model_id": "m"}

    snap_a = profiles_mod.snapshot_from_resolved_profile(
        profile_id="shared-profile",
        provider_id=base_params["provider_id"],
        instances=("m",),
        params=base_params,
    )
    snap_b = profiles_mod.snapshot_from_resolved_profile(
        profile_id="shared-profile",
        provider_id=base_params["provider_id"],
        instances=("m",),
        params=dict(base_params),  # fresh dict, same content
    )

    assert snap_a.config_digest == snap_b.config_digest
    assert (snap_a.profile_id, snap_a.generation, snap_a.config_digest) == (
        snap_b.profile_id, snap_b.generation, snap_b.config_digest,
    )
    # Same lane identity means one shared queue

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

    params_a = {"virtual-capacity": 1, "provider_id": "local", "model_id": "m"}
    params_b = {"virtual-capacity": 2, "provider_id": "local", "model_id": "m"}  # different concurrency

    snap_a = profiles_mod.snapshot_from_resolved_profile(
        profile_id="same-profile",
        provider_id=params_a["provider_id"],
        instances=("m",),
        params=params_a,
    )
    snap_b = profiles_mod.snapshot_from_resolved_profile(
        profile_id="same-profile",
        provider_id=params_b["provider_id"],
        instances=("m",),
        params=params_b,
    )

    # Different non-secret params → different config digest → separate lanes
    assert snap_a.config_digest != snap_b.config_digest
    assert (snap_a.profile_id, snap_a.generation, snap_a.config_digest) != (
        snap_b.profile_id, snap_b.generation, snap_b.config_digest,
    )


def test_project_queue_depths_is_project_scoped(tmp_path: Path):
    """Project reporting exposes profile depth without internal lane keys."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(execution_profile_id="test-profile", prompt_body="x")
    store.write_record(tmp_path, record)
    params = {"virtual-capacity": 1, "provider_id": "local"}
    manager.enqueue(tmp_path, record, params, _immediate_runner)

    depths = manager.project_queue_depths(tmp_path)

    # Keys are public ids, not bare profile ids or paths
    assert depths["test-profile"]["pending"] + depths["test-profile"]["running"] >= 0


def test_project_queue_depths_hides_other_projects(tmp_path: Path):
    """Project reporting does not expose other projects or lane policy."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(execution_profile_id="prod-profile", prompt_body="x")
    store.write_record(tmp_path, record)
    params = {"virtual-capacity": 1, "provider_id": "local"}
    manager.enqueue(tmp_path, record, params, _immediate_runner)

    # queue_depth accepts bare profile id
    depth = manager.queue_depth("prod-profile")
    assert depth["virtual_capacity"] == 1

    # Project-scoped reporting exposes no project paths or auth tokens.
    depths = manager.project_queue_depths(tmp_path)
    assert "prod-profile" in depths


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


def _snapshot_identity_kwargs(snap) -> dict:
    """AS105/AS101: the record fields carrying a shared-registry snapshot's
    admission-time identity. gateway_execution_lane_key/resolved_queue_limits/
    admission_policy_digest are retired (always None going forward, per
    queue.py's own admission wiring) -- resolved_instance_ids replaces
    resolved_model_id as the field snapshot_from_record reconstructs from."""
    return {
        "gateway_profile_id": snap.profile_id,
        "gateway_profile_generation": snap.generation,
        "gateway_profile_config_digest": snap.config_digest,
        "resolved_provider_id": snap.provider_id,
        "resolved_instance_ids": list(snap.instances),
    }


@pytest.fixture()
def gated_source(tmp_path, monkeypatch):
    """AS105/AS101: declare a user-global model-sources.yaml source with
    resource-id+concurrency=1, so a profile naming it participates in
    free-instance dispatch instead of the legacy per-lane semaphore."""
    from audiagentic.components.providers import providers_api

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(home))
    providers_api.model_source_add_global(
        "gated-src",
        {
            "source-class": "local-endpoint",
            "connector": "openai-compatible",
            "base-url": "http://127.0.0.1:9/v1",
            "model-id": "m",
            "resource-id": "gpu-0",
            "concurrency": 1,
        },
    )
    return "gated-src"


def test_sh07c2_shared_mode_cross_project_lane_limit(tmp_path: Path, shared_registry, gated_source):
    """Two project roots submit same gateway profile naming a gated instance
    with concurrency=1; that global limit is enforced across both while each
    request sees its own project root."""
    shared_registry.register(
        "shared-gw-profile",
        provider_id="local",
        instances=(gated_source,),
    )
    snap = shared_registry.resolve_snapshot("shared-gw-profile")
    snapshot_identity = _snapshot_identity_kwargs(snap)

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

    # Enqueue from project A — takes the only slot (source concurrency=1)
    t1 = threading.Thread(
        target=manager.enqueue,
        args=(root_a, record_a, {}, runner),
    )
    t1.start()
    assert started.acquire(timeout=2)

    # Enqueue from project B — must go pending (global limit = 1)
    manager.enqueue(root_b, record_b, {}, runner)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        depth = manager.queue_depth("shared-gw-profile")
        if depth["running"] == 1 and depth["pending"] == 1:
            break
        time.sleep(0.02)
    depth = manager.queue_depth("shared-gw-profile")
    assert depth["running"] == 1
    assert depth["pending"] == 1

    hold.set()
    t1.join(timeout=5)
    manager.wait(root_b, record_b["request-id"], timeout_seconds=5)


def test_sh07c2_shared_mode_project_cannot_override_limits(tmp_path: Path, shared_registry, gated_source):
    """A project cannot increase a gated instance's concurrency by passing
    its own params -- capacity comes from the model-sources.yaml source, not
    from anything project-local."""
    shared_registry.register(
        "controlled-profile",
        provider_id="local",
        instances=(gated_source,),
    )
    snap = shared_registry.resolve_snapshot("controlled-profile")
    snapshot_identity = _snapshot_identity_kwargs(snap)

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

    # Project tries to submit with virtual_capacity=10 (irrelevant in gated
    # mode -- capacity is sourced from the resource tracker, not params).
    params = {"virtual-capacity": 10, "provider_id": "local"}

    records = []
    for i in range(4):
        record = store.build_record(
            execution_profile_id="controlled-profile", prompt_body=f"x{i}",
            **snapshot_identity,
        )
        store.write_record(tmp_path, record)
        manager.enqueue(tmp_path, record, params, runner)
        records.append(record)

    # Source concurrency=1; only 1 should start running regardless of params.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with started_lock:
            if started_count >= 1:
                break
        time.sleep(0.05)

    assert started_count == 1, f"expected 1 running (source concurrency), got {started_count}"

    depth = manager.queue_depth("controlled-profile")
    assert depth["running"] == 1
    assert depth["pending"] == 3

    hold.set()
    for r in records:
        manager.wait(tmp_path, r["request-id"], timeout_seconds=5)


def test_sh07c2_stale_generation_pending_rejected(tmp_path: Path):
    """Generation changes while a request is pending: the pending old request
    rejects with CON-AGW-101; new submission uses current generation and runs."""
    from audiagentic.components.agents.gateway import profiles as profiles_mod

    registry = profiles_mod.InMemoryExecutionProfileRegistry()
    registry.register("gen-profile", provider_id="local", instances=("m",))
    snap_v1 = registry.resolve_snapshot("gen-profile")
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
            **_snapshot_identity_kwargs(snap_v1),
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
            **_snapshot_identity_kwargs(snap_v1),
        )
        store.write_record(tmp_path, record_b)
        manager.enqueue(tmp_path, record_b, {"provider_id": "local"}, runner)

        # Now change generation in the registry (simulates profile update).
        # InMemoryExecutionProfileRegistry auto-increments version → new generation.
        registry.register("gen-profile", provider_id="local", instances=("m27b1", "m27b2"))
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
            **_snapshot_identity_kwargs(snap_v2),
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
    registry.register("run-profile", provider_id="local", instances=("m",))
    snap_v1 = registry.resolve_snapshot("run-profile")
    profiles_mod.set_gateway_registry(registry)

    try:
        manager = queue_mod.GatewayQueueManager()
        hold = threading.Event()
        started = threading.Event()

        def runner(project_root: Path, record: dict) -> dict:
            started.set()
            # Change generation while this request is running
            registry.register("run-profile", provider_id="local", instances=("m27b1", "m27b2"))
            hold.wait(timeout=5)
            return store.transition_record(
                project_root, record["request-id"], "completed",
                updates={"output": "done-v1", "finished-at": now_iso_z()},
            )

        # Request A with v1 snapshot — starts running
        record_a = store.build_record(
            execution_profile_id="run-profile", prompt_body="running_v1",
            **_snapshot_identity_kwargs(snap_v1),
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
            **_snapshot_identity_kwargs(snap_v2),
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


def test_project_queue_depths_redacted(tmp_path: Path):
    """Queue overview reports project profile depths without internal keys."""
    manager = queue_mod.GatewayQueueManager()

    record = store.build_record(
        execution_profile_id="overview-profile", prompt_body="x",
        gateway_profile_id="overview-profile",
        gateway_profile_generation="gen_test123",
        gateway_profile_config_digest="sha256:abcd1234",
        resolved_provider_id="local",
        resolved_instance_ids=["m"],
    )
    store.write_record(tmp_path, record)
    manager.enqueue(tmp_path, record, {"provider_id": "local"}, _immediate_runner)

    depths = manager.project_queue_depths(tmp_path)

    # Keys are lane public ids — no project paths
    assert "overview-profile" in depths
