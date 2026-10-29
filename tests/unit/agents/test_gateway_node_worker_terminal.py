"""Verified local worker terminals: exact preparation, private artifacts, no native ACK."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.contracts.execution_context import (
    SessionSpec,
    SubmissionEnvelope,
    build_manifest,
)
from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerErrorEnvelope,
    WorkerExecutionIdentity,
    WorkerHandshakeEnvelope,
    WorkerProcessEvidence,
    WorkerResultEnvelope,
    encode_worker_message,
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
from audiagentic.components.agents.gateway.node.terminal_output import parse_worker_terminal_output
from audiagentic.components.agents.gateway.queue import worker
from audiagentic.components.providers import providers_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_case(root):
    root.mkdir(parents=True, exist_ok=True)
    raw, rendered = "raw request", "PRIVATE rendered prompt\r\nλ"
    submission = SubmissionEnvelope(
        project_root=str(root),
        execution_profile_id="profile",
        component_profile="",
        prompt_body=raw,
        session=SessionSpec(),
        mode="async",
    )
    manifest = build_manifest(
        submission,
        manifest_id="manifest",
        request_id="request",
        resolved_at="2026-10-26T00:00:00Z",
        canonical_root=submission.validate(),
        execution_profile_id="profile",
        provider_id="fixture-provider",
        model_id="fixture-model",
        provider_isolation_tier="full-isolation",
        agent_runtime_digest="d" * 64,
        agent_config_fingerprint="a" * 64,
    )
    expected = WorkerExecutionIdentity(
        "worker",
        1,
        manifest.manifest_id,
        manifest.context_fingerprint,
        str(root.resolve()),
        "",
        "full-isolation",
    )
    request = providers_api.ProviderExecutionRequest(
        root.resolve(),
        "fixture-provider",
        "fixture-model",
        None,
        {"request-id": "request", "working-root": str(root.resolve()), "prompt-body": rendered},
        "worker",
        1,
        "full-isolation",
    )
    bundle = canonical_json(
        {
            "version": 1,
            "kind": "node-worker-preparation",
            "worker-identity": expected.to_mapping(tier_field="provider-isolation-tier"),
            "execution-manifest": manifest.to_mapping(),
            "provider-request": request.to_mapping(),
        }
    )
    binding = PreparationBinding(
        "command",
        "request",
        "node",
        "boot",
        "gateway",
        1,
        "workspace",
        1,
        1,
        "challenge",
        "prepare-request",
    )
    semantic = PromptSemanticIdentity(
        "a" * 64, "b" * 64, "prompt", "profile", 1, sha(b"expanded"), sha(raw.encode())
    )
    preparation = prepare_node_command(
        binding=binding,
        semantic=semantic,
        raw_prompt=raw,
        rendered_prompt=rendered,
        manifest_id="manifest",
        context_fingerprint=manifest.context_fingerprint,
        runtime_digest="d" * 64,
        provider_manifest=bundle,
        worker_id="worker",
        attempt_epoch=1,
        provider_id="fixture-provider",
        model_id="fixture-model",
        model_alias=None,
    )
    payload = build_final_command_payload(preparation, raw)
    identity = CommandIdentity(
        "command",
        "request",
        "node",
        "boot",
        "gateway",
        1,
        "workspace",
        1,
        1,
        sha(canonical_json(payload)),
        "profile",
    )
    store = NodeReceiptStore(
        node_id="node", node_epoch="boot", gateway_owner_epoch="gateway", root=root / "receipts"
    )
    store.prepare(identity, canonical_json(payload))
    auth_request = Frame(
        1,
        "effect-authorize",
        "auth-request",
        "node",
        "boot",
        "gateway",
        1,
        {"identity": identity.to_mapping()},
    )
    auth_reply = Frame(
        1,
        "effect-authorized",
        "auth-reply",
        "node",
        "boot",
        "gateway",
        2,
        {
            "identity": identity.to_mapping(),
            "authorization-request-id": "auth-request",
            "authorization-id": "grant",
            "authorized": True,
        },
    )
    assert store.effect_intent(identity, auth_request, auth_reply, connection_generation=1)
    return SimpleNamespace(
        store=store,
        preparation=preparation,
        identity=identity,
        expected=expected,
        request=request.to_mapping(),
        payload=payload,
        manifest=manifest,
        auth_request=auth_request,
        auth_reply=auth_reply,
    )


def mint_proof(
    monkeypatch, case, *, identity=None, result_changes=None, result_data=None, error=False
):
    """Real supervisor's proof minting with fake child I/O, no provider invocation."""
    expected = identity or case.expected
    request = dict(case.request) | {
        "project-root": expected.project_root,
        "worker-id": expected.worker_id,
        "attempt-epoch": expected.attempt_epoch,
        "provider-isolation-tier": expected.provider_isolation_tier,
    }
    process = WorkerProcessEvidence(27182, "test-process-creation", expected.project_root)
    result = {
        "provider-id": "fixture-provider",
        "model-id": "fixture-model",
        "worker-id": expected.worker_id,
        "attempt-epoch": expected.attempt_epoch,
        "result-data": result_data
        if result_data is not None
        else {"output": "Verified answer\r\n  λ\n"},
    }
    result.update(result_changes or {})
    terminal = (
        WorkerErrorEnvelope(expected, process, "EXT-PEXE-001", "providers", "failed")
        if error
        else WorkerResultEnvelope(expected, process, result)
    )
    output = (
        encode_worker_message(WorkerHandshakeEnvelope(expected, process))
        + "\n"
        + encode_worker_message(terminal)
        + "\n"
    )
    exited = []

    @contextmanager
    def fake_spawn(*args, **kwargs):
        try:
            yield SimpleNamespace(pid=27182, poll=lambda: 0)
        finally:
            exited.append(True)

    monkeypatch.setattr(worker, "spawn_supervised", fake_spawn)
    monkeypatch.setattr(worker, "process_creation_identity", lambda pid: "test-process-creation")
    monkeypatch.setattr(worker, "_wait_for_provider_terminal", lambda *args, **kwargs: (output, ""))
    monkeypatch.setattr(providers_api, "prepare_provider_execution_environment", lambda req: {})
    proof = worker.execute_verified_isolated_provider_turn(
        identity=expected,
        execution_request=request,
        allowed_model_ids={"fixture-model", "other-model"},
    )
    assert exited == [True]
    return proof


