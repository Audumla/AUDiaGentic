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
from audiagentic.components.agents.gateway.node.receipts import Receipt
from audiagentic.components.agents.gateway.node.runner import NodeRunner
from audiagentic.components.agents.gateway.node.transport import NodeConnectionOwner
from audiagentic.components.agents.gateway.node.work_protocol import (
    CommandWork,
    EffectAuthorize,
    EffectAuthorized,
    EffectDenied,
    PrepareWork,
)
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_node_admission_owner import admission as admission
from .test_gateway_node_admission_owner import submit


class PairedSocket:
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
        effect_identity=None,
        reject_code=None,
        prepared_hook=None, command_hook=None, ignore_prepare=False, preparation=None,
        effect_done=threading.Event())
    runner = NodeRunner(config, admission.service, admission.authority, connections, asyncio.get_running_loop(), timeout=0.5)
    value.runner = runner

    async def central(frame, work):
        assert type(work) is EffectAuthorize
        await runner.handle_effect_authorize(gateway, frame, work)

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
            pytest.fail("unexpected node work")

    gateway.enable_work(central, max_artifact_bytes=1024 * 1024)
    node.enable_work(fake_recipient, max_artifact_bytes=1024 * 1024)
    gateway.start()
    node.start()
    try:
        yield value
    finally:
        await gateway.close()
        await node.close()


async def invoke(case, **kwargs):
    with pytest.raises(RecoveryDeferred) as caught:
        await asyncio.to_thread(case.runner, case.admission.root, case.record, **kwargs)
    return caught.value


async def effects(case):
    assert await asyncio.to_thread(case.effect_done.wait, 3)
    return store.read_record(case.admission.root, case.record["request-id"])


@pytest.mark.asyncio
async def test_fresh_flow_binds_and_authorizes_exact_queue_attempt_without_claiming_completion(case):
    deferred = await invoke(case)
    current = await effects(case)
    assert deferred.side_effect_state == "may-have-started"
    assert len(case.prepares) == len(case.commands) == len(case.effects) == 1
    assert type(case.effects[0]) is EffectAuthorized
    assert case.effects[0].authorization_request_id == case.effect_requests[0].message_id
    assert current["node-dispatch"]["authorization-id"] == case.effects[0].authorization_id
    assert current["worker-id"] == "queue-worker" and current["attempt-epoch"] == 1
    assert current["state"] == "running"
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
async def test_unbound_running_recovery_waits_for_missing_canonical_clear_operation(case):
    record = await asyncio.to_thread(store.takeover_nonterminal_owner, case.admission.root, case.record["request-id"],
        expected_owner_epoch="owner", new_owner_epoch="other-owner")
    case.record = await asyncio.to_thread(store.takeover_nonterminal_owner, case.admission.root, record["request-id"],
        expected_owner_epoch="other-owner", new_owner_epoch="owner")
    deferred = await invoke(case)
    assert deferred.error.details["reason-code"] == "recovery-clear-unavailable"
    assert deferred.phase == ObservationPhase.OWNERSHIP
    assert case.record["recovery-required"] and not case.prepares and not case.commands


@pytest.mark.asyncio
async def test_preparation_timeout_is_null_bind_not_uncertain_native_work(case):
    case.ignore_prepare = True
    case.runner.timeout = 0.05
    deferred = await invoke(case)
    assert deferred.side_effect_state == "not-started"
    assert deferred.phase == ObservationPhase.PRE_SUBMIT
    assert deferred.error.details["reason-code"] == "preparation-timeout"
    assert len(case.prepares) == 1 and not case.commands


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
