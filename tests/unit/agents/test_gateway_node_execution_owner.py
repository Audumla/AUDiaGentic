"""Local owner fencing with real receipts/leases and fake supervised child I/O."""

from __future__ import annotations

import gc
import json
import sqlite3
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.unit.agents.test_gateway_node_worker_terminal import make_case, mint_proof, sha

from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.contracts import Frame, canonical_json
from audiagentic.components.agents.gateway.node.execution_owner import NodeExecutionOwner
from audiagentic.components.agents.gateway.node.preparation import RetainedNodePreparation
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore, ReceiptOwnerScope
from audiagentic.components.agents.gateway.queue import worker
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayNodeConfig,
    SharedGatewayNodeWorkspace,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import current_process_evidence
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner


@pytest.fixture
def env(tmp_path):
    case = make_case(tmp_path / "project")
    state = tmp_path / "node-state"
    state.mkdir(mode=0o700)
    config = SharedGatewayNodeConfig(
        "node",
        "server",
        "wss://localhost/node",
        tmp_path / "unused-token",
        state,
        {"workspace": SharedGatewayNodeWorkspace(tmp_path / "project", frozenset({"profile"}))},
    )
    service = ManagedServiceStore(ServiceKey("execution-node", "node"), root=state)
    record = ManagedServiceOwner(service).claim(
        protocol_version="1",
        endpoint=EndpointInfo("local", "execution-node"),
        evidence_factory=lambda epoch: current_process_evidence(owner_epoch=epoch),
    )
    return SimpleNamespace(case=case, config=config, service=service, record=record)


def open_owner(env, *, node_epoch="boot"):
    return NodeExecutionOwner.open(
        env.config,
        service_store=env.service,
        service_owner_epoch=env.record.owner_epoch,
        node_epoch=node_epoch,
    )


def connect(owner, *, gateway="gateway", generation=1, boot="boot", capability="active"):
    control = NodeConnectionIdentity("node", boot, gateway, generation)
    owner.observe_connection(control, capability=capability)
    owner.handoff_if_quiescent()
    return control


def run(owner, case, **changes):
    args = dict(
        preparation=case.preparation,
        command_payload=case.payload,
        current_binding=case.preparation.attestation.binding,
        authorization_request=case.auth_request,
        authorization_reply=case.auth_reply,
        timeout_seconds=1,
    )
    args.update(changes)
    return owner.run_one(case.identity, **args)


def ack(owner, connection, receipt, root):
    store = NodeReceiptStore(
        root=root,
        node_id=connection.node_id,
        node_epoch=connection.node_epoch,
        gateway_owner_epoch=connection.gateway_owner_epoch,
    )
    return Frame(
        1,
        "reconcile-result",
        "ack",
        "node",
        connection.node_epoch,
        connection.gateway_owner_epoch,
        1,
        {
            "kind": "receipt-ack",
            "server-id": "server",
            "log-incarnation-id": store.log_incarnation_id,
            "connection-generation": connection.connection_generation,
            "through-sequence": receipt.sequence,
            "through-receipt-sha256": receipt.digest,
        },
    )


def test_scope_reader_missing_is_noncreating(tmp_path):
    root = tmp_path / "absent"
    assert NodeReceiptStore.read_owner_scope(root, expected_node_id="node") is None
    assert not root.exists()


def test_scope_reader_preserves_files_schema_and_actual_scope(env):
    case = env.case
    root = case.store.root
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    assert NodeReceiptStore.read_owner_scope(root, expected_node_id="node") == ReceiptOwnerScope(
        "node", "boot", "gateway"
    )
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == before
    with pytest.raises(AudiaGenticError):
        NodeReceiptStore.read_owner_scope(root, expected_node_id="other")
    assert case.store.get(case.identity).state == "effect-intent"


@pytest.mark.parametrize("damage", ["version", "shape", "trigger", "checkpoint"])
def test_scope_reader_rejects_schema_without_migrating(env, damage):
    root = env.case.store.root
    with sqlite3.connect(root / "receipts.sqlite3") as db:
        db.execute(
            {
                "version": "PRAGMA user_version=1",
                "shape": "ALTER TABLE owner ADD COLUMN extra TEXT",
                "trigger": "DROP TRIGGER outbox_no_delete",
                "checkpoint": "UPDATE receipt_checkpoint SET through_sequence=99",
            }[damage]
        )
    before = (root / "receipts.sqlite3").read_bytes()
    with pytest.raises(AudiaGenticError):
        NodeReceiptStore.read_owner_scope(root, expected_node_id="node")
    assert (root / "receipts.sqlite3").read_bytes() == before


