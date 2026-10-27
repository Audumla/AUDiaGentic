"""Real channel/canonical custody; fake preparation, no native execution proof."""
import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node import checkpoints as checkpoint_module
from audiagentic.components.agents.gateway.node.checkpoints import NodeReceiptCheckpoints
from audiagentic.components.agents.gateway.node.connection import NodeConnection
from audiagentic.components.agents.gateway.node.receipt_runtime import NodeReceiptRuntime
from audiagentic.components.agents.gateway.node.receipts import Receipt
from audiagentic.components.agents.gateway.node.work_protocol import (
    ReceiptAckWork,
    ReceiptResumeReply,
    ReceiptWork,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_node_admission_owner import admission as admission
from .test_gateway_node_runner import PairedSocket, effects, invoke
from .test_gateway_node_runner import case as case


@pytest_asyncio.fixture
async def ingress(case):
    await invoke(case)
    current = await effects(case)
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections)
    case.receipt_runtime = runtime
    acknowledgements, arrived = [], asyncio.Event()
    async def receive(frame, work):
        assert type(work) is ReceiptAckWork
        acknowledgements.append(work)
        arrived.set()
    case.central_work_handler = runtime.handle_work
    case.node_work_handler = receive
    return case, runtime, current, str(uuid4()), acknowledgements, arrived


async def send(ingress, state="prepared", sequence=1, *, identity=None, digest=None):
    case, _, _, log, _, _ = ingress
    command = identity or case.commands[0].identity
    receipt = Receipt(command, state, sequence, digest)
    await case.node.send_work("receipt", {"log-incarnation-id": log, "receipt": receipt.public_payload()})
    return receipt


async def ack(ingress):
    await asyncio.wait_for(ingress[-1].wait(), 3)
    ingress[-1].clear()
    return ingress[-2][-1]


def checkpoint(ingress):
    case, runtime, _, _, _, _ = ingress
    return runtime._streams[case.gateway.identity.node_id][1]


@pytest.mark.asyncio
async def test_authenticated_resume_receipt_commit_and_actual_ack(ingress):
    case, runtime, original, log, _, _ = ingress
    _, _, cursor = await case.node.request_work("reconcile", {
        "kind": "receipt-resume", "log-incarnation-id": log,
        "through-sequence": 0, "through-receipt-sha256": None,
    }, reply_types=(ReceiptResumeReply,), timeout=3)
    assert cursor.after_sequence == 0 and cursor.after_receipt_sha256 is None
    assert not checkpoint(ingress).path.exists()
    receipt = await send(ingress)
    result = await ack(ingress)
    assert result.through_sequence == 1 and result.through_receipt_sha256 == receipt.digest
    current = store.read_record(case.admission.root, original["request-id"])
    assert current["node-dispatch"]["receipt-sha256"] == receipt.digest
    assert current["state"] == "running" and runtime.custody_changed.is_set()
    _, _, cursor = await case.node.request_work("reconcile", {
        "kind": "receipt-resume", "log-incarnation-id": log,
        "through-sequence": 0, "through-receipt-sha256": None,
    }, reply_types=(ReceiptResumeReply,), timeout=3)
    assert cursor.after_sequence == 1 and cursor.after_receipt_sha256 == receipt.digest


