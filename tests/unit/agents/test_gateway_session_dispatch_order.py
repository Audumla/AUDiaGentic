"""Submission order must survive concurrent worker preparation."""
import asyncio
import threading
import functools
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue import queue as queue_mod
from audiagentic.components.agents.gateway.queue.session_order import SessionDispatchOrder


def test_cancel_between_status_read_and_ticket_lookup_cannot_dispatch():
    order = SessionDispatchOrder()
    order.register("parent", "project", "session")
    order.register("cancelled", "project", "session")

    def cancelled_after_read():
        order.complete("cancelled")
        return False  # Simulate the stale pre-cancellation durable read.

    assert order.wait("cancelled", cancelled_after_read) is False
    assert order.is_head("cancelled") is False
    assert order.wait("ungated", lambda: False, required=False) is True
    assert order.is_head("parent") is True


@pytest.mark.parametrize("cancel_middle", [False, True])
@pytest.mark.parametrize("terminal_before_unwind", [False, True])
def test_session_fifo_survives_preparation_overtake_without_blocking_other_session(tmp_path, monkeypatch, cancel_middle, terminal_before_unwind):
    manager = queue_mod.GatewayQueueManager()
    release_first = threading.Event()
    release_second_worker = threading.Event()
    second_worker_waiting = threading.Event()
    third_worker_arrived = threading.Event()
    first_entered = threading.Event()
    third_entered = threading.Event()
    other_entered = threading.Event()
    order = []
    records = [store.build_record(
        execution_profile_id="fifo-profile", prompt_body=str(i),
        session_id="other-session" if i == 3 else "same-session",
        provider_transport_kind="provider-session",
    ) for i in range(4)]
    ids = [r["request-id"] for r in records]
    original_worker = manager._run_one

    def delayed_worker(pq, entry, bound):
        if entry.request_id == ids[1]:
            second_worker_waiting.set()
            assert release_second_worker.wait(10)
        if entry.request_id == ids[2]:
            third_worker_arrived.set()
        original_worker(pq, entry, bound)

    monkeypatch.setattr(manager, "_run_one", delayed_worker)

    def runner(root, record, *, session_start):
        current = session_start()
        rid = current["request-id"]
        asyncio.run(queue_mod.notify_turn_starting(rid))
        try:
            order.append(rid)
            if rid == ids[0]:
                if terminal_before_unwind:
                    terminal = store.transition_owned_terminal(
                        root, rid, "completed", owner_epoch=current["dispatch-owner-epoch"],
                        worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"], updates={"output": "done"},
                    )
                first_entered.set()
                assert release_first.wait(10)
                if terminal_before_unwind:
                    return terminal
            elif rid == ids[2]:
                third_entered.set()
            elif rid == ids[3]:
                other_entered.set()
            return store.transition_owned_terminal(
                root, rid, "completed", owner_epoch=current["dispatch-owner-epoch"],
                worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
                updates={"output": "done"},
            )
        finally:
            asyncio.run(queue_mod.notify_turn_done(rid))

    params = {"global-capacity": "unlimited", "project-capacity": "unlimited"}
    try:
        for i, record in enumerate(records):
            store.write_record(tmp_path, record)
            manager.enqueue(tmp_path, record, params, runner)
            if i == 0:
                assert first_entered.wait(3)
        assert second_worker_waiting.wait(3)
        assert third_worker_arrived.wait(3)
        assert other_entered.wait(3), "unrelated session was blocked by same-session FIFO"
        if terminal_before_unwind:
            assert store.read_record(tmp_path, ids[0])["state"] == "completed"
            assert not third_entered.wait(.1), "terminal write released the still-active worker's lane"
        if cancel_middle:
            assert manager.cancel(tmp_path, "fifo-profile", ids[1])["state"] == "cancelled"
        release_first.set()
        assert manager.wait(tmp_path, ids[0], timeout_seconds=3)["state"] == "completed"
        if cancel_middle:
            assert third_entered.wait(3), "cancelled predecessor blocked its successor"
        else:
            assert not third_entered.wait(.2), "later worker overtook earlier admitted request"
        release_second_worker.set()
        for rid in ids:
            result = manager.wait(tmp_path, rid, timeout_seconds=5)
            assert result["state"] == ("cancelled" if cancel_middle and rid == ids[1] else "completed")
        same_session_order = [rid for rid in order if rid != ids[3]]
        assert same_session_order == ([ids[0], ids[2]] if cancel_middle else ids[:3])
    finally:
        release_first.set()
        release_second_worker.set()
        for rid in ids:
            try:
                manager.wait(tmp_path, rid, timeout_seconds=3)
            except Exception:
                pass  # A failed assertion may precede writing every record.
        manager.shutdown()