def test_scope_reader_rejects_symlinks(env, tmp_path):
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(env.case.store.root, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not grant symlink creation")
    with pytest.raises(AudiaGenticError):
        NodeReceiptStore.read_owner_scope(alias, expected_node_id="node")


def test_one_shot_success_and_duplicate_no_resend(env, monkeypatch):
    owner = open_owner(env)
    connect(owner)
    mint_proof(monkeypatch, env.case)
    receipt = run(owner, env.case)
    assert receipt.state == "terminal"
    assert not owner.snapshot().capacity_blocked
    store = NodeReceiptStore(
        root=env.config.state_root, node_id="node", node_epoch="boot", gateway_owner_epoch="gateway"
    )
    assert store.native_reference(env.case.identity) is None
    assert store.worker_terminal_output(env.case.identity).text.startswith("Verified answer")
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("duplicate native call"),
    )
    with pytest.raises(AudiaGenticError, match="reconciliation-only"):
        run(owner, env.case)


@pytest.mark.parametrize("capability", ["disconnect", "drain"])
def test_no_fresh_effect_without_active_channel(env, monkeypatch, capability):
    owner = open_owner(env)
    connection = connect(owner, capability="drain" if capability == "drain" else "active")
    if capability == "disconnect":
        owner.connection_lost(connection)
    monkeypatch.setattr(
        worker, "execute_verified_isolated_provider_turn", lambda **kw: pytest.fail("native call")
    )
    with pytest.raises(AudiaGenticError):
        run(owner, env.case)
    assert owner.receipts_after() == ()


def test_restart_uses_persisted_scope_and_intent_stays_occupied(env, monkeypatch):
    store = NodeReceiptStore(
        root=env.config.state_root, node_id="node", node_epoch="boot", gateway_owner_epoch="gateway"
    )
    c = env.case
    store.prepare(c.identity, canonical_json(c.payload))
    store.effect_intent(c.identity, c.auth_request, c.auth_reply, connection_generation=1)
    owner = open_owner(env, node_epoch="reboot")
    assert owner.snapshot().owner_scope.node_epoch == "boot"
    assert owner.snapshot().capacity_blocked
    connect(owner, gateway="newgateway", boot="reboot")
    assert owner.snapshot().owner_scope.node_epoch == "reboot"
    assert owner.snapshot().capacity_blocked
    assert owner.receipts_after()[-1].identity == c.identity
    with pytest.raises(AudiaGenticError):
        store.advance_epoch(node_epoch="other", gateway_owner_epoch="other")
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("restart resend"),
    )
    with pytest.raises(AudiaGenticError):
        run(owner, c)


def start_blocked(env, monkeypatch, *, error=False):
    owner = open_owner(env)
    old = connect(owner)
    mint_proof(monkeypatch, env.case)
    entered, release = threading.Event(), threading.Event()
    original = worker._wait_for_provider_terminal

    def wait(*args, **kwargs):
        entered.set()
        assert release.wait(5), "test failed to release worker"
        if error:
            raise RuntimeError("worker failed after intent")
        return original(*args, **kwargs)

    monkeypatch.setattr(worker, "_wait_for_provider_terminal", wait)
    result, errors = [], []

    def target():
        try:
            result.append(run(owner, env.case))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=target)
    thread.start()
    assert entered.wait(5)
    return owner, old, release, thread, result, errors


@pytest.mark.parametrize("error", [False, True])
def test_g2_control_does_not_move_live_producer_scope_or_ack(env, monkeypatch, error):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch, error=error)
    try:
        row = owner.receipts_after()[-1]
        g2 = NodeConnectionIdentity("node", "boot", "gateway2", 1)
        owner.observe_connection(g2)
        owner.connection_lost(old)  # stale cleanup cannot erase G2
        assert owner.snapshot().control == g2
        assert owner.handoff_if_quiescent().owner_scope.gateway_owner_epoch == "gateway"
        assert owner.acknowledge(ack(owner, g2, row, env.config.state_root)) is None
        assert (
            NodeReceiptStore.read_owner_scope(
                env.config.state_root, expected_node_id="node"
            ).gateway_owner_epoch
            == "gateway"
        )
        with pytest.raises(AudiaGenticError):
            run(owner, env.case)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    assert bool(errors) == error
    assert bool(result) != error
    assert owner.snapshot().owner_scope.gateway_owner_epoch == "gateway"
    snapshot = owner.handoff_if_quiescent()
    assert snapshot.owner_scope.gateway_owner_epoch == "gateway2"
    assert snapshot.capacity_blocked == error
    row = owner.receipts_after()[-1]
    assert row.state == ("effect-intent" if error else "terminal")
    assert (
        owner.acknowledge(ack(owner, g2, row, env.config.state_root)).through_sequence
        == row.sequence
    )
    assert owner.receipts_after()[-1] == row  # ACK is custody, no deletion/completion inference.