@pytest.mark.asyncio
async def test_older_duplicate_returns_cumulative_ack_without_resolving_untrusted_body(ingress, monkeypatch):
    case, runtime, original, _, _, _ = ingress
    await send(ingress)
    await ack(ingress)
    second = await send(ingress, "effect-intent", 2)
    await ack(ingress)
    def forbidden(*args):
        pytest.fail("older duplicate cannot resolve or publish its supplied identity")
    monkeypatch.setattr(runtime, "_target", forbidden)
    await send(ingress, identity=replace(case.commands[0].identity, request_id="missing", command_id="missing"))
    result = await ack(ingress)
    assert result.through_sequence == 2 and result.through_receipt_sha256 == second.digest
    assert store.read_record(case.admission.root, original["request-id"])["node-dispatch"]["receipt-sequence"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before", "after-precheck", "after-custody"])
async def test_replacement_boundary_never_sends_stale_ack(ingress, monkeypatch, when):
    case, runtime, original, log, acknowledgements, _ = ingress
    def replaced():
        case.connections.replace("node", "new-boot", case.gateway.websocket)
    if when == "before":
        await asyncio.to_thread(replaced)
        work = ReceiptWork(message_id="message", sequence=1, log_incarnation_id=log,
            receipt=Receipt(case.commands[0].identity, "prepared", 1))
        with pytest.raises(AudiaGenticError, match="no longer current"):
            await asyncio.to_thread(runtime._accept, case.gateway, work)
    else:
        target = NodeReceiptCheckpoints if when == "after-precheck" else runtime
        name = "accept" if when == "after-precheck" else "_accept"
        original_method = getattr(target, name)
        def racing(*args, **kwargs):
            if when == "after-precheck":
                replaced()
            result = original_method(*args, **kwargs)
            if when == "after-custody":
                replaced()
            return result
        monkeypatch.setattr(target, name, racing)
        await send(ingress)
        await asyncio.wait_for(case.gateway.wait_closed(), 3)
    assert not acknowledgements
    current = store.read_record(case.admission.root, original["request-id"])
    assert current["node-dispatch"]["receipt-sequence"] == (0 if when == "before" else 1)
    assert current["state"] == "running" and len(case.commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["canonical", "cursor"])
async def test_custody_persistence_failure_never_sends_ack_or_fails_native_request(ingress, monkeypatch, fault):
    case, _, original, _, acknowledgements, _ = ingress
    def fail(*args, **kwargs):
        raise OSError("PRIVATE persistence fault")
    if fault == "canonical":
        monkeypatch.setattr(checkpoint_module.request_store, "apply_owned_node_receipt", fail)
    else:
        monkeypatch.setattr(checkpoint_module, "atomic_write_json", fail)
    await send(ingress)
    await asyncio.wait_for(case.gateway.wait_closed(), 3)
    assert not acknowledgements and not checkpoint(ingress).path.exists()
    current = store.read_record(case.admission.root, original["request-id"])
    assert current["state"] == "running"
    assert current["node-dispatch"]["receipt-sequence"] == (0 if fault == "canonical" else 1)
    if fault == "cursor":
        with pytest.raises(AudiaGenticError, match="uncertain"):
            checkpoint(ingress).resume_cursor(log_incarnation_id=ingress[3], expected_epoch="owner")


@pytest.mark.asyncio
async def test_drain_allows_original_custody_without_renewing_revoked_grant(ingress):
    from audiagentic.components.agents.gateway.node.drain import NodeDrainEligibility
    case, _, original, _, _, _ = ingress
    case.connections.drain_eligibility = NodeDrainEligibility(case.config, case.admission.service)
    await asyncio.to_thread(case.admission.authority.revoke, "node", expected_grant_revision=1)
    await asyncio.to_thread(case.connections.refresh_capability, "node")
    await case.gateway.notify_drain(2)
    receipt = await send(ingress)
    result = await ack(ingress)
    assert result.through_receipt_sha256 == receipt.digest
    assert store.read_record(case.admission.root, original["request-id"])["state"] == "running"
    assert len(case.commands) == 1


@pytest.mark.asyncio
async def test_receipt_storage_runs_off_loop_and_trace_failure_does_not_undo_custody(ingress, monkeypatch):
    case, _, original, _, _, _ = ingress
    from audiagentic.components.agents.gateway.node import receipt_runtime as module
    original_accept, calls = NodeReceiptCheckpoints.accept, []
    def checked(*args, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        calls.append(True)
        return original_accept(*args, **kwargs)
    monkeypatch.setattr(NodeReceiptCheckpoints, "accept", checked)
    def failed(*args, **kwargs):
        raise OSError("PRIVATE diagnostic failure")
    # Exercise the emitter's real fault boundary, not a throwing fake emitter.
    monkeypatch.setattr(module.store, "record_gateway_timeline", failed)
    receipt = await send(ingress)
    assert (await ack(ingress)).through_receipt_sha256 == receipt.digest
    assert calls and store.read_record(case.admission.root, original["request-id"])["node-dispatch"]["receipt-sequence"] == 1


@pytest.mark.asyncio
async def test_unknown_log_never_resets_existing_custody(ingress):
    case, _, _, _, _, _ = ingress
    await send(ingress)
    await ack(ingress)
    before = checkpoint(ingress).path.read_bytes()
    with pytest.raises(Exception):
        await case.node.request_work("reconcile", {
            "kind": "receipt-resume", "log-incarnation-id": str(uuid4()),
            "through-sequence": 0, "through-receipt-sha256": None,
        }, reply_types=(ReceiptResumeReply,), timeout=3)
    assert checkpoint(ingress).path.read_bytes() == before


@pytest.mark.asyncio
async def test_gap_no_ack_preserves_registered_causal_reason_in_service_timeline(ingress):
    from audiagentic.foundation.io import iter_ndjson
    case, _, original, _, acknowledgements, _ = ingress
    await send(ingress, sequence=2)
    await asyncio.wait_for(case.gateway.wait_closed(), 3)
    assert not acknowledgements
    events = list(iter_ndjson(case.admission.service.timeline_path))
    errors = [e for e in events if e["event"] == "node.receipt-ingress-deferred"]
    assert errors[-1]["attributes"]["reason-code"] == "receipt-stream-gap"
    assert errors[-1]["attributes"]["receipt-sequence"] == 2
    assert store.read_record(case.admission.root, original["request-id"])["node-dispatch"]["receipt-sequence"] == 0


@pytest.mark.asyncio
async def test_owner_takeover_rejects_old_custody_without_mutation(ingress):
    from audiagentic.foundation.io import iter_ndjson
    case, _, original, _, acknowledgements, _ = ingress
    from .test_gateway_node_checkpoints import _restart
    await asyncio.to_thread(_restart, case.admission.service, "new-owner")
    await send(ingress)
    await asyncio.wait_for(case.gateway.wait_closed(), 3)
    assert not acknowledgements and not checkpoint(ingress).path.exists()
    assert store.read_record(case.admission.root, original["request-id"])["node-dispatch"]["receipt-sequence"] == 0
    errors = [e for e in iter_ndjson(case.admission.service.timeline_path)
              if e["event"] == "node.receipt-ingress-deferred"]
    assert errors[-1]["attributes"]["reason-code"] == "owner-fence-changed"


@pytest.mark.asyncio
async def test_new_connection_reconciles_committed_old_command_without_rebinding(ingress):
    case, runtime, original, log, _, _ = ingress
    first = await send(ingress)
    await ack(ingress)
    await case.gateway.close()
    a, b = PairedSocket(), PairedSocket()
    a.peer, b.peer = b, a
    slot, _ = await asyncio.to_thread(case.connections.replace, "node", "new-boot", a)
    async def current():
        return await asyncio.to_thread(case.connections.is_current, slot)
    gateway = NodeConnection(a, slot.identity, role="gateway", grant_revision=1, capability="active", current=current)
    node = NodeConnection(b, slot.identity, role="node", grant_revision=1, capability="active")
    await asyncio.to_thread(case.connections.attach, slot, gateway)
    received, ready = [], asyncio.Event()
    async def receive(frame, work):
        received.append(work)
        ready.set()
    gateway.enable_work(lambda frame, work: runtime.handle_work(gateway, frame, work), max_artifact_bytes=1024 * 1024)
    node.enable_work(receive, max_artifact_bytes=1024 * 1024)
    gateway.start()
    node.start()
    try:
        _, _, cursor = await node.request_work("reconcile", {
            "kind": "receipt-resume", "log-incarnation-id": log,
            "through-sequence": 0, "through-receipt-sha256": None,
        }, reply_types=(ReceiptResumeReply,), timeout=3)
        assert cursor.after_sequence == 1 and cursor.after_receipt_sha256 == first.digest
        # Original command identity stays on boot1; outer envelope is boot2/G2.
        await node.send_work("receipt", {"log-incarnation-id": log, "receipt": first.public_payload()})
        await asyncio.wait_for(ready.wait(), 3)
        assert received[-1].through_receipt_sha256 == first.digest
        record = store.read_record(case.admission.root, original["request-id"])
        assert record["node-dispatch"]["identity"] == first.identity.to_mapping()
        assert record["worker-id"] == original["worker-id"] and record["attempt-epoch"] == original["attempt-epoch"]
        assert len(case.commands) == 1
    finally:
        await gateway.close()
        await node.close()

# Readiness remains a scheduling hint. These are real owner/cursor/channel
# validations with fake node execution; no native readiness proof is claimed.
async def ready(runtime, connection, log, sequence=0, digest=None, *, frame_changes=None, work_override=None):
    from audiagentic.components.agents.gateway.node.contracts import Frame
    from audiagentic.components.agents.gateway.node.work_protocol import parse_work_frame
    values = dict(version=1, type="reconcile", message_id="ready-message",
        node_id=connection.identity.node_id, node_epoch=connection.identity.node_epoch,
        gateway_owner_epoch=connection.identity.gateway_owner_epoch, sequence=1,
        payload={"kind": "receipt-ready", "connection-generation": connection.identity.connection_generation,
                 "log-incarnation-id": log, "through-sequence": sequence, "through-receipt-sha256": digest})
    values.update(frame_changes or {})
    frame = Frame(**values)
    work = parse_work_frame(frame, role="gateway", current_connection=connection.identity,
                            capability=connection.capability, max_artifact_bytes=1024*1024)
    return await runtime.handle_work(connection, frame, work if work_override is None else work_override)


def open_socket(case):
    from websockets.protocol import State
    assert case.gateway.websocket.state is State.OPEN
    # The shared runner fixture now performs a real startup ready handshake.
    # Consume its hint so each readiness test starts at its own transition.
    case.admission.authority.serialize(lambda: case.connections.consume_ready(case.gateway, grant_revision=1))


def is_ready(case):
    return case.admission.authority.serialize(lambda: case.connections.is_ready(case.gateway, grant_revision=1))


@pytest.mark.asyncio
async def test_zero_custody_ready_is_idempotent_no_cursor_no_reply_and_offloop_notification(case):
    open_socket(case)
    calls = []
    def notified(node):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        # These acquisitions prove notification is outside both owner locks.
        with case.admission.service.owner_guard("owner"):
            assert case.admission.authority.serialize(lambda: is_current_unlocked())
        calls.append(node)
    def is_current_unlocked():
        return case.connections.current_slot("node").connection is case.gateway
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections, on_node_changed=notified)
    log = str(uuid4())
    before = case.node.websocket.incoming.qsize()
    assert await ready(runtime, case.gateway, log) is None
    assert await asyncio.to_thread(is_ready, case)
    assert calls == ["node"] and runtime.custody_changed.is_set()
    runtime.custody_changed.clear()
    assert await ready(runtime, case.gateway, log) is None
    assert calls == ["node"] and not runtime.custody_changed.is_set()
    assert case.node.websocket.incoming.qsize() == before
    assert not runtime._streams["node"][1].path.exists()


@pytest.mark.asyncio
async def test_ready_actual_envelope_after_terminal_custody(ingress):
    case, runtime, _, log, _, _ = ingress
    open_socket(case)
    calls, notified = [], asyncio.Event()
    loop = asyncio.get_running_loop()
    def notify(node):
        calls.append(node)
        loop.call_soon_threadsafe(notified.set)
    runtime.on_node_changed = notify
    receipt = await send(ingress, "terminal", 1, digest="a"*64)
    await ack(ingress)
    await asyncio.wait_for(notified.wait(), 3)
    calls.clear()
    notified.clear()
    runtime.custody_changed.clear()
    before = checkpoint(ingress).path.read_bytes()
    case.central_work_handler = runtime.handle_work
    await case.node.send_work("reconcile", {"kind": "receipt-ready", "log-incarnation-id": log,
        "through-sequence": 1, "through-receipt-sha256": receipt.digest})
    await asyncio.wait_for(runtime.custody_changed.wait(), 3)
    # Callback runs after the transition; wait on the owner, not arbitrary sleeps.
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(.01)
    assert calls == ["node"] and await asyncio.to_thread(is_ready, case)
    assert checkpoint(ingress).path.read_bytes() == before
    assert case.gateway.failure is None and len(case.commands) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["cursor-mismatch", "missing", "unreadable", "different-log"])
