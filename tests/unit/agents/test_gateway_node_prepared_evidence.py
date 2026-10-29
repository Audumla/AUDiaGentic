"""Private prepared evidence binds exact commands, never orphan authorization."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.agents_paths import (
    gateway_node_prepared_evidence_path,
    gateway_request_dir,
    gateway_request_maintenance_lock_path,
    gateway_request_path,
)
from audiagentic.components.agents.gateway import output, store
from audiagentic.components.agents.gateway.node import prepared_evidence as module
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity, canonical_json
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    build_final_command_payload,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.node.prepared_evidence import (
    RetainedPreparedEvidence,
    persist_prepared_once,
    read_prepared_evidence,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def prepared(tmp_path):
    raw = "SECRET accepted raw body λ\r\n"
    record = store.build_record(
        execution_profile_id="profile", prompt_body=raw, session_id="ses_evidence",
        node_placement={"node-id": "node", "workspace-id": "workspace", "principal-id": "principal", "server-project-id": "project", "grant-revision": 1},
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="owner", expected_revision=0)
    record = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="owner", worker_id="worker", expected_revision=claimed["revision"])
    semantic = PromptSemanticIdentity("a" * 64, "b" * 64, "prompt", "profile", 1, hashlib.sha256(b"expanded").hexdigest(), hashlib.sha256(raw.encode()).hexdigest())
    binding = PreparationBinding("cmd:private-name", record["request-id"], "node", "node-epoch", "owner", 1, "workspace", 1, 1, "challenge", "prepare-request")
    retained = prepare_node_command(
        binding=binding, semantic=semantic, raw_prompt=raw, rendered_prompt="NODE ONLY render",
        manifest_id="manifest", context_fingerprint="c" * 64, runtime_digest="d" * 64,
        provider_manifest=b"NODE ONLY bundle /node/local/path", worker_id="worker", attempt_epoch=record["attempt-epoch"],
        provider_id="provider", model_id="vendor/model", model_alias=None,
    )
    payload = build_final_command_payload(retained, raw)
    identity = command_for(retained.attestation, payload)
    return tmp_path, record, identity, retained.attestation, payload


def command_for(attestation, payload):
    b = attestation.binding
    return CommandIdentity(b.command_id, b.request_id, b.node_id, b.node_epoch, b.gateway_owner_epoch, b.connection_generation, b.workspace_id, b.grant_revision, b.binding_generation, hashlib.sha256(canonical_json(payload)).hexdigest(), attestation.semantic.execution_profile_id)


def test_owner_takeover_preserves_original_bound_preparation(prepared):
    root, record, identity, accepted, _ = persisted_bound(prepared)
    recovered = store.takeover_nonterminal_owner(root, identity.request_id,
        expected_owner_epoch=record["dispatch-owner-epoch"], new_owner_epoch="replacement")
    assert recovered["worker-id"] == accepted.worker_id
    assert recovered["attempt-epoch"] == accepted.attempt_epoch
    assert recovered["node-dispatch"]["identity"] == identity.to_mapping()
    assert read_prepared_evidence(root, identity, recovered).attestation == accepted


def mutable(value):
    return json.loads(canonical_json(value))


def fences(record):
    return dict(owner_epoch=record["dispatch-owner-epoch"], worker_id=record["worker-id"], attempt_epoch=record["attempt-epoch"], expected_revision=record["revision"])


def bind(root, record, identity, attestation, payload):
    return store.bind_owned_node_dispatch(root, record["request-id"], identity=identity, command_payload=payload, accepted_attestation=attestation, **fences(record))


def authorize(root, record, identity, attestation):
    return store.authorize_owned_node_effect(root, record["request-id"], identity=identity, authorization_id="original-auth", accepted_attestation=attestation, current_node_epoch=identity.node_epoch, current_connection_generation=identity.connection_generation, **fences(record))


def persisted_bound(prepared, *, authorized=True):
    root, record, identity, attestation, payload = prepared
    persist_prepared_once(root, identity, attestation=attestation, payload=payload)
    record = bind(root, record, identity, attestation, payload)
    if authorized:
        record = authorize(root, record, identity, attestation)
    return root, record, identity, attestation, payload


def test_persist_before_bind_canonical_bytes_and_typed_private_roundtrip(prepared):
    root, record, identity, attestation, payload = prepared
    canonical_record = gateway_request_path(root, identity.request_id).read_bytes()
    evidence = persist_prepared_once(root, identity, attestation=attestation, payload=payload)
    assert type(evidence) is RetainedPreparedEvidence
    path = gateway_node_prepared_evidence_path(root, identity)
    assert path.parent == gateway_request_dir(root, identity.request_id) / "runtime"
    assert path.name == f"node-prepared-{hashlib.sha256(canonical_json(identity.to_mapping())).hexdigest()}.json"
    assert identity.command_id not in path.name
    value = json.loads(path.read_bytes())
    assert value == {"version": 1, "kind": "node-prepared-v1", "attestation": attestation.to_mapping(), "final-command-payload": mutable(payload)}
    assert canonical_json(value) == path.read_bytes()
    assert b"NODE ONLY" not in path.read_bytes() and b"/node/local/path" not in path.read_bytes()
    assert evidence.attestation == attestation
    assert gateway_request_path(root, identity.request_id).read_bytes() == canonical_record
    assert record["node-dispatch"] is None
    for required in (True, False):
        with pytest.raises(AudiaGenticError):
            read_prepared_evidence(root, identity, record, require_authorized=required)
    bound = bind(root, record, identity, attestation, payload)
    assert read_prepared_evidence(root, identity, bound, require_authorized=False) == evidence
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, identity, bound)
    authorized = authorize(root, bound, identity, attestation)
    assert read_prepared_evidence(root, identity, authorized) == evidence


def test_exact_replay_is_read_only_and_freezes_caller_payload(prepared, monkeypatch):
    root, _, identity, attestation, payload = prepared
    caller_payload = mutable(payload)
    write = Mock(wraps=module.atomic_write_bytes)
    monkeypatch.setattr(module, "atomic_write_bytes", write)
    first = persist_prepared_once(root, identity, attestation, caller_payload)
    caller_payload["raw-prompt"] = "changed by caller"
    with pytest.raises(TypeError):
        first.final_command_payload["semantic"]["prompt-id"] = "changed"
    with pytest.raises(FrozenInstanceError):
        first.attestation = attestation
    assert "changed by caller" not in first.final_command_payload["raw-prompt"]
    assert "SECRET" not in repr(first)
    assert not hasattr(first, "to_mapping")
    assert persist_prepared_once(root, identity, attestation, payload) == first
    write.assert_called_once()
    if os.name == "posix":
        assert gateway_node_prepared_evidence_path(root, identity).stat().st_mode & 0o077 == 0


def test_existing_corruption_conflicts_and_is_never_overwritten(prepared):
    root, _, identity, attestation, payload = prepared
    persist_prepared_once(root, identity, attestation, payload)
    path = gateway_node_prepared_evidence_path(root, identity)
    path.write_bytes(b"corrupt PRIVATE input")
    with pytest.raises(AudiaGenticError) as error:
        persist_prepared_once(root, identity, attestation, payload)
    assert path.read_bytes() == b"corrupt PRIVATE input"
    assert "PRIVATE" not in str(error.value) and str(path) not in str(error.value)


def test_changed_input_cannot_overwrite_original_command_evidence(prepared):
    root, _, identity, attestation, payload = prepared
    persist_prepared_once(root, identity, attestation, payload)
    path = gateway_node_prepared_evidence_path(root, identity)
    original = path.read_bytes()
    changed = mutable(payload)
    changed["raw-prompt"] = "replacement secret"
    with pytest.raises(AudiaGenticError):
        persist_prepared_once(root, identity, attestation, changed)
    assert path.read_bytes() == original


def test_missing_file_remains_unresolved_and_read_does_not_write(prepared):
    root, record, identity, attestation, payload = prepared
    record = authorize(root, bind(root, record, identity, attestation, payload), identity, attestation)
    canonical_record = gateway_request_path(root, identity.request_id).read_bytes()
    path = gateway_node_prepared_evidence_path(root, identity)
    assert not path.exists()
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, identity, record)
    assert not path.exists()
    assert gateway_request_path(root, identity.request_id).read_bytes() == canonical_record


@pytest.mark.parametrize("change", ["missing", "extra", "kind", "version-bool", "version-float", "pretty", "newline", "duplicate", "invalid-json", "invalid-utf8", "attestation-missing", "payload-missing", "changed-model", "wrong-sha"])
def test_malformed_forged_or_noncanonical_evidence_never_reads(prepared, change):
    root, record, identity, _, _ = persisted_bound(prepared)
    path = gateway_node_prepared_evidence_path(root, identity)
    value = json.loads(path.read_bytes())
    if change == "missing":
        del value["attestation"]
    elif change == "extra":
        value["unexpected"] = "private"
    elif change == "kind":
        value["kind"] = "different"
    elif change == "version-bool":
        value["version"] = True
    elif change == "version-float":
        value["version"] = 1.0
    elif change == "attestation-missing":
        del value["attestation"]["worker-id"]
    elif change == "payload-missing":
        del value["final-command-payload"]["raw-prompt"]
    elif change == "changed-model":
        value["attestation"]["model-id"] = "forged-model"
        value["final-command-payload"]["attestation"]["model-id"] = "forged-model"
    elif change == "wrong-sha":
        value["attestation"]["provider-manifest-sha256"] = "e" * 64
        value["final-command-payload"]["attestation"]["provider-manifest-sha256"] = "e" * 64
    raw = canonical_json(value)
    if change == "pretty":
        raw = json.dumps(value, indent=2).encode()
    elif change == "newline":
        raw += b"\n"
    elif change == "duplicate":
        raw = b'{"version":1,' + raw[1:]
    elif change == "invalid-json":
        raw = b'{"SECRET":'
    elif change == "invalid-utf8":
        raw = b'\xff'
    path.write_bytes(raw)
    canonical_record = gateway_request_path(root, identity.request_id).read_bytes()
    with pytest.raises(AudiaGenticError) as error:
        read_prepared_evidence(root, identity, record)
    assert "SECRET" not in str(error.value)
    assert gateway_request_path(root, identity.request_id).read_bytes() == canonical_record


@pytest.mark.parametrize("field,value", [
    ("request-id", "req_other"), ("execution-profile-id", "other-profile"),
    ("worker-id", "other-worker"), ("attempt-epoch", 2), ("attempt-epoch", True),
])
def test_wrong_canonical_request_or_attempt_rejected(prepared, field, value):
    root, record, identity, _, _ = persisted_bound(prepared)
    changed = deepcopy(record)
    changed[field] = value
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, identity, changed)


@pytest.mark.parametrize("field,value", [("attestation-sha256", "e" * 64), ("authorization-id", None), ("authorization-id", ""), ("authorization-state", "not-authorized")])
def test_original_binding_and_authorization_are_required(prepared, field, value):
    root, record, identity, _, _ = persisted_bound(prepared)
    changed = deepcopy(record)
    changed["node-dispatch"][field] = value
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, identity, changed)


@pytest.mark.parametrize("field,value", [("node-id", "other-node"), ("workspace-id", "other-workspace"), ("grant-revision", 2)])
def test_canonical_admission_placement_must_match_command(prepared, field, value):
    root, record, identity, _, _ = persisted_bound(prepared)
    changed = deepcopy(record)
    changed["node-placement"][field] = value
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, identity, changed)


@pytest.mark.parametrize("stage,state", [("effect-intent", "uncertain"), ("native-accepted", "effect-observed"), ("terminal", "terminal")])
def test_original_authorization_survives_historical_receipt_state(prepared, stage, state):
    root, record, identity, _, _ = persisted_bound(prepared)
    receipt = {"identity": identity.to_mapping(), "state": stage, "receipt-sequence": 1, "output-sha256": "e" * 64 if stage == "terminal" else None}
    record = store.apply_owned_node_receipt(root, identity.request_id, receipt=receipt, **fences(record))
    assert record["node-dispatch"]["authorization-state"] == state
    assert read_prepared_evidence(root, identity, record).attestation == prepared[3]


def test_late_command_a_cannot_read_against_new_canonical_command_b(prepared):
    root, record, a, attestation_a, payload_a = prepared
    evidence_a = persist_prepared_once(root, a, attestation_a, payload_a)
    old_file = gateway_node_prepared_evidence_path(root, a)
    old_bytes = old_file.read_bytes()
    record_a = bind(root, record, a, attestation_a, payload_a)
    assert read_prepared_evidence(root, a, record_a, require_authorized=False) == evidence_a
    # The canonical retirement/rebind policy belongs to the store owner. Model
    # its post-retirement B snapshot here; this file owner performs no transition.
    binding_b = replace(attestation_a.binding, command_id="command-b", binding_generation=2, preparation_challenge="challenge-b")
    attestation_b = replace(attestation_a, binding=binding_b)
    payload_b = mutable(payload_a)
    payload_b["attestation"] = attestation_b.to_mapping()
    payload_b["preparation-challenge"] = "challenge-b"
    b = command_for(attestation_b, payload_b)
    persist_prepared_once(root, b, attestation_b, payload_b)
    assert gateway_node_prepared_evidence_path(root, b) != old_file
    assert old_file.read_bytes() == old_bytes
    record_b = deepcopy(record_a)
    record_b["node-dispatch"].update(identity=b.to_mapping(), **{"attestation-sha256": attestation_b.digest})
    assert read_prepared_evidence(root, b, record_b, require_authorized=False).attestation == attestation_b
    for authorized in (False, True):
        with pytest.raises(AudiaGenticError):
            read_prepared_evidence(root, a, record_b, require_authorized=authorized)
    assert len(list(old_file.parent.glob("node-prepared-*.json"))) == 2


def test_new_binding_never_reuses_previous_command_file(prepared):
    root, record, a, attestation, payload = persisted_bound(prepared)
    b = replace(a, command_id="command-b")
    with pytest.raises(AudiaGenticError):
        read_prepared_evidence(root, b, record)
    assert not gateway_node_prepared_evidence_path(root, b).exists()
    assert gateway_node_prepared_evidence_path(root, a).exists()


def test_parallel_exact_writers_publish_once(prepared, monkeypatch):
    root, _, identity, attestation, payload = prepared
    write = Mock(wraps=module.atomic_write_bytes)
    monkeypatch.setattr(module, "atomic_write_bytes", write)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: persist_prepared_once(root, identity, attestation, payload), range(8)))
    assert all(result == results[0] for result in results)
    write.assert_called_once()


def test_public_response_reader_cannot_select_private_prepared_evidence(prepared, monkeypatch):
    root, record, identity, _, _ = persisted_bound(prepared)
    path = gateway_node_prepared_evidence_path(root, identity)
    fake_artifact = {"artifact-id": "node-prepared-v1", "request-id": identity.request_id, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "path": str(path), "media-type": "text/plain; charset=utf-8"}
    output.persist_final_response(root, identity.request_id, "PUBLIC final response")
    original_read = Path.read_bytes
    reads = []
    def read(candidate):
        assert candidate != path, "public response read followed a private path"
        reads.append(candidate)
        return original_read(candidate)
    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(AudiaGenticError):
        output.read_final_response(root, identity.request_id, fake_artifact)
    assert reads and all(candidate.name == "final-response.txt" for candidate in reads)
    assert record["response-artifact"] is None


def _symlink(link, target, *, directory):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"symlink creation unavailable: {type(error).__name__}")


@pytest.mark.parametrize("which", ["file", "runtime", "root", "lock", "guard"])
def test_symlink_paths_are_never_followed_for_read_or_write(prepared, tmp_path, which):
    root, record, identity, attestation, payload = prepared
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "private.json"
    target.write_bytes(b"outside must remain untouched")
    path = gateway_node_prepared_evidence_path(root, identity)
    redirected_root = root
    if which == "file":
        path.parent.mkdir(parents=True, exist_ok=True)
        _symlink(path, target, directory=False)
    elif which == "runtime":
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        _symlink(path.parent, outside, directory=True)
    elif which == "root":
        redirected_root = tmp_path / "linked-root"
        _symlink(redirected_root, root, directory=True)
    else:
        lock = gateway_request_maintenance_lock_path(root, identity.request_id)
        lock.parent.mkdir(parents=True, exist_ok=True)
        link = lock if which == "lock" else lock.with_name(lock.name + ".guard")
        _symlink(link, target, directory=False)
    with pytest.raises(AudiaGenticError):
        persist_prepared_once(redirected_root, identity, attestation, payload)
    if which in {"file", "runtime", "root"}:
        with pytest.raises(AudiaGenticError):
            read_prepared_evidence(redirected_root, identity, record, require_authorized=False)
    assert target.read_bytes() == b"outside must remain untouched"


@pytest.mark.skipif(os.name != "nt", reason="Windows junction qualification")
def test_windows_junction_runtime_is_rejected_without_touching_target(prepared, tmp_path):
    root, record, identity, attestation, payload = prepared
    outside = tmp_path / "junction-target"
    outside.mkdir()
    path = gateway_node_prepared_evidence_path(root, identity)
    path.parent.parent.mkdir(parents=True, exist_ok=True)
    # Named test paths only, one shell, no destructive shell operation.
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(path.parent), str(outside)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    try:
        assert path.parent.is_junction()
        with pytest.raises(AudiaGenticError):
            persist_prepared_once(root, identity, attestation, payload)
        with pytest.raises(AudiaGenticError):
            read_prepared_evidence(root, identity, record, require_authorized=False)
        assert not list(outside.iterdir())
    finally:
        path.parent.rmdir()  # Remove the verified junction, never its target.