def test_disconnect_during_run_does_not_discard_owned_terminal(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch)
    owner.connection_lost(old)
    assert owner.snapshot().producer_running
    release.set()
    thread.join(5)
    assert not errors and result[0].state == "terminal"
    assert owner.snapshot().control is None


def test_service_retirement_fences_terminal_and_keeps_intent(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch)
    ManagedServiceOwner(env.service).retire(expected_epoch=env.record.owner_epoch)
    release.set()
    thread.join(5)
    assert not result and len(errors) == 1 and isinstance(errors[0], AudiaGenticError)
    assert (
        NodeReceiptStore(
            root=env.config.state_root,
            node_id="node",
            node_epoch="boot",
            gateway_owner_epoch="gateway",
        )
        .get(env.case.identity)
        .state
        == "effect-intent"
    )
    with pytest.raises(AudiaGenticError):
        owner.handoff_if_quiescent()


def test_single_local_owner_and_wrong_service_identity(env):
    owner = open_owner(env)
    with pytest.raises(AudiaGenticError, match="already holds"):
        open_owner(env)
    wrong = ManagedServiceStore(ServiceKey("gateway", "central"), root=env.config.state_root)
    with pytest.raises(AudiaGenticError, match="execution-node service"):
        NodeExecutionOwner.open(
            env.config,
            service_store=wrong,
            service_owner_epoch=env.record.owner_epoch,
            node_epoch="boot",
        )
    assert owner.snapshot().owner_scope is None


@pytest.mark.parametrize("change", ["binding", "payload", "auth", "bundle", "workspace"])
def test_failed_correlation_never_creates_intent(env, monkeypatch, change):
    owner = open_owner(env)
    connect(owner)
    c = env.case
    kwargs = {}
    if change == "binding":
        kwargs["current_binding"] = replace(c.preparation.attestation.binding, binding_generation=2)
    elif change == "payload":
        kwargs["command_payload"] = dict(c.payload) | {"raw-prompt": "different"}
    elif change == "auth":
        kwargs["authorization_reply"] = replace(
            c.auth_reply, payload=dict(c.auth_reply.payload) | {"authorization-request-id": "other"}
        )
    elif change == "workspace":
        env.config.workspaces.clear()
    else:
        bundle = json.loads(c.preparation._provider_manifest)
        bundle["provider-request"]["packet-data"]["prompt-body"] = "different"
        raw = canonical_json(bundle)
        attestation = replace(c.preparation.attestation, provider_manifest_sha256=sha(raw))
        kwargs["preparation"] = RetainedNodePreparation(
            attestation, c.preparation._rendered_prompt, raw
        )
        kwargs["command_payload"] = dict(c.payload) | {"attestation": attestation.to_mapping()}
        # Rehash the identity as a hostile but internally content-consistent candidate.
        identity = replace(
            c.identity, payload_sha256=sha(canonical_json(kwargs["command_payload"]))
        )
        c = SimpleNamespace(**(c.__dict__ | {"identity": identity}))
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("uncorrelated native call"),
    )
    with pytest.raises(AudiaGenticError):
        run(owner, c, **kwargs)
    assert owner.receipts_after() == ()


def test_prepared_exact_identity_may_execute_but_changed_identity_cannot(env, monkeypatch):
    owner = open_owner(env)
    connect(owner)
    store = NodeReceiptStore(
        root=env.config.state_root, node_id="node", node_epoch="boot", gateway_owner_epoch="gateway"
    )
    store.prepare(env.case.identity, canonical_json(env.case.payload))
    # Reopen simulates a prepared-only restart under the same original fences.
    del owner
    gc.collect()
    owner = open_owner(env)
    connect(owner)
    mint_proof(monkeypatch, env.case)
    assert run(owner, env.case).state == "terminal"