async def test_ready_refuses_unproven_custody(ingress, fault):
    case, runtime, _, log, _, _ = ingress
    open_socket(case)
    receipt = await send(ingress)
    await ack(ingress)
    cursor = checkpoint(ingress)
    sequence, digest = 1, receipt.digest
    if fault == "cursor-mismatch":
        digest, reason = "b"*64, "receipt-cursor-mismatch"
    elif fault == "missing":
        cursor.path.unlink()
        reason = "receipt-cursor-mismatch"
    elif fault == "unreadable":
        cursor.path.write_text("{invalid", encoding="utf-8")
        reason = "receipt-cursor-unreadable"
    elif fault == "different-log":
        log, reason = str(uuid4()), "receipt-log-changed"
    unchanged = cursor.path.read_bytes() if cursor.path.exists() else None
    with pytest.raises(AudiaGenticError) as error:
        await ready(runtime, case.gateway, log, sequence, digest)
    assert error.value.details["reason-code"] == reason
    assert not await asyncio.to_thread(is_ready, case)
    assert (cursor.path.read_bytes() if cursor.path.exists() else None) == unchanged


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["replacement", "grant", "owner"])
async def test_ready_final_publication_revalidates_after_cursor_without_nested_guard(case, monkeypatch, race):
    open_socket(case)
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections)
    original = NodeReceiptCheckpoints.resume_cursor
    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        # Original resume has released its service guard. These operations
        # acquire the existing locks rather than simulating a returned bool.
        if race == "replacement":
            case.connections.replace("node", "replacement", case.gateway.websocket)
        elif race == "grant":
            case.admission.authority.revoke("node", expected_grant_revision=1)
        elif race == "owner":
            from .test_gateway_node_checkpoints import _restart
            _restart(case.admission.service, "new-owner")
        return result
    monkeypatch.setattr(NodeReceiptCheckpoints, "resume_cursor", racing)
    with pytest.raises(AudiaGenticError) as error:
        await ready(runtime, case.gateway, str(uuid4()))
    assert error.value.details["reason-code"] == {
        "replacement": "receipt-channel-replaced", "grant": "ready-channel-invalid",
        "owner": "owner-fence-changed",
    }[race]
    assert not await asyncio.to_thread(is_ready, case)
    assert not runtime._streams["node"][1].path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["drain", "grant-revision", "closed", "stale-generation", "forged-work"])
