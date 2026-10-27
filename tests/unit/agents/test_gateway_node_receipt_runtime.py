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