def test_generation_only_handoff_defers_ack_until_producer_barrier(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch)
    try:
        g2 = replace(old, connection_generation=2)
        owner.observe_connection(g2)
        assert owner.handoff_if_quiescent().handoff_pending
        frame = ack(owner, g2, owner.receipts_after()[-1], env.config.state_root)
        assert owner.acknowledge(frame) is None
    finally:
        release.set()
        thread.join(5)
    assert not errors and result[0].state == "terminal"
    assert not owner.handoff_if_quiescent().handoff_pending
    frame = ack(owner, g2, owner.receipts_after()[-1], env.config.state_root)
    assert owner.acknowledge(frame).through_sequence == result[0].sequence
    with pytest.raises(AudiaGenticError, match="Stale control"):
        owner.observe_connection(old)


def test_old_gateway_handler_cannot_reinstall_retired_epoch(env):
    owner = open_owner(env)
    old = connect(owner)
    owner.observe_connection(replace(old, gateway_owner_epoch="gateway2"))
    with pytest.raises(AudiaGenticError, match="Retired gateway"):
        owner.observe_connection(old)


def test_plain_result_or_peer_claim_is_not_worker_terminal_proof(env, monkeypatch):
    owner = open_owner(env)
    connect(owner)
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: SimpleNamespace(worker_exited=True, result={"output": "fake"}),
    )
    with pytest.raises(AudiaGenticError):
        run(owner, env.case)
    assert owner.snapshot().capacity_blocked
    assert not owner.snapshot().producer_running
    assert owner.receipts_after()[-1].state == "effect-intent"


def test_scope_reader_live_wal_uses_committed_scope_without_new_files(env):
    root = env.case.store.root
    db = sqlite3.connect(root / "receipts.sqlite3")
    try:
        db.execute("UPDATE owner SET gateway='rotated'")
        db.commit()
        before = {p.name for p in root.iterdir()}
        assert (
            NodeReceiptStore.read_owner_scope(root, expected_node_id="node").gateway_owner_epoch
            == "rotated"
        )
        assert {p.name for p in root.iterdir()} == before
    finally:
        db.close()


def test_scope_reader_missing_wal_index_refuses_instead_of_creating(env):
    root = env.case.store.root
    (root / "receipts.sqlite3-wal").write_bytes(b"private orphaned WAL")
    before = {p.name for p in root.iterdir()}
    with pytest.raises(AudiaGenticError, match="existing shared-memory"):
        NodeReceiptStore.read_owner_scope(root, expected_node_id="node")
    assert {p.name for p in root.iterdir()} == before


def second_case(case):
    bundle = json.loads(case.preparation._provider_manifest)
    bundle["execution-manifest"]["request_id"] = "request2"
    bundle["provider-request"]["packet-data"]["request-id"] = "request2"
    raw = canonical_json(bundle)
    a = replace(
        case.preparation.attestation,
        binding=replace(
            case.preparation.attestation.binding, command_id="command2", request_id="request2"
        ),
        provider_manifest_sha256=sha(raw),
    )
    prep = RetainedNodePreparation(a, case.preparation._rendered_prompt, raw)
    payload = dict(case.payload) | {"attestation": a.to_mapping()}
    identity = replace(
        case.identity,
        command_id="command2",
        request_id="request2",
        payload_sha256=sha(canonical_json(payload)),
    )
    auth_request = replace(case.auth_request, payload={"identity": identity.to_mapping()})
    auth_reply = replace(
        case.auth_reply, payload=dict(case.auth_reply.payload) | {"identity": identity.to_mapping()}
    )
    return SimpleNamespace(
        **(
            case.__dict__
            | {
                "preparation": prep,
                "payload": payload,
                "identity": identity,
                "auth_request": auth_request,
                "auth_reply": auth_reply,
            }
        )
    )


def test_concurrent_distinct_command_cannot_start_second_producer(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch)
    try:
        with pytest.raises(AudiaGenticError, match="occupied"):
            run(owner, second_case(env.case))
        assert len(owner.receipts_after()) == 2
    finally:
        release.set()
        thread.join(5)
    assert not errors and result[0].state == "terminal"


def test_handed_off_store_rejects_old_producer_mutation(env):
    owner = open_owner(env)
    old = connect(owner)
    store = NodeReceiptStore(
        root=env.config.state_root, node_id="node", node_epoch="boot", gateway_owner_epoch="gateway"
    )
    owner.observe_connection(replace(old, gateway_owner_epoch="gateway2"))
    owner.handoff_if_quiescent()
    with pytest.raises(AudiaGenticError, match="evidence-only"):
        store.prepare(env.case.identity, canonical_json(env.case.payload))
    assert owner.receipts_after() == ()