def commit(case, proof):
    return case.store.terminal_from_worker_result(
        case.identity, preparation=case.preparation, proof=proof
    )


def test_direct_terminal_private_kind_exact_text_reopen_and_no_native_acceptance(
    tmp_path, monkeypatch
):
    case = make_case(tmp_path / "case")
    before = case.store.receipts_after()
    proof = mint_proof(monkeypatch, case)
    receipt = commit(case, proof)
    assert [r.state for r in case.store.receipts_after()] == [
        "prepared",
        "effect-intent",
        "terminal",
    ]
    assert case.store.receipts_after()[:2] == before
    assert case.store.native_reference(case.identity) is None
    assert case.store.authorization_id(case.identity) == "grant"
    assert (
        receipt.sequence == 3
        and case.store.artifact_kind(case.identity) == "worker-terminal-result"
    )
    assert proof.worker_exited is True and proof.cleanup_proven is False
    parsed = case.store.worker_terminal_output(case.identity)
    assert parsed.text == "Verified answer\r\n  λ\n"
    assert parsed.media_type == "text/plain; charset=utf-8"
    assert "Verified answer" not in repr(parsed)
    raw = case.store.output(case.identity).encode()
    assert sha(raw) == receipt.output_sha256
    assert json.loads(raw)["outcome"]["status"] == "success"
    assert (
        "PRIVATE rendered prompt" not in raw.decode()
        and case.expected.project_root not in raw.decode()
    )
    assert commit(case, proof) == receipt
    reopened = NodeReceiptStore(
        node_id="node", node_epoch="boot", gateway_owner_epoch="gateway", root=case.store.root
    )
    assert reopened.worker_terminal_output(case.identity) == parsed
    assert not reopened.effect_intent(
        case.identity, case.auth_request, case.auth_reply, connection_generation=1
    )
    with sqlite3.connect(case.store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT native_ref FROM commands").fetchone()[0] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("worker_id", "other-worker"),
        ("attempt_epoch", 2),
        ("manifest_id", "other-manifest"),
        ("context_fingerprint", "e" * 64),
        ("component_profile", "other-profile"),
        ("provider_isolation_tier", "partial-isolation"),
        ("project_root", "other-root"),
    ],
)
def test_genuine_proof_for_another_worker_identity_fails(tmp_path, monkeypatch, field, value):
    case = make_case(tmp_path / "case")
    if field == "project_root":
        value = str((tmp_path / "other-root").resolve())
    proof = mint_proof(monkeypatch, case, identity=replace(case.expected, **{field: value}))
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        commit(case, proof)
    assert case.store.get(case.identity).state == "effect-intent"
    assert len(case.store.receipts_after()) == 2


