"""Finite central dispatch over real channels/stores, explicitly fake node preparation."""
import asyncio
import hashlib
import threading
import traceback
from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio
from websockets.exceptions import ConnectionClosedOK
from websockets.protocol import State

from audiagentic.components.agents.agents_paths import gateway_node_admission_path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.diagnostics import ObservationPhase, classify_error
from audiagentic.components.agents.gateway.node.admission_owner import read_node_admission_snapshot
from audiagentic.components.agents.gateway.node.connection import NodeConnection
from audiagentic.components.agents.gateway.node.diagnostics import sanitize_node_error
from audiagentic.components.agents.gateway.node.preparation import (
    assemble_final_command_payload,
    build_final_command_payload,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.node.receipt_runtime import NodeReceiptRuntime
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore, Receipt
from audiagentic.components.agents.gateway.node.runner import NodeRunner
from audiagentic.components.agents.gateway.node.transport import NodeConnectionOwner
from audiagentic.components.agents.gateway.node.work_protocol import (
    CommandWork,
    EffectAuthorize,
    EffectAuthorized,
    EffectDenied,
    PrepareWork,
    ReceiptReady,
    ReceiptResume,
    ReceiptResumeReply,
)
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_node_admission_owner import admission as admission
from .test_gateway_node_admission_owner import submit


class PairedSocket:
    @property
    def state(self):
        return State.CLOSED if self.closed else State.OPEN

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.peer = None
        self.closed = False
        self.authenticated_credential_sha256 = hashlib.sha256(b"Bearer credential-node").hexdigest()
        self.transport = SimpleNamespace(abort=self.abort)

    async def send(self, raw):
        if self.closed:
            raise ConnectionClosedOK(None, None)
        self.peer.incoming.put_nowait(raw)

    async def recv(self):
        raw = await self.incoming.get()
        if raw is None:
            raise ConnectionClosedOK(None, None)
        return raw

    def abort(self):
        for socket in (self, self.peer):
            if not socket.closed:
                socket.closed = True
                socket.incoming.put_nowait(None)

    async def close(self, **kwargs):
        self.abort()


@pytest_asyncio.fixture
async def case(admission):
    record = await asyncio.to_thread(submit, admission)
    record = await asyncio.to_thread(store.claim_dispatch, admission.root, record["request-id"],
        owner_epoch="owner", expected_revision=record["revision"], service_root=admission.service.root)
    record = await asyncio.to_thread(store.start_owned_attempt, admission.root, record["request-id"],
        owner_epoch="owner", worker_id="queue-worker", expected_revision=record["revision"])
    config = await asyncio.to_thread(load_shared_server_config, admission.config_path)
    connections = NodeConnectionOwner(admission.authority, "owner")
    a, b = PairedSocket(), PairedSocket()
    a.peer, b.peer = b, a
    assert await asyncio.to_thread(connections.authenticate, "Bearer credential-node") == "node"
    slot, _ = await asyncio.to_thread(connections.replace, "node", "boot", a)

    async def current():
        return await asyncio.to_thread(connections.is_current, slot)

    gateway = NodeConnection(a, slot.identity, role="gateway", grant_revision=1, capability="active", current=current)
    node = NodeConnection(b, slot.identity, role="node", grant_revision=1, capability="active")
    await asyncio.to_thread(connections.attach, slot, gateway)
    value = SimpleNamespace(admission=admission, record=record, config=config, connections=connections,
        slot=slot, gateway=gateway, node=node, prepares=[], commands=[], effects=[],
        effect_requests=[],
        central_work_handler=None, node_work_handler=None,
        effect_identity=None,
        reject_code=None,
        prepared_hook=None, command_hook=None, ignore_prepare=False, preparation=None,
        effect_done=threading.Event())
    runner = NodeRunner(config, admission.service, admission.authority, connections, asyncio.get_running_loop(), timeout=0.5)
    value.runner = runner
    value.receipt_runtime = NodeReceiptRuntime(config, admission.service, connections)
    value.node_receipts = await asyncio.to_thread(NodeReceiptStore, node_id="node", node_epoch="boot",
        gateway_owner_epoch="owner", root=admission.root.parent / "fixture-node-receipts")
    value.ready_received = asyncio.Event()

    async def central(frame, work):
        if type(work) is EffectAuthorize:
            await runner.handle_effect_authorize(gateway, frame, work)
        elif type(work) is ReceiptReady or (type(work) is ReceiptResume and value.central_work_handler is None):
            await value.receipt_runtime.handle_work(gateway, frame, work)
            if type(work) is ReceiptReady:
                value.ready_received.set()
        else:
            assert value.central_work_handler is not None
            await value.central_work_handler(gateway, frame, work)

    async def fake_recipient(frame, work):
        if type(work) is PrepareWork:
            value.prepares.append(work)
            if value.ignore_prepare:
                return
            if value.reject_code is not None:
                await node.send_work("reconcile-result", {"kind": "prepare-rejected", "in-reply-to": work.message_id,
                                                         "code": value.reject_code})
                return
            value.preparation = prepare_node_command(
                binding=work.binding, semantic=work.semantic, raw_prompt=work.raw_prompt,
                rendered_prompt="FAKE provider render", manifest_id="fake-manifest",
                context_fingerprint="e" * 64, runtime_digest="f" * 64, provider_manifest=b"FAKE manifest",
                worker_id=work.worker_id, attempt_epoch=work.attempt_epoch, provider_id="provider",
                model_id="fake-model", model_alias=None,
            )
            if value.prepared_hook:
                await asyncio.to_thread(value.prepared_hook)
            await node.send_work("reconcile-result", {"kind": "prepared", "in-reply-to": work.message_id,
                                                     "attestation": value.preparation.attestation.to_mapping()})
        elif type(work) is CommandWork:
            value.commands.append(work)
            if value.command_hook:
                await asyncio.to_thread(value.command_hook)
            requested = value.effect_identity(work.identity) if value.effect_identity else work.identity
            sent, _, reply = await node.request_work("effect-authorize", {"identity": requested.to_mapping()},
                                                   reply_types=(EffectAuthorized, EffectDenied), timeout=2)
            value.effect_requests.append(sent)
            value.effects.append(reply)
            value.effect_done.set()
        else:
            assert value.node_work_handler is not None
            await value.node_work_handler(frame, work)

    gateway.enable_work(central, max_artifact_bytes=1024 * 1024)
    node.enable_work(fake_recipient, max_artifact_bytes=1024 * 1024)
    gateway.start()
    node.start()
    try:
        await announce_ready(value)
        yield value
    finally:
        await gateway.close()
        await node.close()


async def announce_ready(case):
    """Real zero-row resume/readiness ingress; no native execution is implied."""
    checkpoint = await asyncio.to_thread(case.node_receipts.ack_checkpoint)
    assert checkpoint.through_sequence == 0 and checkpoint.through_receipt_sha256 is None
    case.ready_received.clear()
    await case.node.request_work("reconcile", {"kind": "receipt-resume",
        "log-incarnation-id": checkpoint.log_incarnation_id, "through-sequence": 0,
        "through-receipt-sha256": None}, reply_types=(ReceiptResumeReply,), timeout=2)
    await case.node.send_work("reconcile", {"kind": "receipt-ready",
        "log-incarnation-id": checkpoint.log_incarnation_id, "through-sequence": 0,
        "through-receipt-sha256": None})
    await asyncio.wait_for(case.ready_received.wait(), 2)


async def invoke(case, **kwargs):
    with pytest.raises(RecoveryDeferred) as caught:
        await asyncio.to_thread(case.runner, case.admission.root, case.record, **kwargs)
    return caught.value


async def effects(case):
    assert await asyncio.to_thread(case.effect_done.wait, 3)
    return store.read_record(case.admission.root, case.record["request-id"])


@pytest.mark.asyncio
async def test_fresh_flow_binds_and_authorizes_exact_queue_attempt_without_claiming_completion(case):
    assert await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.is_ready(case.gateway, grant_revision=1))
    deferred = await invoke(case)
    current = await effects(case)
    assert deferred.side_effect_state == "may-have-started"
    assert len(case.prepares) == len(case.commands) == len(case.effects) == 1
    assert type(case.effects[0]) is EffectAuthorized
    assert case.effects[0].authorization_request_id == case.effect_requests[0].message_id
    assert current["node-dispatch"]["authorization-id"] == case.effects[0].authorization_id
    assert current["worker-id"] == "queue-worker" and current["attempt-epoch"] == 1
    assert current["state"] == "running"
    assert not await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.is_ready(case.gateway, grant_revision=1))
    assert case.preparation.attestation.binding == case.prepares[0].binding
    assert assemble_final_command_payload(case.preparation.attestation, case.prepares[0].raw_prompt) == build_final_command_payload(case.preparation, case.prepares[0].raw_prompt)
    # Canonical binding is never an invitation to resend, even with omitted keyword.
    await invoke(case)
    await invoke(case, reconcile_only=True)
    assert len(case.prepares) == len(case.commands) == 1