def test_durable_admission_registration_prevents_later_publication_overtake(tmp_path):
    manager = queue_mod.GatewayQueueManager()
    entered = []
    callback = functools.partial(manager.reserve_session_admission, project_root=tmp_path)
    records = []
    for i in range(2):
        candidate = store.build_record(
            execution_profile_id="fifo-profile", prompt_body=str(i),
            session_id="same-session", provider_transport_kind="provider-session",
        )
        admitted, created = store.admit_record(tmp_path, candidate, idempotency_key=str(i), on_admitted=callback)
        assert created
        records.append(admitted)
    assert [r["enqueue-ordinal"] for r in records] == [1, 2]
    replay, created = store.admit_record(tmp_path, records[0], idempotency_key="0", on_admitted=callback)
    assert not created and replay["enqueue-ordinal"] == 1

    def runner(root, record, *, session_start):
        current = session_start()
        entered.append(record["request-id"])
        return store.transition_owned_terminal(
            root, record["request-id"], "completed", owner_epoch=current["dispatch-owner-epoch"],
            worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"], updates={"output": "done"},
        )

    params = {"global-capacity": "unlimited"}
    try:
        # Simulate thread A pausing after durable admission, while B publishes
        # its worker first. B must retain its queued, non-running state.
        manager.enqueue(tmp_path, records[1], params, runner)
        assert manager.wait(tmp_path, records[1]["request-id"], timeout_seconds=.1)["state"] == "queued"
        assert not entered
        manager.enqueue(tmp_path, records[0], params, runner)
        for record in records:
            assert manager.wait(tmp_path, record["request-id"], timeout_seconds=3)["state"] == "completed"
        assert entered == [r["request-id"] for r in records]
    finally:
        manager.shutdown()


def test_service_recovery_seeds_running_then_uses_durable_queue_ordinals(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway import api
    from audiagentic.components.agents.gateway.queue import recovery
    from audiagentic.components.agents.gateway.service import host, known_projects
    from audiagentic.components.providers.adapters.gpt_auto import config

    records = {
        "active": {"request-id": "active", "enqueue-ordinal": 3, "created-at": "c"},
        "earlier": {"request-id": "earlier", "enqueue-ordinal": 1, "created-at": "z"},
        "later": {"request-id": "later", "enqueue-ordinal": 2, "created-at": "a"},
    }
    calls = []
    manager = SimpleNamespace(
        enqueue_recovered_running=lambda root, record, *args, **kwargs: calls.append(("running", record["request-id"])),
        enqueue_recovered_queued=lambda root, record, *args, **kwargs: calls.append(("queued", record["request-id"])),
    )
    monkeypatch.setattr(api, "get_queue_manager", lambda: manager)
    monkeypatch.setattr(api.store, "read_record", lambda root, rid: records[rid])
    monkeypatch.setattr(recovery, "recover_gateway_requests", lambda *args, **kwargs: SimpleNamespace(
        running=[(tmp_path, "active")], queued=[(tmp_path, "later"), (tmp_path, "earlier")],
    ))
    monkeypatch.setattr(recovery, "recovery_runner", lambda *args, **kwargs: None)
    monkeypatch.setattr(config, "validate_machine_gpt_auto_config", lambda: None)
    monkeypatch.setattr(known_projects, "scan_known_gpt_auto_projects", lambda *args, **kwargs: None)
    instance = SimpleNamespace(
        service_store=SimpleNamespace(root=tmp_path), owner_epoch="new-owner", _externally_managed=True,
        _start_ingress_poller=lambda: None, _start_operations_poller=lambda: None,
        lifecycle=None, server=SimpleNamespace(serve_forever=lambda **kwargs: None), _stop_background=lambda: None,
    )
    host.GatewayServiceHost.serve_forever(instance)
    assert calls == [("running", "active"), ("queued", "earlier"), ("queued", "later")]