async def test_ready_requires_actual_current_active_channel(case, fault):
    open_socket(case)
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections)
    log = str(uuid4())
    options = {}
    if fault == "drain":
        case.gateway.capability = "drain"
    elif fault == "grant-revision":
        case.gateway.grant_revision = 2
    elif fault == "closed":
        await case.gateway.close()
    elif fault == "stale-generation":
        options["frame_changes"] = {"payload": {"kind": "receipt-ready", "connection-generation": 99,
            "log-incarnation-id": log, "through-sequence": 0, "through-receipt-sha256": None}}
    else:
        from audiagentic.components.agents.gateway.node.work_protocol import ReceiptReady
        options["work_override"] = ReceiptReady(message_id="different", sequence=1,
            log_incarnation_id=log, through_sequence=0, through_receipt_sha256=None)
    with pytest.raises(AudiaGenticError):
        await ready(runtime, case.gateway, log, **options)
    assert not await asyncio.to_thread(is_ready, case)


@pytest.mark.asyncio
async def test_notification_fault_does_not_undo_ack_custody_or_ready(ingress):
    from audiagentic.foundation.io import iter_ndjson
    case, runtime, _, log, _, _ = ingress
    open_socket(case)
    calls = []
    def failed(node):
        calls.append(node)
        raise OSError("PRIVATE callback credential")
    runtime.on_node_changed = failed
    terminal = await send(ingress, "terminal", 1, digest="a"*64)
    assert (await ack(ingress)).through_receipt_sha256 == terminal.digest
    await ready(runtime, case.gateway, log, 1, terminal.digest)
    assert await asyncio.to_thread(is_ready, case)
    assert calls == ["node", "node"]
    events = [e for e in iter_ndjson(case.admission.service.timeline_path)
              if e["event"] == "node.receipt-ingress-deferred"]
    assert len([e for e in events if e["attributes"]["reason-code"] == "node-notification-failed"]) == 2
    assert "PRIVATE" not in case.admission.service.timeline_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_notification_only_on_new_custody_not_duplicate_or_resume(ingress):
    case, runtime, _, log, _, _ = ingress
    calls = []
    runtime.on_node_changed = calls.append
    await send(ingress)
    await ack(ingress)
    await send(ingress)
    await ack(ingress)
    await case.node.request_work("reconcile", {"kind": "receipt-resume", "log-incarnation-id": log,
        "through-sequence": 0, "through-receipt-sha256": None}, reply_types=(ReceiptResumeReply,), timeout=3)
    assert calls == ["node"]