@pytest.mark.asyncio
async def test_public_admission_reader_needs_no_source_credential_or_foreign_root_resolution(case):
    snapshot = await asyncio.to_thread(read_node_admission_snapshot, case.admission.root, case.record)
    assert snapshot.caller_root == "/foreign/worktree-not-on-server"
    assert "credential-node" not in snapshot._bytes.decode()
    assert snapshot.raw_prompt not in repr(snapshot)
    assert snapshot.caller_root not in repr(snapshot)


@pytest.mark.asyncio
async def test_no_live_slot_is_positive_null_bind_defer(case):
    await asyncio.to_thread(case.connections.remove, case.slot)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert deferred.phase == ObservationPhase.PRE_SUBMIT
    assert deferred.error.code == "CON-AGND-001"
    assert deferred.error.details["reason-code"] == "transport-unavailable"
    assert not case.prepares and not case.commands
    assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"] is None


@pytest.mark.asyncio
async def test_reconcile_only_unbound_never_prepares(case):
    deferred = await invoke(case, reconcile_only=True)
    assert deferred.side_effect_state == "not-started" and not case.prepares


@pytest.mark.asyncio
async def test_unbound_running_recovery_atomically_binds_original_attempt(case):
    record = await asyncio.to_thread(store.takeover_nonterminal_owner, case.admission.root, case.record["request-id"],
        expected_owner_epoch="owner", new_owner_epoch="other-owner")
    case.record = await asyncio.to_thread(store.takeover_nonterminal_owner, case.admission.root, record["request-id"],
        expected_owner_epoch="other-owner", new_owner_epoch="owner")
    deferred = await invoke(case)
    current = await effects(case)
    assert deferred.side_effect_state == "may-have-started"
    assert case.record["recovery-required"] and not current["recovery-required"]
    assert current["worker-id"] == case.record["worker-id"]
    assert current["attempt-epoch"] == case.record["attempt-epoch"]
    assert len(case.prepares) == len(case.commands) == 1
    assert type(case.effects[0]) is EffectAuthorized


