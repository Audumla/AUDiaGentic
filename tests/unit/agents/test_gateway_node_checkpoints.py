"""Single-stream C+1 custody, fixed canonical writes and cumulative ACKs."""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node import checkpoints as module
from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.checkpoints import (
    CanonicalReceiptTarget,
    NodeReceiptCheckpoints,
)
from audiagentic.components.agents.gateway.node.contracts import (
    CommandIdentity,
    Frame,
    canonical_json,
)
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    build_final_command_payload,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, read_json_with_retry
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


def _service(base):
    return ManagedServiceStore(ServiceKey("gateway", "checkpoints"), root=base)


def _running(base):
    service = _service(base)
    record = service.create(protocol_version="test", owner_epoch="owner")
    service.transition("running", expected_revision=record.revision, expected_epoch="owner")
    return service


def _target(project_root, identity):
    record = store.read_record(project_root, identity.request_id)
    return CanonicalReceiptTarget(
        project_root, record["dispatch-owner-epoch"], record["worker-id"],
        record["attempt-epoch"], record["revision"],
    )


def _make_request(root, suffix):
    record = store.build_record(
        execution_profile_id="profile", prompt_body="hello",
        node_placement={"node-id": "node", "workspace-id": "workspace",
                        "principal-id": "principal", "server-project-id": "project", "grant-revision": 1},
    )
    store.write_record(root, record)
    record = store.claim_dispatch(root, record["request-id"], owner_epoch="owner", expected_revision=0)
    record = store.start_owned_attempt(
        root, record["request-id"], owner_epoch="owner", worker_id="worker",
        expected_revision=record["revision"],
    )
    binding = PreparationBinding(
        "command-" + suffix, record["request-id"], "node", "node-epoch", "owner", 1,
        "workspace", 1, 1, "challenge-" + suffix, "prepare-" + suffix,
    )
    semantic = PromptSemanticIdentity(
        "a" * 64, "b" * 64, "prompt", "profile", 1,
        hashlib.sha256(b"expanded").hexdigest(), hashlib.sha256(b"hello").hexdigest(),
    )
    preparation = prepare_node_command(
        binding=binding, semantic=semantic, raw_prompt="hello", rendered_prompt="private render",
        manifest_id="manifest-" + suffix, context_fingerprint="c" * 64, runtime_digest="d" * 64,
        provider_manifest=b"private manifest", worker_id="worker", attempt_epoch=1,
        provider_id="node-provider", model_id="model", model_alias=None,
    )
    payload = build_final_command_payload(preparation, "hello")
    identity = CommandIdentity(
        binding.command_id, record["request-id"], "node", "node-epoch", "owner", 1,
        "workspace", 1, 1, hashlib.sha256(canonical_json(payload)).hexdigest(), "profile",
    )
    record = store.bind_owned_node_dispatch(
        root, record["request-id"], identity=identity, command_payload=payload,
        accepted_attestation=preparation.attestation, owner_epoch="owner",
        worker_id="worker", attempt_epoch=1, expected_revision=record["revision"],
    )
    store.authorize_owned_node_effect(
        root, record["request-id"], identity=identity, accepted_attestation=preparation.attestation,
        authorization_id="auth-" + suffix, current_node_epoch="node-epoch",
        current_connection_generation=1, owner_epoch="owner", worker_id="worker",
        attempt_epoch=1, expected_revision=record["revision"],
    )
    return identity, payload