@pytest.mark.parametrize("bad_claim", ["epoch", "birth", "root"])
def test_open_rejects_wrong_current_process_claim(env, monkeypatch, bad_claim):
    service, epoch = env.service, env.record.owner_epoch
    if bad_claim == "epoch":
        epoch = "other-owner"
    elif bad_claim == "root":
        service = ManagedServiceStore(
            ServiceKey("execution-node", "node"), root=env.config.state_root / "other-root"
        )
    else:
        from audiagentic.components.agents.gateway.node import execution_owner

        monkeypatch.setattr(execution_owner, "process_creation_identity", lambda pid: "wrong-birth")
    with pytest.raises(AudiaGenticError):
        NodeExecutionOwner.open(
            env.config, service_store=service, service_owner_epoch=epoch, node_epoch="boot"
        )


def test_prepared_reused_command_with_changed_binding_is_not_a_new_intent(env, monkeypatch):
    # An existing prepared command still requires every original identity field.
    c = env.case
    store = NodeReceiptStore(
        root=env.config.state_root, node_id="node", node_epoch="boot", gateway_owner_epoch="gateway"
    )
    store.prepare(c.identity, canonical_json(c.payload))
    owner = open_owner(env)
    connect(owner)
    a = replace(
        c.preparation.attestation,
        binding=replace(c.preparation.attestation.binding, binding_generation=2),
    )
    prep = RetainedNodePreparation(
        a, c.preparation._rendered_prompt, c.preparation._provider_manifest
    )
    payload = dict(c.payload) | {"attestation": a.to_mapping()}
    identity = replace(
        c.identity, binding_generation=2, payload_sha256=sha(canonical_json(payload))
    )
    candidate = SimpleNamespace(
        **(
            c.__dict__
            | {
                "identity": identity,
                "preparation": prep,
                "payload": payload,
                "auth_request": replace(
                    c.auth_request, payload={"identity": identity.to_mapping()}
                ),
                "auth_reply": replace(
                    c.auth_reply,
                    payload=dict(c.auth_reply.payload) | {"identity": identity.to_mapping()},
                ),
            }
        )
    )
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("rebound prepared command executed"),
    )
    with pytest.raises(AudiaGenticError):
        run(owner, candidate)
    assert store.get(c.identity).state == "prepared"
    assert len(owner.receipts_after()) == 1


@pytest.mark.parametrize("version", [2, 3])
def test_scope_reader_older_supported_schema_does_not_migrate(env, version):
    root = env.case.store.root
    with sqlite3.connect(root / "receipts.sqlite3") as db:
        db.execute("ALTER TABLE commands DROP COLUMN artifact_kind")
        if version == 2:
            db.execute("ALTER TABLE owner DROP COLUMN log_incarnation_id")
            db.execute("DROP TABLE receipt_checkpoint")
        db.execute(f"PRAGMA user_version={version}")
    # SQLite readers may update existing SHM read marks, never durable DB/WAL facts.
    names = {p.name for p in root.iterdir()}
    before = {
        p.name: p.read_bytes()
        for p in root.iterdir()
        if p.is_file() and not p.name.endswith("-shm")
    }
    assert NodeReceiptStore.read_owner_scope(root, expected_node_id="node") == ReceiptOwnerScope(
        "node", "boot", "gateway"
    )
    assert {p.name for p in root.iterdir()} == names
    assert {
        p.name: p.read_bytes()
        for p in root.iterdir()
        if p.is_file() and not p.name.endswith("-shm")
    } == before


def test_worker_error_retains_occupancy_against_valid_different_command(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch, error=True)
    release.set()
    thread.join(5)
    assert len(errors) == 1 and not result
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("uncertain effect released capacity"),
    )
    with pytest.raises(AudiaGenticError, match="occupied"):
        run(owner, second_case(env.case))
    with pytest.raises(AudiaGenticError, match="reconciliation-only"):
        run(owner, env.case)
    assert owner.receipts_after()[-1].state == "effect-intent"


def test_external_store_handoff_fences_original_producer_terminal(env, monkeypatch):
    owner, old, release, thread, result, errors = start_blocked(env, monkeypatch)
    try:
        store = NodeReceiptStore(
            root=env.config.state_root,
            node_id="node",
            node_epoch="boot",
            gateway_owner_epoch="gateway",
        )
        store.advance_epoch(node_epoch="boot", gateway_owner_epoch="externalgateway")
    finally:
        release.set()
        thread.join(5)
    assert not result and len(errors) == 1 and isinstance(errors[0], AudiaGenticError)
    assert owner.snapshot().capacity_blocked
    assert store.get(env.case.identity).state == "effect-intent"