@pytest.mark.asyncio
@pytest.mark.parametrize("recovering", [False, True])
async def test_preparation_timeout_is_null_bind_not_uncertain_native_work(case, recovering):
    if recovering:
        case.record = await asyncio.to_thread(store.defer_owned_recovery, case.admission.root, case.record["request-id"],
            owner_epoch="owner", worker_id=case.record["worker-id"], attempt_epoch=case.record["attempt-epoch"],
            expected_revision=case.record["revision"], error=AudiaGenticError("CON-AGND-001", "agents-node", "Disconnected", {}),
            phase="node-disconnected", side_effect_state="not-started", retry_delay_seconds=None)
    case.ignore_prepare = True
    case.runner.timeout = 0.05
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert deferred.phase == ObservationPhase.PRE_SUBMIT
    assert deferred.error.details["reason-code"] == "preparation-timeout"
    assert len(case.prepares) == 1 and not case.commands
    current = store.read_record(case.admission.root, case.record["request-id"])
    assert current["node-dispatch"] is None and current["recovery-required"] is recovering


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["occupied", "grant-revoked", "evidence-write"])
async def test_recovered_preparation_failure_never_clears_flag_or_sends_command(case, monkeypatch, failure):
    from audiagentic.components.agents.gateway.node import runner as module
    case.record = await asyncio.to_thread(store.defer_owned_recovery, case.admission.root, case.record["request-id"],
        owner_epoch="owner", worker_id=case.record["worker-id"], attempt_epoch=case.record["attempt-epoch"],
        expected_revision=case.record["revision"], error=AudiaGenticError("CON-AGND-001", "agents-node", "Disconnected", {}),
        phase="node-disconnected", side_effect_state="not-started", retry_delay_seconds=None)
    if failure == "occupied":
        case.reject_code = "CON-AGND-001"
    elif failure == "grant-revoked":
        case.prepared_hook = lambda: case.admission.authority.revoke("node", expected_grant_revision=1)
    else:
        def failed(*args, **kwargs):
            raise OSError("PRIVATE injected evidence write failure")
        monkeypatch.setattr(module, "persist_prepared_once", failed)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    current = store.read_record(case.admission.root, case.record["request-id"])
    assert current["node-dispatch"] is None and current["recovery-required"]
    assert current["worker-id"] == case.record["worker-id"] and current["attempt-epoch"] == case.record["attempt-epoch"]
    assert len(case.prepares) == 1 and not case.commands and not case.effects


@pytest.mark.asyncio
async def test_snapshot_drift_after_prepare_prevents_bind_and_command(case):
    path = gateway_node_admission_path(case.admission.root, case.record["request-id"])
    case.prepared_hook = lambda: path.write_bytes(path.read_bytes() + b" ")
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert len(case.prepares) == 1 and not case.commands
    assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before-bind", "before-effect"])
async def test_revoke_blocks_binding_or_denies_effect_without_second_command(case, when):
    def revoke():
        return case.admission.authority.revoke("node", expected_grant_revision=1)
    if when == "before-bind":
        case.prepared_hook = revoke
    else:
        case.command_hook = revoke
    await invoke(case)
    current = store.read_record(case.admission.root, case.record["request-id"])
    if when == "before-bind":
        assert not case.commands and current["node-dispatch"] is None
    else:
        current = await effects(case)
        assert type(case.effects[0]) is EffectDenied
        assert current["node-dispatch"]["authorization-id"] is None
        await invoke(case, reconcile_only=True)
        assert len(case.commands) == 1


@pytest.mark.asyncio
async def test_post_send_error_stays_uncertain_bound_and_never_resends(case, monkeypatch):
    original = case.gateway.send_work

    async def sent_then_error(kind, payload, **kwargs):
        result = await original(kind, payload, **kwargs)
        if kind == "command":
            raise TimeoutError("delivery uncertain")
        return result

    monkeypatch.setattr(case.gateway, "send_work", sent_then_error)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "may-have-started"
    await effects(case)
    await invoke(case)
    assert len(case.commands) == 1