@pytest.fixture
def system(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service = _running(tmp_path / "service-base")
    identity, payload = _make_request(project, "one")
    local = NodeReceiptStore(
        node_id="node", node_epoch="node-epoch", gateway_owner_epoch="owner", root=tmp_path / "local-node",
    )
    receipt = local.prepare(identity, canonical_json(payload))
    central = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    return project, service, local, central, receipt


def _accept(system, receipt=None, **changes):
    root, _, local, central, first = system
    return central.accept(
        receipt or first, log_incarnation_id=local.log_incarnation_id,
        expected_epoch="owner", resolve_target=lambda identity: _target(root, identity), **changes,
    )


def _restart(service, epoch):
    for state in ("stopping", "stopped", "starting", "running"):
        record = service.read()
        service.transition(
            state, expected_revision=record.revision, expected_epoch=record.owner_epoch,
            new_owner_epoch=epoch if state == "starting" else None,
        )


def test_canonical_then_cursor_then_real_node_ack_outside_guards(system):
    root, service, local, central, receipt = system
    ack = _accept(system)
    record = store.read_record(root, receipt.identity.request_id)
    assert record["node-dispatch"]["receipt-sha256"] == receipt.digest
    assert read_json_with_retry(central.path) == {
        "version": 1, "server-id": "server", "node-id": "node",
        "log-incarnation-id": local.log_incarnation_id, "sequence": 1,
        "receipt-sha256": receipt.digest, "gateway-owner-epoch": "owner",
    }
    # The returned metadata does not mutate node custody until the runtime
    # sends it. Acquiring this lock also proves accept released its guard.
    assert local.ack_checkpoint().through_sequence == 0
    with service.owner_guard("owner"):
        pass
    frame = Frame(1, "reconcile-result", "ack-1", "node", "node-epoch", "owner", 1,
                  ack.payload(connection_generation=1))
    checkpoint = local.acknowledge(
        frame, expected_server_id="server",
        current_connection=NodeConnectionIdentity("node", "node-epoch", "owner", 1),
    )
    assert checkpoint.through_sequence == 1
    assert checkpoint.through_receipt_sha256 == receipt.digest


def test_interleaved_commands_and_old_duplicates_return_current_cumulative_ack(system):
    root, _, local, central, first = system
    second_identity, payload = _make_request(root, "two")
    second = local.prepare(second_identity, canonical_json(payload))
    assert (first.sequence, second.sequence) == (1, 2)
    _accept(system, first)
    latest = _accept(system, second)
    no_lookup = Mock(side_effect=AssertionError("old command must not be resolved or applied"))
    for duplicate in (first, second):
        ack = central.accept(
            duplicate, log_incarnation_id=local.log_incarnation_id,
            expected_epoch="owner", resolve_target=no_lookup,
        )
        assert ack == latest
        assert ack.sequence == 2 and ack.receipt_sha256 == second.digest
    no_lookup.assert_not_called()
    assert store.read_record(root, first.identity.request_id)["node-dispatch"]["receipt-sequence"] == 1
    assert store.read_record(root, second.identity.request_id)["node-dispatch"]["receipt-sequence"] == 2


def test_changed_latest_duplicate_and_sequence_gap_do_not_advance(system):
    _, _, _, central, receipt = system
    _accept(system)
    before = central.path.read_bytes()
    for changed in (replace(receipt, state="effect-intent"), replace(receipt, sequence=3)):
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            _accept(system, changed)
    assert central.path.read_bytes() == before


def test_initial_cursor_also_requires_sequence_one(system):
    _, _, _, central, first = system
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        _accept(system, replace(first, sequence=2))
    assert not central.path.exists()


def test_unknown_new_log_incarnation_never_resets(system):
    root, _, local, central, first = system
    _accept(system)
    before = central.path.read_bytes()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        central.accept(
            first, log_incarnation_id=str(uuid4()), expected_epoch="owner",
            resolve_target=lambda identity: _target(root, identity),
        )
    assert central.path.read_bytes() == before
    assert read_json_with_retry(central.path)["log-incarnation-id"] == local.log_incarnation_id


@pytest.mark.parametrize("field,value", [("server-id", "wrong"), ("node-id", "wrong"), ("version", 2)])
def test_persisted_identity_mismatch_fails_closed(system, field, value):
    _, _, _, central, _ = system
    _accept(system)
    cursor = read_json_with_retry(central.path)
    cursor[field] = value
    atomic_write_json(central.path, cursor)
    with pytest.raises(AudiaGenticError):
        _accept(system)


@pytest.mark.parametrize("node", ["con", "nul", "aux", "com1", "node"])
def test_checkpoint_filename_is_fixed_prefix_digest_not_a_device_name(tmp_path, node):
    service = _running(tmp_path)
    central = NodeReceiptCheckpoints(service, server_id="server", node_id=node)
    assert central.path.parent == service.root / "node-receipt-checkpoints"
    assert central.path.name == "node-" + hashlib.sha256(node.encode()).hexdigest() + ".json"


@pytest.mark.parametrize("committed_then_error", [False, True])
def test_cursor_write_failure_never_acknowledges_or_accepts_followup(system, monkeypatch, committed_then_error):
    root, service, local, central, first = system
    real_write = module.atomic_write_json
    def fail_write(path, value):
        if committed_then_error:
            real_write(path, value)
        raise OSError("simulated checkpoint persistence failure")
    monkeypatch.setattr(module, "atomic_write_json", fail_write)
    acknowledgements = []
    with pytest.raises(OSError):
        acknowledgements.append(_accept(system))
    assert not acknowledgements
    canonical = store.read_record(root, first.identity.request_id)
    assert canonical["node-dispatch"]["receipt-sequence"] == 1
    for pending in (first, replace(first, sequence=2, state="effect-intent")):
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            _accept(system, pending)
    assert local.ack_checkpoint().through_sequence == 0
    monkeypatch.setattr(module, "atomic_write_json", real_write)
    restarted = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    ack = restarted.accept(
        first, log_incarnation_id=local.log_incarnation_id, expected_epoch="owner",
        resolve_target=lambda identity: _target(root, identity),
    )
    assert ack.sequence == 1
    assert store.read_record(root, first.identity.request_id)["revision"] == canonical["revision"]


def test_canonical_newer_than_pending_is_conflict_not_inferred_recovery(system):
    root, _, _, central, first = system
    for receipt in (first, replace(first, sequence=2, state="effect-intent")):
        target = _target(root, receipt.identity)
        store.apply_owned_node_receipt(
            root, receipt.identity.request_id, receipt=receipt.public_payload(),
            owner_epoch=target.owner_epoch, worker_id=target.worker_id,
            attempt_epoch=target.attempt_epoch, expected_revision=target.expected_revision,
        )
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        _accept(system, first)
    assert not central.path.exists()


def test_runtime_resolver_cannot_claim_generic_success(system):
    _, _, local, central, first = system
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        central.accept(
            first, log_incarnation_id=local.log_incarnation_id,
            expected_epoch="owner", resolve_target=lambda identity: True,
        )
    assert not central.path.exists()


def test_stale_audit_epoch_is_not_cursor_authority_after_restart(system):
    _, service, local, _, first = system
    _accept(system)
    _restart(service, "replacement")
    restarted = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    no_lookup = Mock(side_effect=AssertionError("cumulative duplicate must not resolve old command"))
    ack = restarted.accept(
        first, log_incarnation_id=local.log_incarnation_id, expected_epoch="replacement", resolve_target=no_lookup,
    )
    assert ack.sequence == 1 and ack.gateway_owner_epoch == "replacement"
    assert read_json_with_retry(restarted.path)["gateway-owner-epoch"] == "owner"
    with pytest.raises(AudiaGenticError, match="CON-MSVC-014"):
        restarted.accept(
            first, log_incarnation_id=local.log_incarnation_id, expected_epoch="owner", resolve_target=no_lookup,
        )


def test_canonical_and_cursor_commit_order_owner_replacement_on_service_lock(system):
    root, service, local, central, first = system
    entered, release, replacement_started, replaced = Event(), Event(), Event(), Event()
    def resolver(identity):
        entered.set()
        assert release.wait(5)
        return _target(root, identity)
    def replace_owner():
        replacement_started.set()
        record = service.read()
        service.transition(
            "stopping", expected_revision=record.revision, expected_epoch="owner",
            new_owner_epoch="replacement",
        )
        replaced.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(
            central.accept, first, log_incarnation_id=local.log_incarnation_id,
            expected_epoch="owner", resolve_target=resolver,
        )
        try:
            assert entered.wait(5)
            replacement = pool.submit(replace_owner)
            assert replacement_started.wait(5)
            assert not replaced.wait(0.1)
            assert not central.path.exists()
        finally:
            release.set()
        ack = accepted.result(timeout=5)
        replacement.result(timeout=5)
    assert ack.sequence == 1
    assert read_json_with_retry(central.path)["sequence"] == 1
    assert service.read().owner_epoch == "replacement"


def test_hard_kill_after_canonical_before_cursor_recovers_exact_replay(system, tmp_path, monkeypatch):
    import subprocess
    import sys
    import time

    root, service, local, central, first = system
    ready = tmp_path / "canonical-committed.ready"
    before = store.read_record(root, first.identity.request_id)["revision"]
    script = r"""
import sys
import threading
from pathlib import Path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node import checkpoints as module
from audiagentic.components.agents.gateway.node.checkpoints import CanonicalReceiptTarget, NodeReceiptCheckpoints
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.components.agents.gateway.node.receipts import Receipt
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey

base, project, request_id, log_id, ready_path = sys.argv[1:]
project, ready_path = Path(project), Path(ready_path)
service = ManagedServiceStore(ServiceKey("gateway", "checkpoints"), root=Path(base))
owner = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
record = store.read_record(project, request_id)
identity = CommandIdentity.from_mapping(record["node-dispatch"]["identity"])
receipt = Receipt(identity, "prepared", 1)

def resolver(identity):
    record = store.read_record(project, identity.request_id)
    return CanonicalReceiptTarget(
        project, record["dispatch-owner-epoch"], record["worker-id"],
        record["attempt-epoch"], record["revision"],
    )

def pause_before_cursor(path, cursor):
    record = store.read_record(project, request_id)
    assert record["node-dispatch"]["receipt-sequence"] == 1
    assert record["node-dispatch"]["receipt-sha256"] == receipt.digest
    assert not path.exists()
    ready_path.write_text("canonical-committed-no-cursor-no-ack", encoding="utf-8")
    threading.Event().wait(60)
    raise AssertionError("parent did not terminate its child")

module.atomic_write_json = pause_before_cursor
owner.accept(receipt, log_incarnation_id=log_id, expected_epoch="owner", resolve_target=resolver)
raise AssertionError("child unexpectedly returned ACK metadata")
"""
    environment = dict(os.environ)
    import_root = str(Path(module.__file__).resolve().parents[5])
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, (import_root, environment.get("PYTHONPATH"))))
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(service.root.parents[2]), str(root),
         first.identity.request_id, local.log_incarnation_id, str(ready)],
        cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 30
        while not ready.exists():
            if child.poll() is not None:
                stdout, stderr = child.communicate(timeout=5)
                pytest.fail(f"child exited before canonical commit: {child.returncode}; {stdout}; {stderr}")
            if time.monotonic() >= deadline:
                pytest.fail("child did not signal canonical commit")
            time.sleep(0.02)
        assert child.poll() is None
        assert not central.path.exists()
        canonical_path = root / ".audiagentic" / "runtime" / "agent-execution-gateway" / first.identity.request_id / "record.json"
        committed_bytes = canonical_path.read_bytes()
        assert store.read_record(root, first.identity.request_id)["revision"] == before + 1
        assert local.ack_checkpoint().through_sequence == 0
        child.kill()  # Only this owned child: TerminateProcess / SIGKILL.
        child.communicate(timeout=10)
        assert child.returncode != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    _restart(service, "after-kill")
    restarted = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    acknowledgements = []
    acknowledgements.append(restarted.accept(
        first, log_incarnation_id=local.log_incarnation_id, expected_epoch="after-kill",
        resolve_target=lambda identity: _target(root, identity),
    ))
    assert canonical_path.read_bytes() == committed_bytes
    assert read_json_with_retry(restarted.path)["sequence"] == 1
    assert read_json_with_retry(restarted.path)["gateway-owner-epoch"] == "after-kill"
    assert acknowledgements[0].sequence == 1
    assert acknowledgements[0].receipt_sha256 == first.digest
    assert local.ack_checkpoint().through_sequence == 0  # still no network ACK delivery