@pytest.mark.parametrize(
    "result_data",
    [
        {},
        {"output": 42},
        {"output": None},
        {"output": ["answer"]},
        {"output": "answer", "final_media_type": 42},
        {"output": "answer", "final_media_type": "application/octet-stream"},
    ],
)
def test_bad_output_is_never_coerced(tmp_path, monkeypatch, result_data):
    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case, result_data=result_data)
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        commit(case, proof)
    assert case.store.get(case.identity).state == "effect-intent"
    assert not case.store.outputs.exists()


def test_unprepared_model_and_changed_terminal_rejected(tmp_path, monkeypatch):
    case = make_case(tmp_path / "case")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        commit(case, mint_proof(monkeypatch, case, result_changes={"model-id": "other-model"}))
    receipt = commit(case, mint_proof(monkeypatch, case))
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        commit(case, mint_proof(monkeypatch, case, result_data={"output": "changed"}))
    assert case.store.get(case.identity) == receipt


@pytest.mark.parametrize("fake", [None, True, {"verified": True}, "serialized proof"])
def test_peer_data_cannot_be_worker_proof(tmp_path, fake):
    case = make_case(tmp_path / "case")
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        commit(case, fake)
    assert case.store.get(case.identity).state == "effect-intent"


def test_error_and_cleanup_failure_leave_effect_uncertain(tmp_path, monkeypatch):
    case = make_case(tmp_path / "case")
    with pytest.raises(AudiaGenticError, match="EXT-PEXE-001"):
        mint_proof(monkeypatch, case, error=True)

    @contextmanager
    def broken_home():
        home = tmp_path / "worker-home"
        home.mkdir()
        yield home
        raise OSError("cleanup failed")

    monkeypatch.setattr(worker, "_private_worker_home", broken_home)
    with pytest.raises(OSError, match="cleanup failed"):
        mint_proof(monkeypatch, case)
    assert case.store.get(case.identity).state == "effect-intent"
    assert case.store.authorization_id(case.identity) == "grant"


@pytest.mark.parametrize(
    "hazard",
    [
        "prepared",
        "missing-auth",
        "stale-owner",
        "native-accepted",
        "plaintext-terminal",
        "legacy-plaintext",
    ],
)
def test_no_bypassing_intent_owner_or_native_history(tmp_path, monkeypatch, hazard):
    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case)
    if hazard == "prepared":
        with sqlite3.connect(case.store.path) as db:
            db.execute("UPDATE commands SET state='prepared',authorization_id=NULL")
    elif hazard == "missing-auth":
        with sqlite3.connect(case.store.path) as db:
            db.execute("UPDATE commands SET authorization_id=NULL")
    elif hazard == "stale-owner":
        case.store.advance_epoch(node_epoch="other-boot", gateway_owner_epoch="gateway")
    else:
        case.store.native_accepted(case.identity, native_ref="actual-native-ref")
        if hazard in {"plaintext-terminal", "legacy-plaintext"}:
            receipt = case.store.terminal(case.identity, text="historical plaintext")
            assert receipt.output_sha256 == sha(b"historical plaintext")
            if hazard == "legacy-plaintext":
                with sqlite3.connect(case.store.path) as db:
                    db.execute("UPDATE commands SET native_ref=NULL,artifact_kind=NULL")
    before = case.store.receipts_after()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        commit(case, proof)
    assert case.store.receipts_after() == before


@pytest.mark.parametrize("damage", ["render", "bundle", "stored-payload", "accepted-attestation"])
def test_preparation_substitution_rejected(tmp_path, monkeypatch, damage):
    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case)
    if damage == "render":
        object.__setattr__(case.preparation, "_rendered_prompt", "substituted")
    elif damage == "bundle":
        object.__setattr__(case.preparation, "_provider_manifest", b"substituted")
    elif damage == "accepted-attestation":
        case.preparation = replace(
            case.preparation,
            attestation=replace(case.preparation.attestation, runtime_digest="e" * 64),
        )
    else:
        with sqlite3.connect(case.store.path) as db:
            db.execute("UPDATE commands SET payload=?", (canonical_json({"substituted": True}),))
    with pytest.raises(AudiaGenticError):
        commit(case, proof)
    assert case.store.get(case.identity).state == "effect-intent"