@pytest.mark.asyncio
async def test_waiter_cannot_fabricate_completion(case):
    case.runner.waiter = lambda root, record: {"state": "completed"}
    await invoke(case)
    assert store.read_record(case.admission.root, case.record["request-id"])["state"] == "running"


@pytest.mark.asyncio
async def test_runner_rejects_event_loop_invocation_before_disk_io(case):
    with pytest.raises(AudiaGenticError):
        case.runner(case.admission.root, case.record)


@pytest.mark.asyncio
async def test_composed_waiter_returns_only_settled_canonical_result(case):
    def settle(root, record):
        assert case.effect_done.wait(3)
        current = store.read_record(root, record["request-id"])
        terminal = Receipt(case.commands[0].identity, "terminal", 1, hashlib.sha256(b"FAKE provider output").hexdigest())
        current = store.apply_owned_node_receipt(root, record["request-id"], receipt=terminal.public_payload(),
            owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
            expected_revision=current["revision"])
        store.transition_owned_terminal(root, record["request-id"], "completed", updates={"output": "FAKE provider output"},
            owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"])

    case.runner.waiter = settle
    result = await asyncio.to_thread(case.runner, case.admission.root, case.record)
    assert result["state"] == "completed" and result["output"] == "FAKE provider output"
    assert result["node-dispatch"]["receipt-stage"] == "terminal"


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["before-prepare", "before-effect"])
async def test_other_canonical_holder_blocks_prepare_or_effect(case, when):
    from .test_gateway_node_dispatch_store import bind

    def occupy():
        root = case.admission.root
        record = store.build_record(execution_profile_id="profile", prompt_body="other",
                                    node_placement=case.record["node-placement"])
        store.write_record(root, record)
        record = store.claim_dispatch(root, record["request-id"], owner_epoch="owner", expected_revision=0)
        record = store.start_owned_attempt(root, record["request-id"], owner_epoch="owner", worker_id="other-worker",
                                           expected_revision=record["revision"])
        bind(root, record)

    if when == "before-prepare":
        await asyncio.to_thread(occupy)
    else:
        case.command_hook = occupy
    await invoke(case)
    if when == "before-prepare":
        assert not case.prepares
    else:
        await effects(case)
        assert type(case.effects[0]) is EffectDenied
        assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"]["authorization-id"] is None


@pytest.mark.asyncio
async def test_source_hash_drift_after_bind_denies_effect(case):
    path = gateway_node_admission_path(case.admission.root, case.record["request-id"])
    case.command_hook = lambda: path.write_bytes(path.read_bytes() + b" ")
    await invoke(case)
    current = await effects(case)
    assert type(case.effects[0]) is EffectDenied
    assert current["node-dispatch"]["authorization-id"] is None
    assert current["node-dispatch"]["identity"] == case.commands[0].identity.to_mapping()


@pytest.mark.asyncio
async def test_replacement_during_prepare_cannot_bind_old_connection(case):
    case.prepared_hook = lambda: case.connections.replace("node", "new-boot", case.gateway.websocket)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert not case.commands
    assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"] is None


@pytest.mark.asyncio
async def test_snapshot_disk_reads_are_off_event_loop_for_prepare_and_effect(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import runner as module

    original = module.read_node_admission_snapshot
    threads = []

    def checked(*args, **kwargs):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "read_node_admission_snapshot", checked)
    await invoke(case)
    await effects(case)
    assert len(threads) >= 3 and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_canonical_waiter_cannot_settle_only_outer_terminal_while_effect_unresolved(case):
    def incomplete(root, record):
        assert case.effect_done.wait(3)
        current = store.read_record(root, record["request-id"])
        store.transition_owned_terminal(root, record["request-id"], "completed", updates={"output": "incomplete"},
            owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"])

    case.runner.waiter = incomplete
    deferred = await invoke(case)
    assert deferred.side_effect_state == "may-have-started"
    assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"]["authorization-state"] == "authorized"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("worker-id", "other-worker"), ("attempt-epoch", 2),
                                        ("dispatch-owner-epoch", "other-owner")])
async def test_queue_attempt_fences_are_not_substituted(case, field, value):
    case.record = {**case.record, field: value}
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started" and not case.prepares
    assert deferred.phase == ObservationPhase.OWNERSHIP
    assert deferred.error.details["reason-code"] == "owner-fence-changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("payload_sha256", "a" * 64), ("request_id", "other-request"),
                                        ("workspace_id", "other-workspace")])
async def test_effect_request_requires_original_command_identity(case, field, value):
    case.effect_identity = lambda command: replace(command, **{field: value})
    await invoke(case)
    current = await effects(case)
    assert type(case.effects[0]) is EffectDenied
    assert case.effects[0].authorization_request_id == case.effect_requests[0].message_id
    assert current["node-dispatch"]["authorization-id"] is None