def test_corrupt_cursor_does_not_reset_or_apply_another_receipt(system):
    root, _, _, central, receipt = system
    _accept(system)
    canonical_before = store.read_record(root, receipt.identity.request_id)["revision"]
    central.path.write_text("{invalid checkpoint json", encoding="utf-8")
    before = central.path.read_bytes()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        _accept(system)
    assert central.path.read_bytes() == before
    assert store.read_record(root, receipt.identity.request_id)["revision"] == canonical_before


@pytest.mark.parametrize("change", ["worker", "revision", "root"])
def test_fixed_mutator_rejects_wrong_resolved_canonical_fences_without_custody(system, change):
    root, _, local, central, receipt = system
    target = _target(root, receipt.identity)
    if change == "worker":
        target = replace(target, worker_id="wrong-worker")
    elif change == "revision":
        target = replace(target, expected_revision=0)
    else:
        target = replace(target, project_root=root.parent / "wrong-project")
    with pytest.raises(AudiaGenticError):
        central.accept(
            receipt, log_incarnation_id=local.log_incarnation_id, expected_epoch="owner",
            resolve_target=lambda identity: target,
        )
    assert not central.path.exists()
    assert store.read_record(root, receipt.identity.request_id)["node-dispatch"]["receipt-sequence"] == 0