def test_real_process_restart_reads_old_scope_and_never_resends(tmp_path, monkeypatch):
    import subprocess
    import sys

    from tests.unit.agents.test_gateway_node_receipts import child_environment

    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    project = tmp_path / "project"
    c = make_case(project)
    inputs = tmp_path / "fixture-inputs.json"
    inputs.write_bytes(
        canonical_json(
            {
                "identity": c.identity.to_mapping(),
                "payload": c.payload,
                "request": json.loads(c.auth_request.to_bytes()),
                "reply": json.loads(c.auth_reply.to_bytes()),
            }
        )
    )
    # Child creates only local fixture intent and exits. No worker/provider call.
    script = r"""
import sys
from pathlib import Path
import json
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.components.agents.gateway.node.contracts import canonical_json, CommandIdentity, Frame
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner
from audiagentic.foundation.system.managed_service_contracts import ServiceKey, EndpointInfo
from audiagentic.foundation.system.managed_process import current_process_evidence
state, inputs = map(Path, sys.argv[1:])
service = ManagedServiceStore(ServiceKey('execution-node', 'node'), root=state)
ManagedServiceOwner(service).claim(protocol_version='1', endpoint=EndpointInfo('local', 'node'),
    evidence_factory=lambda epoch: current_process_evidence(owner_epoch=epoch))
data = json.loads(inputs.read_bytes())
identity = CommandIdentity.from_mapping(data['identity'])
s = NodeReceiptStore(root=state, node_id='node', node_epoch='boot', gateway_owner_epoch='gateway')
s.prepare(identity, canonical_json(data['payload']))
s.effect_intent(identity, Frame.from_bytes(canonical_json(data['request'])),
    Frame.from_bytes(canonical_json(data['reply'])), connection_generation=1)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(state), str(inputs)],
        env=child_environment(),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 0, child.stderr
    service = ManagedServiceStore(ServiceKey("execution-node", "node"), root=state)
    previous = service.read()
    assert previous.process.pid != __import__("os").getpid()
    record = ManagedServiceOwner(service).claim(
        protocol_version="1",
        endpoint=EndpointInfo("local", "node"),
        evidence_factory=lambda epoch: current_process_evidence(owner_epoch=epoch),
    )
    assert record.owner_epoch != previous.owner_epoch
    config = SharedGatewayNodeConfig(
        "node",
        "server",
        "wss://localhost/node",
        tmp_path / "unused-token",
        state,
        {"workspace": SharedGatewayNodeWorkspace(project, frozenset({"profile"}))},
    )
    owner = NodeExecutionOwner.open(
        config, service_store=service, service_owner_epoch=record.owner_epoch, node_epoch="reboot"
    )
    assert owner.snapshot().owner_scope == ReceiptOwnerScope("node", "boot", "gateway")
    assert owner.snapshot().capacity_blocked
    connect(owner, boot="reboot", gateway="newgateway")
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("restart resend"),
    )
    with pytest.raises(AudiaGenticError):
        run(owner, c)
    assert owner.snapshot().capacity_blocked
    assert owner.receipts_after()[-1].state == "effect-intent"


@pytest.mark.parametrize("boundary", ["prepare", "effect_intent"])
def test_persistence_error_after_commit_never_executes_or_releases_capacity(
    env, monkeypatch, boundary
):
    owner = open_owner(env)
    connect(owner)
    original = getattr(NodeReceiptStore, boundary)

    def commit_then_fail(store, *args, **kwargs):
        original(store, *args, **kwargs)
        raise OSError("uncertain persistence acknowledgement")

    monkeypatch.setattr(NodeReceiptStore, boundary, commit_then_fail)
    monkeypatch.setattr(
        worker,
        "execute_verified_isolated_provider_turn",
        lambda **kw: pytest.fail("ambiguous durable transition executed"),
    )
    with pytest.raises(OSError):
        run(owner, env.case)
    assert owner.snapshot().capacity_blocked
    assert not owner.snapshot().producer_running
    assert owner.receipts_after()[-1].state == (
        "prepared" if boundary == "prepare" else "effect-intent"
    )
    monkeypatch.setattr(NodeReceiptStore, boundary, original)
    with pytest.raises(AudiaGenticError, match="occupied"):
        run(owner, second_case(env.case))