@pytest.mark.asyncio
async def test_dispatched_effect_handler_cannot_authorize_after_channel_retirement(case, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    reply = case.runner._effect_reply
    results = []

    def paused(*args):
        entered.set()
        assert release.wait(3)
        try:
            result = reply(*args)
            results.append(result[0])
            return result
        finally:
            finished.set()

    monkeypatch.setattr(case.runner, "_effect_reply", paused)
    try:
        await invoke(case)
        assert await asyncio.to_thread(entered.wait, 3)
        case.gateway.begin_close("shutdown")
        release.set()
        assert await asyncio.to_thread(finished.wait, 3)
        await asyncio.wait_for(asyncio.shield(case.gateway._work_task), 2)
        current = store.read_record(case.admission.root, case.record["request-id"])
        assert results == ["effect-denied"]
        assert current["node-dispatch"]["authorization-id"] is None
        assert current["node-dispatch"]["authorization-state"] == "not-authorized"
        assert case.gateway.failure_summary is None
    finally:
        release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [("IO-AGND-001", "IO-AGND-001"), ("VAL-AGND-001", "VAL-AGND-001"),
                                         ("EXT-NOTREGISTERED-999", "VAL-AGND-001")])
async def test_remote_preparation_rejection_preserves_only_registered_code(case, code, expected):
    case.reject_code = code
    deferred = await invoke(case)
    assert deferred.error.code == expected
    assert deferred.error.details == {"reason-code": "preparation-rejected", "stage": "prepared-reply",
                                      "phase": "pre-submit"}
    assert deferred.phase == ObservationPhase.PRE_SUBMIT
    assert deferred.__cause__ is deferred.error
    assert not case.commands