@pytest.mark.asyncio
async def test_ready_notification_secondary_trace_fault_is_best_effort(case, monkeypatch):
    open_socket(case)
    def fail(*args):
        raise OSError("PRIVATE sink fault")
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections, on_node_changed=fail)
    monkeypatch.setattr(runtime, "_trace_failure", fail)
    assert await ready(runtime, case.gateway, str(uuid4())) is None
    assert await asyncio.to_thread(is_ready, case)


@pytest.mark.asyncio
async def test_committed_custody_notifies_even_if_replacement_suppresses_ack(ingress, monkeypatch):
    case, runtime, _, _, acknowledgements, _ = ingress
    calls = []
    runtime.on_node_changed = calls.append
    original = runtime._accept
    def replace_after_commit(*args):
        result = original(*args)
        case.connections.replace("node", "new-boot", case.gateway.websocket)
        return result
    monkeypatch.setattr(runtime, "_accept", replace_after_commit)
    await send(ingress)
    await asyncio.wait_for(case.gateway.wait_closed(), 3)
    assert calls == ["node"] and not acknowledgements
    assert checkpoint(ingress).path.exists()


@pytest.mark.asyncio
async def test_notification_dispatch_failure_preserves_ready(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import receipt_runtime as module
    open_socket(case)
    runtime = NodeReceiptRuntime(case.config, case.admission.service, case.connections)
    original, attempts = asyncio.to_thread, []
    async def dispatch(function, *args, **kwargs):
        if function == runtime._notify:
            attempts.append(True)
            raise RuntimeError("PRIVATE executor submission failure")
        return await original(function, *args, **kwargs)
    monkeypatch.setattr(module.asyncio, "to_thread", dispatch)
    assert await ready(runtime, case.gateway, str(uuid4())) is None
    assert attempts == [True] and await original(is_ready, case)


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_failure", [False, True])
async def test_notification_dispatch_failure_preserves_ack_or_primary_error(ingress, monkeypatch, primary_failure):
    from audiagentic.components.agents.gateway.node import receipt_runtime as module
    from audiagentic.components.agents.gateway.node.contracts import Frame, conflict
    from audiagentic.components.agents.gateway.node.work_protocol import parse_work_frame
    case, runtime, _, log, _, _ = ingress
    original, attempts = asyncio.to_thread, []
    async def dispatch(function, *args, **kwargs):
        if function == runtime._notify:
            attempts.append(True)
            raise RuntimeError("PRIVATE executor submission failure")
        return await original(function, *args, **kwargs)
    monkeypatch.setattr(module.asyncio, "to_thread", dispatch)
    if primary_failure:
        def replaced(*args):
            raise conflict(1, "Primary channel failure", reason_code="receipt-channel-replaced")
        # Fail only the post-custody channel check, not receipt admission.
        current = runtime._current
        def check(connection, *, stream=False):
            if not stream:
                return replaced()
            return current(connection, stream=stream)
        monkeypatch.setattr(runtime, "_current", check)
    receipt = Receipt(case.commands[0].identity, "prepared", 1)
    frame = Frame(1, "receipt", "receipt-message", case.gateway.identity.node_id,
        case.gateway.identity.node_epoch, case.gateway.identity.gateway_owner_epoch, 1,
        {"connection-generation": case.gateway.identity.connection_generation,
         "log-incarnation-id": log, "receipt": receipt.public_payload()})
    work = parse_work_frame(frame, role="gateway", current_connection=case.gateway.identity,
                            capability="active", max_artifact_bytes=1024*1024)
    if primary_failure:
        with pytest.raises(AudiaGenticError) as error:
            await runtime.handle_work(case.gateway, frame, work)
        assert error.value.code == "CON-AGND-001"
        assert error.value.details["reason-code"] == "receipt-channel-replaced"
    else:
        assert await runtime.handle_work(case.gateway, frame, work) is not None
        assert (await ack(ingress)).through_receipt_sha256 == receipt.digest
    assert attempts == [True] and checkpoint(ingress).path.exists()


@pytest.mark.asyncio
async def test_ready_retained_while_canonical_capacity_held_then_consumed_after_settlement(ingress):
    from audiagentic.components.agents.gateway.node.contracts import conflict
    from audiagentic.components.agents.gateway.node.occupancy import NodeOccupancy
    case, runtime, original, log, _, _ = ingress
    open_socket(case)
    projection = NodeOccupancy(tuple(case.config.projects.values()), server_id=case.config.server_id)
    assert projection.snapshot().occupied(case.config.server_id, "node")
    before = store.read_record(case.admission.root, original["request-id"])
    assert before["node-dispatch"]["authorization-state"] == "authorized"
    assert await ready(runtime, case.gateway, log) is None
    assert await asyncio.to_thread(is_ready, case)
    assert not checkpoint(ingress).path.exists()
    assert store.read_record(case.admission.root, original["request-id"]) == before

    # The existing admission owners retain capacity authority. A readiness
    # hint cannot bypass occupancy or be consumed by a blocked admission.
    def admit():
        with case.admission.service.owner_guard("owner"):
            if projection.snapshot().occupied(case.config.server_id, "node"):
                raise conflict(1, "Canonical node capacity remains held", reason_code="capacity-occupied")
            return case.admission.authority.serialize(
                lambda: case.connections.consume_ready(case.gateway, grant_revision=1))
    with pytest.raises(AudiaGenticError) as error:
        await asyncio.to_thread(admit)
    assert error.value.details["reason_code"] == "capacity-occupied"
    assert await asyncio.to_thread(is_ready, case)
    terminal = await send(ingress, "terminal", 1, digest="a"*64)
    assert (await ack(ingress)).through_receipt_sha256 == terminal.digest
    settled = store.read_record(case.admission.root, original["request-id"])
    assert settled["node-dispatch"]["authorization-state"] == "terminal"
    assert not projection.snapshot().occupied(case.config.server_id, "node")
    # No second ready frame: the original hint survives canonical settlement.
    assert await asyncio.to_thread(is_ready, case)
    assert await asyncio.to_thread(admit)
    assert not await asyncio.to_thread(is_ready, case)