def rebind_bundle_fixture(case, bundle):
    private = canonical_json(bundle)
    case.preparation = replace(
        case.preparation,
        _provider_manifest=private,
        attestation=replace(case.preparation.attestation, provider_manifest_sha256=sha(private)),
    )
    case.payload = build_final_command_payload(case.preparation, "raw request")
    case.identity = replace(case.identity, payload_sha256=sha(canonical_json(case.payload)))
    with sqlite3.connect(case.store.path) as db:
        db.execute(
            "UPDATE commands SET identity=?,payload=?",
            (canonical_json(case.identity.to_mapping()).decode(), canonical_json(case.payload)),
        )


@pytest.mark.parametrize(
    "hazard",
    [
        "manifest-root",
        "manifest-context",
        "manifest-request",
        "manifest-runtime",
        "manifest-profile",
        "request-provider",
        "request-model",
        "packet-root",
        "packet-prompt",
        "extra-identity",
        "bundle-kind",
        "bundle-version",
    ],
)
def test_bundle_hash_alone_is_insufficient(tmp_path, monkeypatch, hazard):
    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case)
    bundle = json.loads(case.preparation._provider_manifest)
    if hazard == "manifest-root":
        bundle["execution-manifest"]["identity"]["project_root"] = "/foreign"
    elif hazard == "manifest-context":
        bundle["execution-manifest"]["context_fingerprint"] = "e" * 64
    elif hazard == "manifest-request":
        bundle["execution-manifest"]["request_id"] = "other"
    elif hazard == "manifest-runtime":
        bundle["execution-manifest"]["identity"]["agent_runtime_digest"] = "e" * 64
    elif hazard == "manifest-profile":
        bundle["execution-manifest"]["identity"]["execution_profile_id"] = "other"
    elif hazard == "request-provider":
        bundle["provider-request"]["provider-id"] = "other"
    elif hazard == "request-model":
        bundle["provider-request"]["model-id"] = "other"
    elif hazard == "packet-root":
        bundle["provider-request"]["packet-data"]["working-root"] = "/foreign"
    elif hazard == "packet-prompt":
        bundle["provider-request"]["packet-data"]["prompt-body"] = "substituted"
    elif hazard == "extra-identity":
        bundle["worker-identity"]["untrusted"] = True
    elif hazard == "bundle-kind":
        bundle["kind"] = "peer-result"
    else:
        bundle["version"] = True
    rebind_bundle_fixture(case, bundle)
    with pytest.raises(AudiaGenticError):
        commit(case, proof)
    assert case.store.get(case.identity).state == "effect-intent"
    assert not case.store.outputs.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "identity",
        "kind",
        "version",
        "outcome",
        "extra",
        "text",
        "duplicate",
        "noncanonical",
        "native-plaintext",
    ],
)
def test_parser_checks_exact_hash_schema_and_correlation(tmp_path, monkeypatch, mutation):
    case = make_case(tmp_path / "case")
    receipt = commit(case, mint_proof(monkeypatch, case))
    raw, expected = case.store.output(case.identity).encode(), case.identity
    if mutation == "hash":
        digest = "0" * 64
    elif mutation == "identity":
        expected, digest = replace(expected, request_id="foreign-request"), sha(raw)
    elif mutation == "native-plaintext":
        raw, digest = b"plaintext", sha(b"plaintext")
    elif mutation == "duplicate":
        raw = raw.replace(b'"version":1', b'"version":1,"version":1')
        digest = sha(raw)
    else:
        value = json.loads(raw)
        if mutation == "kind":
            value["kind"] = "native-accepted"
        elif mutation == "version":
            value["version"] = True
        elif mutation == "outcome":
            value["outcome"]["status"] = "failed"
        elif mutation == "extra":
            value["unbound-proof"] = True
        elif mutation == "text":
            value["output"]["text"] = {"not": "text"}
        raw = (
            json.dumps(value, indent=2).encode()
            if mutation == "noncanonical"
            else canonical_json(value)
        )
        digest = sha(raw)
    with pytest.raises(AudiaGenticError):
        parse_worker_terminal_output(raw, expected_identity=expected, expected_sha256=digest)
    assert receipt.state == "terminal"