@pytest.mark.asyncio
async def test_registered_first_cause_is_sanitized_and_survives_existing_recovery_projection(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import runner as module

    def failure(*args, **kwargs):
        raise AudiaGenticError("IO-AGND-001", "agents-node", "SECRET raw prompt /private/token",
                              {"reason-code": "SECRET arbitrary reason", "payload": "SECRET", "stage": "SECRET"})

    monkeypatch.setattr(module, "persist_prepared_once", failure)
    deferred = await invoke(case)
    assert deferred.error.code == "IO-AGND-001"
    assert deferred.error.details["reason-code"] == "prepared-evidence-unavailable"
    assert deferred.error.details["stage"] == "retain-prepared"
    assert "SECRET" not in "".join(traceback.format_exception(deferred))
    assert deferred.__cause__ is deferred.error and deferred.__suppress_context__
    summary = classify_error(deferred.error, phase=deferred.phase, side_effect_state=deferred.side_effect_state)
    assert summary["phase"] == "pre-submit" and summary["reason-code"] == "prepared-evidence-unavailable"
    current = store.read_record(case.admission.root, case.record["request-id"])
    updated = await asyncio.to_thread(store.defer_owned_recovery, case.admission.root, case.record["request-id"],
        owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
        error=deferred.error, phase=deferred.phase, side_effect_state=deferred.side_effect_state, retry_delay_seconds=None)
    assert updated["recovery"]["last-error-code"] == "IO-AGND-001"
    assert updated["recovery"]["last-error-details"]["stage"] == "retain-prepared"
    assert "SECRET" not in str(updated["recovery"])


@pytest.mark.asyncio
async def test_unregistered_private_exception_message_and_type_do_not_escape(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import runner as module

    class SECRETException(Exception):
        pass

    def failure(*args, **kwargs):
        raise SECRETException("SECRET prompt and credential")

    monkeypatch.setattr(module, "read_node_admission_snapshot", failure)
    deferred = await invoke(case)
    assert deferred.error.code == "IO-AGND-001"
    assert deferred.phase == ObservationPhase.ADMISSION
    assert deferred.error.details["reason-code"] == "admission-snapshot-invalid"
    assert "SECRET" not in "".join(traceback.format_exception(deferred))


@pytest.mark.asyncio
async def test_bound_terminal_receipt_reports_terminal_evidence_not_a_new_effect(case):
    await invoke(case)
    current = await effects(case)
    terminal = Receipt(case.commands[0].identity, "terminal", 1, "a" * 64)
    await asyncio.to_thread(store.apply_owned_node_receipt, case.admission.root, current["request-id"],
        receipt=terminal.public_payload(), owner_epoch="owner", worker_id=current["worker-id"],
        attempt_epoch=current["attempt-epoch"], expected_revision=current["revision"])
    deferred = await invoke(case, reconcile_only=True)
    assert deferred.side_effect_state == "terminal-evidence-seen"
    assert deferred.phase == ObservationPhase.RECONCILIATION
    assert len(case.commands) == 1


@pytest.mark.asyncio
async def test_grant_drift_before_bind_is_distinct_from_missing_transport(case):
    case.prepared_hook = lambda: case.admission.authority.revoke("node", expected_grant_revision=1)
    deferred = await invoke(case)
    assert deferred.error.code == "CON-AGND-001"
    assert deferred.phase == ObservationPhase.SUBMIT_INTENT
    assert deferred.error.details["stage"] == "bind"
    assert deferred.error.details["reason-code"] == "grant-or-connection-changed"
    assert not case.commands


@pytest.mark.asyncio
async def test_revoked_slot_before_prepare_reports_grant_drift_not_missing_transport(case):
    await asyncio.to_thread(case.admission.authority.revoke, "node", expected_grant_revision=1)
    deferred = await invoke(case)
    assert deferred.error.details["reason-code"] == "grant-or-connection-changed"
    assert deferred.error.details["stage"] == "transport"
    assert not case.prepares


@pytest.mark.asyncio
async def test_another_registered_owner_code_is_retained_without_private_details(case, monkeypatch):
    from pathlib import Path

    from audiagentic.components.agents.gateway.node import runner as module
    from audiagentic.foundation.contracts.error_resolutions import (
        load_error_resolutions_from_component,
    )

    config_dir = Path(module.__file__).resolve().parents[4] / "config" / "components"
    load_error_resolutions_from_component("agents", config_dir)

    def ownership_failure(*args, **kwargs):
        raise AudiaGenticError("CON-AGW-083", "agents", "SECRET ownership payload",
                              {"reason-code": ["SECRET arbitrary reason"], "payload": "SECRET"})

    monkeypatch.setattr(case.runner, "_read", ownership_failure)
    deferred = await invoke(case)
    assert deferred.error.code == "CON-AGW-083"
    assert deferred.error.details["stage"] == "ownership"
    assert deferred.error.details["reason-code"] == "owner-fence-changed"
    assert "SECRET" not in "".join(traceback.format_exception(deferred))


@pytest.mark.asyncio
async def test_waiter_cannot_override_canonical_uncertainty_or_inject_phase_text(case):
    def unavailable(root, record):
        raise RecoveryDeferred(AudiaGenticError("IO-AGND-001", "agents-node", "SECRET callback payload",
                                               {"reason-code": "SECRET callback reason"}),
                               phase="SECRET callback phase", side_effect_state="not-started")

    case.runner.waiter = unavailable
    deferred = await invoke(case)
    assert deferred.error.code == "IO-AGND-001"
    assert deferred.phase == ObservationPhase.RECONCILIATION
    assert deferred.side_effect_state == "may-have-started"
    assert "SECRET" not in "".join(traceback.format_exception(deferred))
    assert len(case.commands) <= 1


@pytest.mark.asyncio
async def test_real_stage_journal_reports_control_milestones_without_native_completion(case):
    from audiagentic.components.agents.gateway.observability import read_observation_page
    await invoke(case)
    current = await effects(case)
    page = await asyncio.to_thread(read_observation_page, case.admission.root, current["request-id"], limit=100)
    rows = [e for e in page["items"] if e["event"] == "node-stage-observed"]
    facts = [e["facts"]["diagnostic-facts"] for e in rows]
    stages = [e["node-stage"] for e in facts]
    ordered = ["admission-validated", "connection-qualified", "prepare-requested", "prepare-accepted",
               "prepared-retained", "command-bound", "command-delivery-requested", "command-sent",
               "reconciliation-started", "reconciliation-deferred"]
    assert [stage for stage in stages if stage in ordered] == ordered
    assert "effect-authorized" in stages
    assert "terminal-published" not in stages and "native-accepted" not in stages
    assert current["state"] == "running"
    elapsed = [e["elapsed-ms"] for e in facts if e["node-stage"] in ordered]
    assert elapsed == sorted(elapsed)
    raw = str(page)
    assert "FAKE provider render" not in raw and "FAKE manifest" not in raw


@pytest.mark.asyncio
async def test_stage_emission_happens_after_service_owner_guard_is_released(case, monkeypatch):
    from contextlib import contextmanager

    from audiagentic.components.agents.gateway.node import runner as module
    state = threading.local()
    original_guard, original_emit = case.runner.service.owner_guard, module.emit_node_stage
    calls = []
    @contextmanager
    def guarded(*args, **kwargs):
        with original_guard(*args, **kwargs):
            state.depth = getattr(state, "depth", 0) + 1
            try:
                yield
            finally:
                state.depth -= 1
    def emitted(*args, **kwargs):
        assert getattr(state, "depth", 0) == 0
        calls.append(args[2])
        return original_emit(*args, **kwargs)
    monkeypatch.setattr(case.runner.service, "owner_guard", guarded)
    monkeypatch.setattr(module, "emit_node_stage", emitted)
    await invoke(case)
    await effects(case)
    assert "command-bound" in calls and "effect-authorized" in calls


@pytest.mark.asyncio
async def test_actual_runner_diagnostic_sink_failures_do_not_reverse_binding_or_authorization(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import observability as module
    def failed(*args, **kwargs):
        raise OSError("PRIVATE diagnostic sink failure")
    monkeypatch.setattr(module.observations, "append_observation", failed)
    monkeypatch.setattr(store, "record_gateway_timeline", failed)
    monkeypatch.setattr(module.logger, "warning", failed)
    before = module.node_observation_failure_count()
    await invoke(case)
    current = await effects(case)
    assert current["state"] == "running" and current["node-dispatch"]["authorization-id"]
    assert type(case.effects[0]) is EffectAuthorized and len(case.commands) == 1
    assert module.node_observation_failure_count() > before


def test_shared_projection_preserves_safe_stage_reason_phase_when_queue_omits_stage():
    first = sanitize_node_error(AudiaGenticError("IO-AGND-001", "agents-node", "SECRET source details"),
                                stage="retain-prepared", reason="prepared-evidence-unavailable")
    projected = sanitize_node_error(first)
    assert projected.code == first.code
    assert projected.details == first.details == {
        "stage": "retain-prepared", "reason-code": "prepared-evidence-unavailable", "phase": "pre-submit",
    }
    assert "SECRET" not in str(projected)
    explicit_none = sanitize_node_error(first, stage=None)
    assert explicit_none.details == first.details


@pytest.mark.parametrize("details", [
    {"stage": "SECRET", "reason-code": "SECRET", "phase": "SECRET"},
    {"stage": [], "reason-code": {}, "phase": []},
])
def test_shared_projection_drops_arbitrary_source_details(details):
    source = {"code": "CON-AGND-001", "message": "SECRET", "details": details}
    projected = sanitize_node_error(source)
    assert projected.code == "CON-AGND-001"
    assert projected.details == {"stage": "observe", "phase": "reconciliation",
                                 "reason-code": "node-reconciliation-required"}
    assert "SECRET" not in str(projected)


def test_shared_projection_accepts_only_enum_phase_and_explicit_validated_stage():
    source = sanitize_node_error(None, stage="bind", reason="grant-or-connection-changed")
    projected = sanitize_node_error(source, stage="observe", phase=ObservationPhase.TERMINAL_OBSERVATION)
    assert projected.details["stage"] == "observe"
    assert projected.details["phase"] == "terminal-observation"
    invalid = sanitize_node_error(source, phase="SECRET")
    assert invalid.details["stage"] == "bind" and invalid.details["phase"] == "submit-intent"


@pytest.mark.asyncio
async def test_runner_error_retains_stage_after_shared_queue_projection_and_canonical_defer(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import runner as module

    def unavailable(*args, **kwargs):
        raise AudiaGenticError("IO-AGND-001", "agents-node", "SECRET disk material")

    monkeypatch.setattr(module, "persist_prepared_once", unavailable)
    deferred = await invoke(case)
    projected = sanitize_node_error(deferred.error)
    assert projected.details == deferred.error.details
    current = store.read_record(case.admission.root, case.record["request-id"])
    updated = await asyncio.to_thread(store.defer_owned_recovery, case.admission.root, current["request-id"],
        owner_epoch="owner", worker_id=current["worker-id"], attempt_epoch=current["attempt-epoch"],
        expected_revision=current["revision"], error=projected, phase=projected.details["phase"],
        side_effect_state=deferred.side_effect_state, retry_delay_seconds=None)
    assert updated["recovery"]["last-error-details"]["stage"] == "retain-prepared"
    assert updated["recovery"]["last-error-details"]["reason-code"] == "prepared-evidence-unavailable"


@pytest.mark.asyncio
async def test_fresh_prepare_requires_readiness_without_consuming_canonical_attempt(case):
    assert await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.consume_ready(case.gateway, grant_revision=1))
    deferred = await invoke(case)
    assert deferred.error.details["reason-code"] == "ready-channel-invalid"
    assert deferred.error.details["stage"] == "prepare"
    assert deferred.side_effect_state == "not-started"
    assert not case.prepares and not case.commands and not case.effects
    current = store.read_record(case.admission.root, case.record["request-id"])
    assert current["revision"] == case.record["revision"] and current["node-dispatch"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["cancel", "revision", "worker", "attempt", "owner", "placement"])
async def test_last_prepare_admission_rechecks_canonical_fences_before_consume(case, monkeypatch, fault):
    original = case.runner._admit_prepare
    consumed = []
    consume = case.connections.consume_ready
    def tracked(*args, **kwargs):
        consumed.append(True)
        return consume(*args, **kwargs)
    monkeypatch.setattr(case.connections, "consume_ready", tracked)
    def raced(root, record, slot, snapshot):
        current = store.read_record(root, record["request-id"])
        if fault == "cancel":
            store.mark_cancel_requested(root, record["request-id"])
        elif fault == "owner":
            store.takeover_nonterminal_owner(root, record["request-id"],
                expected_owner_epoch="owner", new_owner_epoch="replacement-owner")
        else:
            if fault == "revision":
                current["revision"] += 1
            elif fault == "worker":
                current["worker-id"] = "replacement-worker"
            elif fault == "attempt":
                current["attempt-epoch"] += 1
            else:
                current["node-placement"] = {**current["node-placement"], "principal-id": "different-principal"}
            store.write_record(root, current)
        return original(root, record, slot, snapshot)
    monkeypatch.setattr(case.runner, "_admit_prepare", raced)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert not consumed and not case.prepares and not case.commands
    assert deferred.error.details["reason-code"] == (
        "owner-fence-changed" if fault in {"worker", "attempt", "owner"} else "attempt-not-dispatchable")
    assert await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.is_ready(case.gateway, grant_revision=1))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["occupancy", "replacement", "revoke", "snapshot"])
async def test_last_prepare_admission_rechecks_source_grant_slot_and_occupancy(case, monkeypatch, fault):
    from .test_gateway_node_dispatch_store import bind

    original = case.runner._admit_prepare
    def raced(root, record, slot, snapshot):
        if fault == "occupancy":
            other = store.build_record(execution_profile_id="profile", prompt_body="other",
                node_placement=record["node-placement"])
            store.write_record(root, other)
            other = store.claim_dispatch(root, other["request-id"], owner_epoch="owner", expected_revision=0)
            other = store.start_owned_attempt(root, other["request-id"], owner_epoch="owner",
                worker_id="other-worker", expected_revision=other["revision"])
            bind(root, other)
        elif fault == "replacement":
            case.connections.replace("node", "replacement-boot", case.gateway.websocket)
        elif fault == "revoke":
            case.admission.authority.revoke("node", expected_grant_revision=1)
        else:
            path = gateway_node_admission_path(root, record["request-id"])
            path.write_bytes(path.read_bytes() + b" ")
        return original(root, record, slot, snapshot)
    monkeypatch.setattr(case.runner, "_admit_prepare", raced)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert not case.prepares and not case.commands
    if fault == "snapshot":
        assert deferred.error.details["reason-code"] == "admission-snapshot-invalid"
    if fault in {"occupancy", "snapshot"}:
        assert await asyncio.to_thread(case.admission.authority.serialize,
            lambda: case.connections.is_ready(case.gateway, grant_revision=1))


@pytest.mark.asyncio
async def test_late_canonical_bind_prevents_second_prepare_without_consuming_ready(case, monkeypatch):
    from .test_gateway_node_dispatch_store import bind

    original = case.runner._admit_prepare
    def raced(root, record, slot, snapshot):
        bind(root, record)
        return original(root, record, slot, snapshot)
    monkeypatch.setattr(case.runner, "_admit_prepare", raced)
    deferred = await invoke(case)
    assert deferred.side_effect_state == "may-have-started"
    assert store.read_record(case.admission.root, case.record["request-id"])["node-dispatch"] is not None
    assert not case.prepares and not case.commands
    assert await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.is_ready(case.gateway, grant_revision=1))


