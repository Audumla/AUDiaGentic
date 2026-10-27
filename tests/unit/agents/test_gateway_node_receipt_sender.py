"""Standalone sender with real node channels/receipts; fake child I/O, no native E2E."""

from __future__ import annotations

import asyncio

import pytest
from tests.unit.agents.test_gateway_node_execution_owner import env as env
from tests.unit.agents.test_gateway_node_recipient_runtime import (
    close,
    command,
    pair,
    prepare,
    retained_historical_artifact,
    setup,
    worker_io,
)
from tests.unit.agents.test_gateway_node_transport import wait_until

from audiagentic.components.agents.gateway.node.execution_owner import NodeExecutionOwner
from audiagentic.components.agents.gateway.node.receipt_sender import NodeReceiptSender
from audiagentic.components.agents.gateway.node.work_protocol import (
    ReceiptReady,
    ReceiptResume,
    ReceiptWork,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


class Central:
    """Test-only custody peer; no canonical mutation or new production authority."""

    def __init__(
        self, owner, *, cursor=0, acknowledge=True, resume_changes=None, ack_sequence=None
    ):
        self.owner = owner
        self.cursor = cursor
        self.acknowledge = acknowledge
        self.resume_changes = resume_changes or {}
        self.ack_sequence = ack_sequence
        self.resumes, self.receipts, self.ready = [], [], []
        self.received = asyncio.Event()
        self.intended = asyncio.Event()
        self.terminal = asyncio.Event()

    async def digest(self, sequence):
        if not sequence:
            return None
        rows = await asyncio.to_thread(self.owner.receipts_after, sequence - 1, limit=1)
        return rows[0].digest if rows else "f" * 64

    def attach(self, gateway):
        previous = gateway._on_work

        async def handle(frame, work):
            if type(work) is ReceiptReady:
                self.ready.append(work)
            elif type(work) is ReceiptResume:
                self.resumes.append(work)
                payload = {
                    "kind": "receipt-resume",
                    "in-reply-to": frame.message_id,
                    "log-incarnation-id": work.log_incarnation_id,
                    "after-sequence": self.cursor,
                    "after-receipt-sha256": await self.digest(self.cursor),
                }
                payload.update(self.resume_changes)
                await gateway.send_work("reconcile-result", payload)
            elif type(work) is ReceiptWork:
                self.receipts.append(work.receipt)
                if self.acknowledge:
                    through = self.ack_sequence or max(self.cursor, work.receipt.sequence)
                    self.cursor = max(self.cursor, through)
                    await gateway.send_work(
                        "reconcile-result",
                        {
                            "kind": "receipt-ack",
                            "server-id": "server",
                            "log-incarnation-id": work.log_incarnation_id,
                            "through-sequence": through,
                            "through-receipt-sha256": await self.digest(through),
                        },
                    )
                self.received.set()
                if work.receipt.state == "effect-intent":
                    self.intended.set()
                if work.receipt.state == "terminal":
                    self.terminal.set()
            else:
                await previous(frame, work)

        gateway._on_work = handle


async def stop_sender(task):
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def wait_cursor(owner, sequence, task=None):
    async def current():
        return (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence

    for _ in range(300):
        if task is not None and task.done():
            task.result()
            pytest.fail("sender stopped before durable ACK")
        if await current() == sequence:
            return
        await asyncio.sleep(0.005)
    pytest.fail("durable ACK did not arrive")


@pytest.mark.asyncio
async def test_central_ahead_replays_local_ack_then_accepts_valid_cumulative_jump(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, cursor=terminal.sequence)
    central.attach(gateway)
    task = asyncio.create_task(NodeReceiptSender(runtime, ack_timeout_seconds=1).run(node))
    try:
        await wait_cursor(owner, terminal.sequence)
        assert [r.sequence for r in central.receipts] == [1]
        assert central.resumes[0].through_sequence == 0
        assert runtime.execution_owner is owner
        assert not runtime.producer_pending and not calls
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_central_behind_local_ack_is_explicit_contradiction_not_reset(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    cp = await asyncio.to_thread(owner.receipt_checkpoint)
    await gateway.send_work(
        "reconcile-result",
        {
            "kind": "receipt-ack",
            "server-id": "server",
            "log-incarnation-id": cp.log_incarnation_id,
            "through-sequence": terminal.sequence,
            "through-receipt-sha256": terminal.digest,
        },
    )
    await asyncio.wait_for(runtime.acknowledgement_event.wait(), 2)
    central = Central(owner)
    central.attach(gateway)
    try:
        with pytest.raises(AudiaGenticError) as error:
            await NodeReceiptSender(runtime, ack_timeout_seconds=1).run(node)
        assert error.value.details["reason_code"] == "receipt-cursor-contradiction"
        assert (
            await asyncio.to_thread(owner.receipt_checkpoint)
        ).through_sequence == terminal.sequence
        assert not central.receipts and not node._task.done()
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["unknown-sequence", "hash", "log"])
async def test_resume_cursor_must_match_exact_local_metadata(env, monkeypatch, bad):
    from uuid import uuid4

    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    changes = {"after-receipt-sha256": "f" * 64} if bad == "hash" else {}
    if bad == "log":
        changes["log-incarnation-id"] = str(uuid4())
    central = Central(
        owner,
        cursor=100 if bad == "unknown-sequence" else terminal.sequence,
        resume_changes=changes,
    )
    central.attach(gateway)
    try:
        with pytest.raises(AudiaGenticError):
            await asyncio.wait_for(NodeReceiptSender(runtime, ack_timeout_seconds=0.3).run(node), 2)
        assert (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence == 0
        assert not central.receipts
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_duplicate_ack_event_cannot_advance_or_extend_deadline(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    cp = await asyncio.to_thread(owner.receipt_checkpoint)
    first = (await asyncio.to_thread(owner.receipts_after, 0, limit=1))[0]
    await gateway.send_work(
        "reconcile-result",
        {
            "kind": "receipt-ack",
            "server-id": "server",
            "log-incarnation-id": cp.log_incarnation_id,
            "through-sequence": 1,
            "through-receipt-sha256": first.digest,
        },
    )
    await asyncio.wait_for(runtime.acknowledgement_event.wait(), 2)
    central = Central(owner, cursor=1, ack_sequence=1)
    central.attach(gateway)
    try:
        with pytest.raises(AudiaGenticError) as error:
            await NodeReceiptSender(runtime, ack_timeout_seconds=0.04).run(node)
        assert error.value.details["reason_code"] == "receipt-ack-timeout"
        assert [r.sequence for r in central.receipts] == [2]
        assert (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence == 1
        assert not node._task.done()
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_idle_sender_has_no_metadata_poll_and_cancellation_leaves_receiver_live(
    env, monkeypatch
):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    original = NodeExecutionOwner.receipts_after
    reads = []

    def read(self, *args, **kwargs):
        reads.append((args, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(NodeExecutionOwner, "receipts_after", read)
    sender = NodeReceiptSender(runtime, poll_interval_seconds=0.005)
    idle = asyncio.Event()
    wait = sender._wait

    async def waiting(closed, events, timeout=None):
        assert timeout is None
        idle.set()
        return await wait(closed, events, timeout)

    monkeypatch.setattr(sender, "_wait", waiting)
    task = asyncio.create_task(sender.run(node))
    try:
        await asyncio.wait_for(idle.wait(), 2)
        await asyncio.sleep(0.03)  # Several configured poll intervals, zero idle reads.
        assert len(reads) == 1
        await stop_sender(task)
        assert not node._task.done() and not node._task.cancelled()
        before = node._received_sequence
        await gateway.heartbeat()
        await wait_until(lambda: node._received_sequence == before + 1)
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_no_checkpoint_waits_for_change_without_initializing_or_sending(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    monkeypatch.setattr(NodeExecutionOwner, "receipt_checkpoint", lambda self: None)
    monkeypatch.setattr(
        NodeExecutionOwner, "receipts_after", lambda *args, **kw: pytest.fail("no log to replay")
    )
    sender = NodeReceiptSender(runtime)
    waiting = asyncio.Event()
    original = sender._wait

    async def wait(closed, events, timeout=None):
        assert timeout is None
        waiting.set()
        return await original(closed, events, timeout)

    monkeypatch.setattr(sender, "_wait", wait)
    task = asyncio.create_task(sender.run(node))
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        assert not central.resumes and not central.receipts
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_close_signal_sender_exit_never_joins_receiver_callback_cycle(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    task = asyncio.create_task(NodeReceiptSender(runtime).run(node))
    await wait_until(lambda: len(central.resumes) == 1)
    previous = node._on_close

    async def closed():
        await task  # Host cleanup may await the sender; sender must not join this receiver.
        await previous()

    node._on_close = closed
    try:
        await asyncio.wait_for(node.close(), 2)
        assert task.done() and not task.cancelled()
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_unknown_cumulative_ack_cannot_advance_local_cursor(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, ack_sequence=100)
    central.attach(gateway)
    task = asyncio.create_task(NodeReceiptSender(runtime, ack_timeout_seconds=0.2).run(node))
    try:
        await asyncio.wait_for(task, 2)
        assert node.failure is not None
        assert (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence == 0
        assert not runtime.acknowledgement_event.is_set()
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_live_producer_without_scope_handoff_does_not_hide_ack_timeout(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, native_calls = worker_io(env, monkeypatch, block=True)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, acknowledge=False)
    central.attach(gateway)
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(AudiaGenticError) as error:
            await NodeReceiptSender(runtime, ack_timeout_seconds=0.03).run(node)
        assert error.value.details["reason_code"] == "receipt-ack-timeout"
        assert runtime.producer_pending and not node._task.done()
        release.set()
        assert (await runtime.wait_producer()).state == "terminal" and len(native_calls) == 1
    finally:
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        await close(node, gateway)


@pytest.mark.asyncio
async def test_g2_deferred_ack_waits_original_producer_then_resumes_and_replays(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, native_calls = worker_io(env, monkeypatch, block=True)
    node, gateway, _ = await pair(runtime)
    newer = None
    task = None
    deferred = asyncio.Event()
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 2)
        newer, new_gateway, _ = await pair(runtime, generation=2, gateway_epoch="gateway2")
        central = Central(owner)
        central.attach(new_gateway)
        sender = NodeReceiptSender(runtime, ack_timeout_seconds=1, poll_interval_seconds=0.01)
        original_wait = sender._wait

        async def wait(closed, events, timeout=None):
            if timeout == sender.poll_interval:
                deferred.set()  # The ACK deadline actually expired under the live handoff.
            return await original_wait(closed, events, timeout)

        monkeypatch.setattr(sender, "_wait", wait)
        task = asyncio.create_task(sender.run(newer))
        await asyncio.wait_for(deferred.wait(), 2)
        assert not task.done() and len(central.resumes) == 1
        assert (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence == 0
        assert runtime.producer_pending and not newer._task.done()
        assert (
            await asyncio.to_thread(owner.snapshot)
        ).owner_scope.gateway_owner_epoch == "gateway"
        release.set()
        terminal = await runtime.wait_producer()
        await wait_cursor(owner, terminal.sequence, task=task)
        assert len(central.resumes) == 2
        assert (
            await asyncio.to_thread(owner.snapshot)
        ).owner_scope.gateway_owner_epoch == "gateway2"
        assert [r.sequence for r in central.receipts][:2] == [1, 1]
        assert len(native_calls) == 1
    finally:
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        if task is not None:
            await stop_sender(task)
        await close(node, gateway)
        if newer is not None:
            await close(newer, new_gateway)


@pytest.mark.asyncio
async def test_pending_producer_poll_emits_intermediate_receipts_before_terminal(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, native_calls = worker_io(env, monkeypatch, block=True)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    # Hold run_one before any prepare/intent so the producer-create event cannot
    # itself reveal receipts. The metadata poll must discover them afterward.
    import threading

    start_native = threading.Event()
    polled = asyncio.Event()
    original_run = NodeExecutionOwner.run_one

    def blocked_start(self, *args, **kwargs):
        assert start_native.wait(5)
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(NodeExecutionOwner, "run_one", blocked_start)
    sender = NodeReceiptSender(runtime, poll_interval_seconds=0.005)
    original_wait = sender._wait

    async def waiting(closed, events, timeout=None):
        if timeout == sender.poll_interval:
            polled.set()
        return await original_wait(closed, events, timeout)

    monkeypatch.setattr(sender, "_wait", waiting)
    task = asyncio.create_task(sender.run(node))
    try:
        await wait_until(lambda: bool(central.resumes))
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(polled.wait(), 2)
        assert not central.receipts
        start_native.set()
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(central.intended.wait(), 2)
        assert runtime.producer_pending and not central.terminal.is_set()
        assert not release.is_set() and len(native_calls) == 1
        release.set()
        terminal = await runtime.wait_producer()
        await wait_cursor(owner, terminal.sequence)
        assert [r.state for r in central.receipts] == ["prepared", "effect-intent", "terminal"]
    finally:
        start_native.set()
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_cancel_pending_resume_keeps_late_reply_correlated_and_receiver_alive(
    env, monkeypatch
):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(frame, message):
        assert type(message) is ReceiptResume
        entered.set()
        await release.wait()
        await gateway.send_work(
            "reconcile-result",
            {
                "kind": "receipt-resume",
                "in-reply-to": frame.message_id,
                "log-incarnation-id": message.log_incarnation_id,
                "after-sequence": 0,
                "after-receipt-sha256": None,
            },
        )

    gateway._on_work = handler
    task = asyncio.create_task(NodeReceiptSender(runtime, ack_timeout_seconds=1).run(node))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await stop_sender(task)
        assert not node._task.done()
        release.set()
        await wait_until(lambda: not node._pending)
        assert node.failure is None and not node._task.done()
    finally:
        release.set()
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ack_timeout_seconds": 0},
        {"ack_timeout_seconds": True},
        {"ack_timeout_seconds": float("inf")},
        {"poll_interval_seconds": 0},
        {"poll_interval_seconds": 2},
    ],
)
def test_sender_rejects_unsupported_timing_bounds(env, monkeypatch, kwargs):
    owner, runtime, calls = setup(env, monkeypatch)
    with pytest.raises(AudiaGenticError):
        NodeReceiptSender(runtime, **kwargs)


@pytest.mark.asyncio
async def test_reconnect_replays_receipts_without_effect_or_artifact_replay(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    first, gateway, _ = await pair(runtime)
    await close(first, gateway)
    # Metadata remains independently replayable even when the artifact is gone.
    (env.config.state_root / "outputs" / (terminal.output_sha256 + ".txt")).unlink()
    node, gateway, _ = await pair(runtime, generation=2, gateway_epoch="gateway2")
    central = Central(owner, cursor=terminal.sequence)
    central.attach(gateway)
    monkeypatch.setattr(
        NodeExecutionOwner, "run_one", lambda *args, **kw: pytest.fail("replayed effect")
    )
    monkeypatch.setattr(
        NodeExecutionOwner,
        "read_artifact_chunk",
        lambda *args, **kw: pytest.fail("sender read artifact"),
    )
    task = asyncio.create_task(NodeReceiptSender(runtime, ack_timeout_seconds=1).run(node))
    try:
        await wait_cursor(owner, terminal.sequence, task)
        assert [r.sequence for r in central.receipts] == [1]
        assert central.receipts[0].identity.gateway_owner_epoch == "gateway"
        assert node.identity.gateway_owner_epoch == "gateway2"
        assert not calls and not runtime.producer_pending
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_sender_cancellation_never_cancels_running_producer(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    entered, release, native_calls = worker_io(env, monkeypatch, block=True)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, acknowledge=False)
    central.attach(gateway)
    task = None
    try:
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 2)
        task = asyncio.create_task(NodeReceiptSender(runtime).run(node))
        await asyncio.wait_for(central.received.wait(), 2)
        await stop_sender(task)
        assert runtime.producer_pending and not node._task.done()
        before = node._received_sequence
        await gateway.heartbeat()
        await wait_until(lambda: node._received_sequence == before + 1)
        release.set()
        assert (await runtime.wait_producer()).state == "terminal" and len(native_calls) == 1
    finally:
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        if task is not None:
            await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_sender_local_metadata_io_is_off_control_loop(env, monkeypatch):
    import threading

    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, cursor=terminal.sequence)
    central.attach(gateway)
    loop_thread = threading.get_ident()
    checked = set()
    for name in ("receipt_checkpoint", "receipts_after"):
        original = getattr(NodeExecutionOwner, name)

        def checked_call(self, *args, _name=name, _original=original, **kwargs):
            assert threading.get_ident() != loop_thread
            checked.add(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(NodeExecutionOwner, name, checked_call)
    task = asyncio.create_task(NodeReceiptSender(runtime, ack_timeout_seconds=1).run(node))
    try:
        await wait_cursor(owner, terminal.sequence, task)
        assert checked == {"receipt_checkpoint", "receipts_after"}
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_event_without_durable_ack_never_becomes_progress(env, monkeypatch):
    case, terminal, raw = retained_historical_artifact(env, monkeypatch)
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner, acknowledge=False)
    central.attach(gateway)
    handler = gateway._on_work

    async def notify_only(frame, work):
        await handler(frame, work)
        if type(work) is ReceiptWork:
            runtime.acknowledgement_event.set()

    gateway._on_work = notify_only
    try:
        with pytest.raises(AudiaGenticError) as error:
            await NodeReceiptSender(runtime, ack_timeout_seconds=0.03).run(node)
        assert error.value.details["reason_code"] == "receipt-ack-timeout"
        assert (await asyncio.to_thread(owner.receipt_checkpoint)).through_sequence == 0
        assert len(central.receipts) == 1 and not node._task.done()
    finally:
        await close(node, gateway)


@pytest.mark.asyncio
async def test_first_boot_ready_zero_cursor_and_duplicate_state_hints_do_not_poll_or_repeat(env, monkeypatch):
    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    sender = NodeReceiptSender(runtime)
    idle = asyncio.Queue()
    original = sender._wait

    async def waiting(closed, events, timeout=None):
        assert timeout is None
        idle.put_nowait(True)
        return await original(closed, events, timeout)

    monkeypatch.setattr(sender, "_wait", waiting)
    task = asyncio.create_task(sender.run(node))
    try:
        await asyncio.wait_for(idle.get(), 2)
        await wait_until(lambda: len(central.ready) == 1)
        ready = central.ready[0]
        checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
        assert ready.log_incarnation_id == checkpoint.log_incarnation_id
        assert ready.through_sequence == 0 and ready.through_receipt_sha256 is None
        assert not central.receipts and len(central.resumes) == 1
        for _ in range(3):
            runtime.state_changed_event.set()  # Notification is not a new cycle.
            await asyncio.wait_for(idle.get(), 2)
        assert len(central.ready) == 1
    finally:
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_two_commands_same_connection_ready_only_after_terminal_ack_and_producer_finally(env, monkeypatch):
    import threading

    from tests.unit.agents.test_gateway_node_execution_owner import second_case
    from tests.unit.agents.test_gateway_node_worker_terminal import mint_proof

    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    sender = NodeReceiptSender(runtime, poll_interval_seconds=0.005)
    task = asyncio.create_task(sender.run(node))
    original = NodeExecutionOwner.run_one
    terminal_written = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    executions = []

    def held_finally(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        executions.append(result)
        loop.call_soon_threadsafe(terminal_written.set)
        assert release.wait(5)
        return result

    monkeypatch.setattr(NodeExecutionOwner, "run_one", held_finally)
    try:
        await wait_until(lambda: len(central.ready) == 1)
        for cycle in range(2):
            if cycle:
                env.case = second_case(env.case)
            mint_proof(monkeypatch, env.case)  # Fake child envelopes, not native E2E.
            release.clear()
            terminal_written.clear()
            await prepare(gateway, env.case)
            await command(gateway, env.case)
            await asyncio.wait_for(terminal_written.wait(), 2)
            terminal = executions[-1]
            await wait_cursor(owner, terminal.sequence, task)
            assert runtime.producer_pending
            assert len(central.ready) == cycle + 1  # Durable terminal is not producer-finally.
            release.set()
            assert (await runtime.wait_producer()).state == "terminal"
            await wait_until(lambda: len(central.ready) == cycle + 2)
            assert central.ready[-1].through_sequence == terminal.sequence
            assert central.ready[-1].through_receipt_sha256 == terminal.digest
        assert len(executions) == 2 and len(central.resumes) == 1
        assert [r.state for r in central.receipts] == ["prepared", "effect-intent", "terminal"] * 2
    finally:
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_pending_preparation_then_rejection_starts_new_ready_cycle_without_effect(env, monkeypatch):
    import threading

    from audiagentic.components.agents.gateway.node.contracts import invalid
    from audiagentic.components.agents.gateway.node.local_preparation import NodeLocalPreparer
    from audiagentic.components.agents.gateway.node.work_protocol import PreparationRejected

    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    sender = NodeReceiptSender(runtime)
    task = asyncio.create_task(sender.run(node))
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def reject(self, **kwargs):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        raise invalid(1, "Preparation rejected")

    monkeypatch.setattr(NodeLocalPreparer, "prepare", reject)
    pending = None
    try:
        await wait_until(lambda: len(central.ready) == 1)
        pending = asyncio.create_task(prepare(gateway, env.case))
        await asyncio.wait_for(entered.wait(), 2)
        assert not await runtime.emit_receipt_ready(node, await asyncio.to_thread(owner.receipt_checkpoint))
        assert len(central.ready) == 1
        release.set()
        _, _, reply = await pending
        assert type(reply) is PreparationRejected
        await wait_until(lambda: len(central.ready) == 2)
        assert central.ready[-1].through_sequence == 0 and not central.receipts
        assert not runtime.producer_pending
    finally:
        release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_replacement_drain_and_sender_cancellation_do_not_advertise_or_replay_effect(env, monkeypatch):
    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    first = asyncio.create_task(NodeReceiptSender(runtime).run(node))
    newer = new_gateway = None
    second = None
    try:
        await wait_until(lambda: len(central.ready) == 1)
        newer, new_gateway, _ = await pair(runtime, generation=2, capability="drain")
        drain = Central(owner)
        drain.attach(new_gateway)
        second = asyncio.create_task(NodeReceiptSender(runtime).run(newer))
        await wait_until(lambda: len(drain.resumes) == 1)
        checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
        assert not await runtime.emit_receipt_ready(node, checkpoint)
        assert not await runtime.emit_receipt_ready(newer, checkpoint)
        await asyncio.wait_for(first, 2)
        await stop_sender(second)
        assert not newer._task.done() and not runtime.producer_pending
        assert not drain.ready and not drain.receipts
        assert len(central.ready) == 1
    finally:
        await stop_sender(first)
        if second is not None:
            await stop_sender(second)
        await close(node, gateway)
        if newer is not None:
            await close(newer, new_gateway)


@pytest.mark.asyncio
async def test_ready_snapshot_offloop_rechecks_prepare_acceptance_and_connection_replacement(env, monkeypatch):
    import threading

    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    original = NodeExecutionOwner.snapshot
    first = True

    def snapshot(self):
        nonlocal first
        assert threading.get_ident() != loop_thread
        if first:
            first = False
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
        return original(self)

    monkeypatch.setattr(NodeExecutionOwner, "snapshot", snapshot)
    ready = asyncio.create_task(runtime.emit_receipt_ready(node, checkpoint))
    newer = new_gateway = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await prepare(gateway, env.case)  # Admission progresses while snapshot I/O is blocked.
        newer, new_gateway, _ = await pair(runtime, generation=2)
        release.set()
        assert not await ready
        assert not central.ready
        current = Central(owner)
        current.attach(new_gateway)
        assert await runtime.emit_receipt_ready(newer, checkpoint)
        await wait_until(lambda: len(current.ready) == 1)
        assert not await runtime.emit_receipt_ready(node, checkpoint)
        assert not await runtime.emit_receipt_ready(newer, checkpoint)
    finally:
        release.set()
        await asyncio.gather(ready, return_exceptions=True)
        await close(node, gateway)
        if newer is not None:
            await close(newer, new_gateway)


@pytest.mark.asyncio
async def test_ready_bounded_send_serializes_prepare_but_holds_no_owner_io_lock(env, monkeypatch):
    owner, runtime, calls = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    entered, release = asyncio.Event(), asyncio.Event()
    original = node.send_work

    async def held(kind, payload, **kwargs):
        if payload.get("kind") == "receipt-ready":
            entered.set()
            await release.wait()
        return await original(kind, payload, **kwargs)

    monkeypatch.setattr(node, "send_work", held)
    checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
    ready = asyncio.create_task(runtime.emit_receipt_ready(node, checkpoint))
    pending = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending = asyncio.create_task(prepare(gateway, env.case))
        before = node._received_sequence
        await gateway.heartbeat()
        await wait_until(lambda: node._received_sequence > before)
        snapshot = await asyncio.wait_for(asyncio.to_thread(owner.snapshot), 2)
        assert not snapshot.capacity_blocked and not calls
        release.set()
        assert await ready
        await pending
        await wait_until(lambda: len(central.ready) == 1)
        assert len(calls) == 1
        assert not await runtime.emit_receipt_ready(node, checkpoint)  # Accepted preparation owns the slot.
    finally:
        release.set()
        await asyncio.gather(ready, return_exceptions=True)
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_worker_error_acknowledged_intent_does_not_advertise_readiness(env, monkeypatch):
    owner, runtime, _ = setup(env, monkeypatch)
    entered, release, native_calls = worker_io(env, monkeypatch, fail=True)
    node, gateway, _ = await pair(runtime)
    central = Central(owner)
    central.attach(gateway)
    task = asyncio.create_task(NodeReceiptSender(runtime, poll_interval_seconds=0.005).run(node))
    try:
        await wait_until(lambda: len(central.ready) == 1)
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 2)
        assert await runtime.wait_producer() is None
        await wait_cursor(owner, 2, task)
        checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
        assert not await runtime.emit_receipt_ready(node, checkpoint)
        assert len(central.ready) == 1 and len(native_calls) == 1
        assert (await asyncio.to_thread(owner.snapshot)).capacity_blocked
        assert not central.terminal.is_set()
    finally:
        release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        await stop_sender(task)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_effect_authorization_wait_is_outside_admission_gate_and_suppresses_ready(env, monkeypatch):
    owner, runtime, _ = setup(env, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    async def authorize(gateway, frame, message):
        entered.set()
        await release.wait()
        await gateway.send_work("effect-authorized", {
            "identity": message.identity.to_mapping(),
            "authorization-request-id": frame.message_id,
            "authorization-id": "grant", "authorized": True,
        })

    worker_entered, worker_release, calls = worker_io(env, monkeypatch)
    node, gateway, _ = await pair(runtime, authorize=authorize)
    central = Central(owner)
    central.attach(gateway)
    sender = asyncio.create_task(NodeReceiptSender(runtime, poll_interval_seconds=0.005).run(node))
    try:
        await wait_until(lambda: len(central.ready) == 1)
        await prepare(gateway, env.case)
        await command(gateway, env.case)
        await asyncio.wait_for(entered.wait(), 2)
        checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
        assert not runtime._admission_gate.locked()
        assert not await asyncio.wait_for(runtime.emit_receipt_ready(node, checkpoint), 2)
        assert not calls and len(central.ready) == 1
        before = node._received_sequence
        await gateway.heartbeat()
        await wait_until(lambda: node._received_sequence > before)
        release.set()
        await asyncio.wait_for(worker_entered.wait(), 2)
        terminal = await runtime.wait_producer()
        await wait_cursor(owner, terminal.sequence, sender)
        await wait_until(lambda: len(central.ready) == 2)
        assert len(calls) == 1
    finally:
        release.set()
        worker_release.set()
        if runtime.producer_pending:
            await runtime.wait_producer()
        await stop_sender(sender)
        await close(node, gateway)


@pytest.mark.asyncio
async def test_cancel_during_ready_send_does_not_repeat_hint_or_cancel_receiver(env, monkeypatch):
    owner, runtime, _ = setup(env, monkeypatch)
    node, gateway, _ = await pair(runtime)
    entered = asyncio.Event()
    attempts = []

    async def held(kind, payload, **kwargs):
        assert payload["kind"] == "receipt-ready"
        attempts.append(payload)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(node, "send_work", held)
    checkpoint = await asyncio.to_thread(owner.receipt_checkpoint)
    task = asyncio.create_task(runtime.emit_receipt_ready(node, checkpoint))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await stop_sender(task)
        assert not runtime._admission_gate.locked()
        runtime.state_changed_event.set()
        assert not await runtime.emit_receipt_ready(node, checkpoint)
        assert len(attempts) == 1 and not runtime.producer_pending
        assert not node._task.done()
    finally:
        await stop_sender(task)
        await close(node, gateway)
