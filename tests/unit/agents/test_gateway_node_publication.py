"""Original node evidence publishes text once without reviving lifecycle winners."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.agents_paths import gateway_final_response_path
from audiagentic.components.agents.gateway import output, store
from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.preparation import PreparationAttestation
from audiagentic.components.agents.gateway.node.publication import publish_owned_node_terminal
from audiagentic.components.agents.gateway.node.receipts import Receipt
from audiagentic.components.agents.gateway.node.terminal_output import WorkerTerminalOutput
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore

from .test_gateway_node_checkpoints import _make_request


@pytest.fixture
def published_case(tmp_path, request):
    from audiagentic.components.agents.gateway.node.prepared_evidence import persist_prepared_once

    root = tmp_path / "project"
    root.mkdir()
    service = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=tmp_path / "service")
    created = service.create(protocol_version="test", owner_epoch="owner")
    service.transition("running", expected_revision=created.revision, expected_epoch="owner")
    identity, payload = _make_request(root, "publication")
    accepted = PreparationAttestation.from_mapping(payload["attestation"])
    persist_prepared_once(root, identity, attestation=accepted, payload=payload)
    record = store.read_record(root, identity.request_id)
    record["dispatch-service-root"] = str(service.root)
    store.write_record(root, record)
    artifact = WorkerTerminalOutput(
        identity, accepted.digest, accepted.provider_manifest_sha256, "a" * 64,
        accepted.provider_id, accepted.model_id, accepted.worker_id, accepted.attempt_epoch,
        "Exact text\r\nλ\n", getattr(request, "param", "text/markdown; charset=utf-8"),
    )
    receipt = Receipt(identity, "terminal", 1, artifact.digest)
    record = store.apply_owned_node_receipt(
        root, identity.request_id, receipt=receipt.public_payload(),
        owner_epoch="owner", worker_id="worker", attempt_epoch=1,
        expected_revision=record["revision"],
    )
    return SimpleNamespace(root=root, service=service, identity=identity, payload=payload,
                           accepted=accepted, artifact=artifact, receipt=receipt, record=record)


def publish(case, **changes):
    params = {
        "identity": case.identity, "terminal_receipt": case.receipt,
        "raw_artifact": case.artifact.to_bytes(),
        "connection": NodeConnectionIdentity("node", "new-boot", "owner", 2),
        "service_store": case.service, "current_owner_epoch": "owner",
    }
    params.update(changes)
    return publish_owned_node_terminal(case.root, **params)


def test_exact_text_not_private_envelope_and_completed_replay_is_no_write(published_case):
    case = published_case
    completed = publish(case)
    assert completed["state"] == "completed"
    assert completed["provider-id"] == case.accepted.provider_id
    assert output.read_final_response(case.root, case.identity.request_id,
                                      completed["response-artifact"]) == case.artifact.text
    assert gateway_final_response_path(case.root, case.identity.request_id).read_bytes() == case.artifact.text.encode()
    assert publish(case) == completed
    assert store.read_record(case.root, case.identity.request_id, include_output=False) == completed


def test_artifact_write_before_terminal_crash_recovers_same_bytes(published_case, monkeypatch):
    case = published_case
    original = store.transition_owned_terminal
    def crash(*args, **kwargs):
        raise RuntimeError("terminal CAS interrupted")
    monkeypatch.setattr(store, "transition_owned_terminal", crash)
    with pytest.raises(RuntimeError, match="CAS interrupted"):
        publish(case)
    assert store.read_record(case.root, case.identity.request_id)["state"] == "running"
    assert gateway_final_response_path(case.root, case.identity.request_id).read_bytes() == case.artifact.text.encode()
    monkeypatch.setattr(store, "transition_owned_terminal", original)
    assert publish(case)["state"] == "completed"


@pytest.mark.parametrize("state", ["cancelled", "failed", "interrupted"])
def test_terminal_lifecycle_winner_is_not_resurrected(published_case, state):
    case = published_case
    winner = store.transition_record(case.root, case.identity.request_id, state)
    with pytest.raises(AudiaGenticError):
        publish(case)
    assert store.read_record(case.root, case.identity.request_id) == winner
    assert not gateway_final_response_path(case.root, case.identity.request_id).exists()


@pytest.mark.parametrize("field,value", [
    ("attestation_sha256", "b" * 64), ("private_bundle_sha256", "b" * 64),
    ("worker_id", "other"), ("attempt_epoch", 2),
    ("provider_id", "other"), ("model_id", "other"),
])
def test_artifact_with_matching_receipt_hash_still_requires_original_preparation(published_case, field, value):
    case = published_case
    changed = replace(case.artifact, **{field: value})
    receipt = replace(case.receipt, sequence=2, output_sha256=changed.digest)
    # A terminal command cannot change its receipt. Model a corrupt canonical
    # record to ensure publication checks original preparation independently.
    current = store.read_record(case.root, case.identity.request_id)
    current["node-dispatch"].update({"receipt-sequence": 2, "output-sha256": changed.digest,
                                     "receipt-sha256": receipt.digest})
    store.write_record(case.root, current)
    with pytest.raises(AudiaGenticError):
        publish(case, terminal_receipt=receipt, raw_artifact=changed.to_bytes())
    assert not gateway_final_response_path(case.root, case.identity.request_id).exists()


def test_wrong_current_channel_and_owner_are_rejected(published_case):
    case = published_case
    for connection in (NodeConnectionIdentity("other", "boot", "owner", 1),
                       NodeConnectionIdentity("node", "boot", "old-owner", 1)):
        with pytest.raises(AudiaGenticError):
            publish(case, connection=connection)
    with pytest.raises(AudiaGenticError):
        publish(case, current_owner_epoch="stale",
                connection=NodeConnectionIdentity("node", "boot", "stale", 1))
    assert not gateway_final_response_path(case.root, case.identity.request_id).exists()


def test_changed_existing_response_is_never_overwritten(published_case):
    case = published_case
    path = gateway_final_response_path(case.root, case.identity.request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"different publication")
    with pytest.raises(AudiaGenticError):
        publish(case)
    assert path.read_bytes() == b"different publication"


def test_stale_revision_and_corrupt_receipt_do_not_write_artifacts(published_case):
    case = published_case
    with pytest.raises(AudiaGenticError):
        publish(case, expected_revision=case.record["revision"] - 1)
    with pytest.raises(AudiaGenticError):
        publish(case, terminal_receipt=replace(case.receipt, sequence=99))
    assert not gateway_final_response_path(case.root, case.identity.request_id).exists()


def test_session_finalization_runs_after_publication_locks(published_case, monkeypatch):
    from audiagentic.components.agents.gateway.node import publication

    case = published_case
    seen = []
    def finalized(root, record):
        from audiagentic.components.agents.gateway.store._shared import _request_lock

        # Re-enter the canonical mutation lock: a nested call would timeout.
        with _request_lock(root, record["request-id"]):
            assert store.read_record(root, record["request-id"])["state"] == "completed"
        seen.append(record["state"])
    monkeypatch.setattr(publication, "_finalize_worker_session_if_terminal", finalized)
    assert publish(case)["state"] == "completed"
    assert seen == ["completed"]


@pytest.mark.parametrize("published_case", ["text/plain", "text/markdown"], indirect=True)
def test_supported_worker_media_normalizes_to_existing_response_contract(published_case):
    case = published_case
    completed = publish(case)
    assert completed["response-artifact"]["media-type"] == case.artifact.media_type + "; charset=utf-8"
    assert publish(case) == completed


@pytest.mark.parametrize("iteration", range(3))
def test_cancel_and_publication_have_one_canonical_winner(published_case, iteration):
    case = published_case
    barrier = Barrier(2)
    def race(action):
        barrier.wait(timeout=5)
        try:
            if action == "cancel":
                return store.transition_record(case.root, case.identity.request_id, "cancelled")["state"]
            return publish(case)["state"]
        except AudiaGenticError:
            return "lost"
    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel, complete = list(pool.map(race, ("cancel", "publish")))
    winner = store.read_record(case.root, case.identity.request_id)
    assert sorted((cancel, complete)) in (["completed", "lost"], ["cancelled", "lost"])
    path = gateway_final_response_path(case.root, case.identity.request_id)
    assert path.exists() == (winner["state"] == "completed")
    if path.exists():
        assert path.read_bytes() == case.artifact.text.encode()