@pytest.mark.asyncio
async def test_rejected_prepare_requires_a_new_quiescent_cycle(case):
    case.reject_code = "VAL-AGND-001"
    await invoke(case)
    assert len(case.prepares) == 1 and not case.commands
    case.reject_code = None
    deferred = await invoke(case)
    assert deferred.error.details["reason-code"] == "ready-channel-invalid"
    assert len(case.prepares) == 1 and not case.commands
    await announce_ready(case)
    await invoke(case)
    await effects(case)
    assert len(case.prepares) == 2 and len(case.commands) == 1
    assert type(case.effects[0]) is EffectAuthorized


@pytest.mark.asyncio
async def test_bound_observation_and_effect_authorization_do_not_require_or_consume_ready(case, monkeypatch):
    await invoke(case)
    await effects(case)
    assert not await asyncio.to_thread(case.admission.authority.serialize,
        lambda: case.connections.is_ready(case.gateway, grant_revision=1))
    def forbidden(*args, **kwargs):
        pytest.fail("bound effects/observation must never consume readiness")
    monkeypatch.setattr(case.connections, "consume_ready", forbidden)
    await invoke(case)
    await invoke(case, reconcile_only=True)
    sent, _, reply = await case.node.request_work("effect-authorize",
        {"identity": case.commands[0].identity.to_mapping()},
        reply_types=(EffectAuthorized, EffectDenied), timeout=2)
    assert type(reply) is EffectAuthorized and reply.authorization_request_id == sent.message_id
    assert len(case.prepares) == len(case.commands) == 1


@pytest.mark.asyncio
async def test_admit_prepare_private_snapshot_reads_stay_outside_authority_lock(case, monkeypatch):
    from audiagentic.components.agents.gateway.node import runner as module

    state = threading.local()
    serialize = case.admission.authority.serialize
    read = module.read_node_admission_snapshot
    def serialized(callback):
        def guarded():
            state.held = True
            try:
                return callback()
            finally:
                state.held = False
        return serialize(guarded)
    def private_read(*args, **kwargs):
        assert not getattr(state, "held", False)
        return read(*args, **kwargs)
    monkeypatch.setattr(case.admission.authority, "serialize", serialized)
    monkeypatch.setattr(module, "read_node_admission_snapshot", private_read)
    await invoke(case)
    await effects(case)
    assert type(case.effects[0]) is EffectAuthorized