def test_output_before_failed_commit_is_not_terminal_evidence(tmp_path, monkeypatch):
    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case)
    original = case.store._append

    def fail(db, identity, state, output_digest=None):
        original(db, identity, state, output_digest)
        raise sqlite3.OperationalError("commit failed")

    monkeypatch.setattr(case.store, "_append", fail)
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        commit(case, proof)
    assert case.store.get(case.identity).state == "effect-intent"
    assert case.store.artifact_kind(case.identity) is None
    assert len(list(case.store.outputs.iterdir())) == 1
    monkeypatch.setattr(case.store, "_append", original)
    assert commit(case, proof).state == "terminal"


_TERMINAL_CHILD = r"""
import json,sys,time,runpy
from pathlib import Path
from pytest import MonkeyPatch
settings=json.loads(sys.stdin.readline())
test=runpy.run_path(settings['test-file'])
root=Path(settings['root'])
case=test['make_case'](root)
def pause():
    (root/'worker-terminal-ready').write_text('ready')
    while True: time.sleep(1)
with MonkeyPatch.context() as monkeypatch:
    proof=test['mint_proof'](monkeypatch,case)
    if settings['stage']=='before-commit':
        original=case.store._append
        def held(db,identity,state,output_digest=None):
            result=original(db,identity,state,output_digest)
            if state=='terminal': pause()
            return result
        case.store._append=held
    test['commit'](case,proof)
    pause()
"""


@pytest.mark.parametrize(
    "stage,expected", [("before-commit", "effect-intent"), ("after-commit", "terminal")]
)
def test_hard_kill_reopen_never_infers_native_acceptance(tmp_path, stage, expected):
    root = tmp_path / "case"
    package_root = Path(sys.modules[NodeReceiptStore.__module__].__file__).parents[5]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    child = subprocess.Popen(
        [sys.executable, "-c", _TERMINAL_CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        child.stdin.write(
            json.dumps(
                {"root": str(root), "test-file": str(Path(__file__).resolve()), "stage": stage}
            )
            + "\n"
        )
        child.stdin.flush()
        deadline = time.monotonic() + 10
        while (
            not (root / "worker-terminal-ready").exists()
            and child.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        if not (root / "worker-terminal-ready").exists():
            child.kill()
            _, error = child.communicate(timeout=5)
            pytest.fail("Worker terminal child missed persistence barrier: " + error)
        child.kill()
        child.communicate(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    store = NodeReceiptStore(
        node_id="node", node_epoch="boot", gateway_owner_epoch="gateway", root=root / "receipts"
    )
    with sqlite3.connect(store.path) as db:
        identity = CommandIdentity.from_mapping(
            json.loads(db.execute("SELECT identity FROM commands").fetchone()[0])
        )
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    receipt = store.get(identity)
    assert receipt.state == expected
    assert store.native_reference(identity) is None and store.authorization_id(identity) == "grant"
    assert [r.state for r in store.receipts_after()] == (
        ["prepared", "effect-intent", "terminal"]
        if expected == "terminal"
        else ["prepared", "effect-intent"]
    )
    if expected == "terminal":
        assert store.worker_terminal_output(identity).text == "Verified answer\r\n  λ\n"
    else:
        assert store.artifact_kind(identity) is None
        raw = next(store.outputs.iterdir()).read_bytes()
        with pytest.raises(AudiaGenticError):
            store.terminal_from_worker_result(identity, preparation=None, proof=json.loads(raw))
        assert store.get(identity).state == "effect-intent"


def test_json_looking_native_plaintext_is_not_worker_artifact_even_when_codec_valid(
    tmp_path, monkeypatch
):
    from audiagentic.components.agents.gateway.node.terminal_output import (
        build_worker_terminal_output,
    )

    case = make_case(tmp_path / "case")
    proof = mint_proof(monkeypatch, case)
    envelope = build_worker_terminal_output(
        case.identity,
        preparation=case.preparation,
        proof=proof,
        stored_payload=canonical_json(case.payload),
    )
    # A native provider may return precisely JSON-looking text. Mode comes from
    # the durable transition, never by sniffing these bytes or their kind field.
    case.store.native_accepted(case.identity, native_ref="real-native-ref")
    receipt = case.store.terminal(case.identity, text=envelope.to_bytes().decode())
    assert receipt.output_sha256 == envelope.digest
    assert case.store.artifact_kind(case.identity) == "native-plaintext"
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        case.store.worker_terminal_output(case.identity)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        commit(case, proof)
    assert case.store.output(case.identity) == envelope.to_bytes().decode()


