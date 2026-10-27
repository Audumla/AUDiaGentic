"""Canonical node admission identity and historical ordinary idempotency."""
import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.admission_contract import (
    NodeAdmissionDescriptor,
    NodeAdmissionPolicy,
    SourceWorkspaceIdentity,
)
from audiagentic.components.agents.gateway.node.preparation import PromptSemanticIdentity
from audiagentic.components.agents.gateway.store._admission import _intent_digest
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import validate_with_schema
from audiagentic.foundation.io import atomic_write_json


def descriptor():
    semantic = PromptSemanticIdentity("a" * 64, "b" * 64, "prompt", "profile", 1, "c" * 64, "d" * 64)
    return NodeAdmissionDescriptor(1, "server", semantic, NodeAdmissionPolicy("profile", "generation", "digest", 8, 2, 1), "e" * 64,
                                   SourceWorkspaceIdentity(1, "node", "workspace", "read-write", "f" * 64))


def node_record(**changes):
    kwargs = dict(execution_profile_id="profile", prompt_body="hello", node_admission=descriptor().to_mapping(),
                  node_placement={"node-id": "node", "workspace-id": "workspace", "principal-id": "alice",
                                  "server-project-id": "project", "grant-revision": 1})
    kwargs.update(changes)
    return store.build_record(**kwargs)


def test_ordinary_intent_digest_historical_golden_bytes():
    ordinary = {"execution-profile-id": "profile", "mode": "async"}
    golden = (b'{"context-fingerprint":null,"continuation-session-id":null,"execution-profile-id":"profile",'
              b'"mode":"async","prompt-digest":null,"provider-transport-kind":null,"session-idle-timeout-seconds":null,'
              b'"session-keep-alive":null,"session-max-lifetime-seconds":null,"timeout-seconds":null}')
    assert _intent_digest(ordinary) == hashlib.sha256(golden).hexdigest()
    assert _intent_digest({**ordinary, "node-placement": None, "node-admission": None}) == _intent_digest(ordinary)


def test_descriptor_roundtrip_and_caller_mutation_isolated():
    original = json.loads(json.dumps(descriptor().to_mapping()))
    record = node_record(node_admission=original)
    original["policy"]["pending-capacity"] = 999
    assert record["node-admission"]["policy"]["pending-capacity"] == 8
    with pytest.raises(TypeError):
        record["node-admission"]["semantic"]["prompt-id"] = "replacement"
    assert NodeAdmissionDescriptor.from_mapping(record["node-admission"]) == descriptor()


@pytest.mark.parametrize("field,value", [
    ("source_node_id", "other-node"), ("workspace_id", "other-workspace"),
    ("access_mode", "read-only"), ("binding_sha256", "a" * 64),
])
def test_source_workspace_is_execution_intent_not_audit_provenance(tmp_path, field, value):
    first = node_record()
    store.admit_record(tmp_path, first, idempotency_key="same-key")
    changed = replace(descriptor(), source_workspace=replace(descriptor().source_workspace, **{field: value}))
    with pytest.raises(AudiaGenticError) as caught:
        store.admit_record(tmp_path, node_record(node_admission=changed.to_mapping()), idempotency_key="same-key")
    assert caught.value.code == "CON-AGW-081"


def test_historical_descriptor_without_source_is_readable_but_never_fresh_admission(tmp_path):
    old = replace(descriptor(), source_workspace=None).to_mapping()
    assert "source-workspace" not in old
    assert NodeAdmissionDescriptor.from_mapping(old).to_mapping() == old
    record = node_record(node_admission=old)
    store.write_record(tmp_path, record)
    loaded = store.read_record(tmp_path, record["request-id"])
    assert loaded["node-admission"] == old
    # Ordinary updates cannot silently rewrite historical descriptor identity.
    store.transition_record(tmp_path, record["request-id"], "running")
    with pytest.raises(AudiaGenticError, match="caller workspace"):
        store.admit_record(tmp_path, node_record(node_admission=old), idempotency_key="fresh")


@pytest.mark.parametrize("field,value", [
    ("version", True), ("source_node_id", "../node"), ("workspace_id", ""),
    ("access_mode", "write"), ("access_mode", None), ("binding_sha256", "bad"),
])
def test_source_workspace_contract_rejects_malformed_identity(field, value):
    with pytest.raises(AudiaGenticError):
        replace(descriptor().source_workspace, **{field: value})


def test_source_locator_and_claims_cannot_be_added_to_public_identity():
    mapping = json.loads(json.dumps(descriptor().to_mapping()))
    for key in ("root", "hostname", "authenticated"):
        changed = deepcopy(mapping)
        changed["source-workspace"][key] = "not-authority"
        with pytest.raises(AudiaGenticError):
            NodeAdmissionDescriptor.from_mapping(changed)
    mapping["source-workspace"] = None
    with pytest.raises(AudiaGenticError):
        NodeAdmissionDescriptor.from_mapping(mapping)


@pytest.mark.parametrize("target,field,value", [
    ("placement", "node-id", "other"), ("placement", "workspace-id", "other"),
    ("placement", "principal-id", "other"), ("placement", "server-project-id", "other"),
    ("placement", "grant-revision", 2), ("descriptor", "server-id", "other"),
    ("semantic", "composition-fingerprint", "f" * 64),
    ("semantic", "prompt-definition-fingerprint", "f" * 64),
    ("semantic", "expanded-prompt-sha256", "f" * 64), ("semantic", "prompt-id", "other"),
    ("policy", "generation", "other"), ("policy", "config-digest", "other"),
    ("policy", "pending-capacity", 9), ("policy", "global-capacity", None),
    ("policy", "project-capacity", 2),
])
def test_explicit_key_conflicts_on_target_semantic_or_policy(tmp_path, target, field, value):
    store.admit_record(tmp_path, node_record(), idempotency_key="same-key")
    candidate = node_record()
    admission = json.loads(json.dumps(candidate["node-admission"]))
    mapping = candidate["node-placement"] if target == "placement" else (
        admission if target == "descriptor" else admission[target])
    mapping[field] = value
    candidate["node-admission"] = admission
    with pytest.raises(AudiaGenticError) as caught:
        store.admit_record(tmp_path, candidate, idempotency_key="same-key")
    assert caught.value.code == "CON-AGW-081"


@pytest.mark.parametrize("node_first", [True, False])
def test_explicit_key_is_shared_between_ordinary_and_node(tmp_path, node_first):
    ordinary = store.build_record(execution_profile_id="profile", prompt_body="hello")
    node = node_record()
    first, second = (node, ordinary) if node_first else (ordinary, node)
    store.admit_record(tmp_path, first, idempotency_key="shared-key")
    with pytest.raises(AudiaGenticError) as caught:
        store.admit_record(tmp_path, second, idempotency_key="shared-key")
    assert caught.value.code == "CON-AGW-081"


def test_provenance_only_replay_returns_original_record(tmp_path):
    first, created = store.admit_record(tmp_path, node_record(), idempotency_key="key")
    assert created
    changed = node_record(node_admission=replace(descriptor(), snapshot_sha256="f" * 64).to_mapping(),
                          source="other-source", metadata={"subject": "other audit provenance"})
    replay, created = store.admit_record(tmp_path, changed, idempotency_key="key")
    assert not created and replay == store.read_record(tmp_path, first["request-id"])
    assert replay["node-admission"]["snapshot-sha256"] == "e" * 64


def test_lowlevel_historical_node_readable_but_not_fresh_admission(tmp_path):
    record = node_record(node_admission=None)
    store.write_record(tmp_path, record)
    assert store.read_record(tmp_path, record["request-id"])["node-admission"] is None
    with pytest.raises(AudiaGenticError):
        store.admit_record(tmp_path, record, idempotency_key="new-admission")


@pytest.mark.parametrize("version", ["v8", "v9", "v10"])
def test_modern_migration_preserves_all_facts_without_descriptor(tmp_path, version):
    legacy = node_record(node_admission=None)
    legacy.pop("node-admission")
    legacy["prompt-body"] = None
    legacy["contract-version"] = version
    legacy.update({"dispatch-owner-epoch": "owner", "worker-id": "worker", "attempt-epoch": 3,
                   "recovery": {"reason": "owner-loss", "outcome": "in-place", "attempt": 2},
                   "recovery-required": True, "replay-required": True, "replay-reason": "owner-loss",
                   "provider-metadata": {"provider-session-id": "retained"}})
    atomic_write_json(gateway_request_path(tmp_path, legacy["request-id"]), legacy)
    migrated = store.read_record(tmp_path, legacy["request-id"])
    assert migrated == {**legacy, "contract-version": "v11", "node-admission": None}
    assert store.read_record(tmp_path, legacy["request-id"]) == migrated


def test_descriptor_cannot_be_added_or_changed_after_creation(tmp_path):
    record = node_record()
    store.write_record(tmp_path, record)
    changed = dict(record, **{"node-admission": replace(descriptor(), snapshot_sha256="f" * 64).to_mapping()})
    with pytest.raises(AudiaGenticError):
        store.write_record(tmp_path, changed)
    with pytest.raises(AudiaGenticError):
        store.transition_record(tmp_path, record["request-id"], "running", updates={"node-admission": None})
    historical = node_record(node_admission=None)
    store.write_record(tmp_path, historical)
    with pytest.raises(AudiaGenticError):
        store.write_record(tmp_path, dict(historical, **{"node-admission": descriptor().to_mapping()}))


@pytest.mark.parametrize("section,key,value", [
    ("descriptor", "version", True), ("descriptor", "snapshot-sha256", "bad"),
    ("descriptor", "private-prompt", "SECRET"), ("semantic", "catalog-digest", "SECRET"),
    ("policy", "pending-capacity", True), ("policy", "pending-capacity", None),
    ("policy", "pending-capacity", 2**31), ("policy", "global-capacity", 0),
    ("policy", "project-capacity", "1"), ("policy", "generation", "x" * 201),
])
def test_strict_bounded_descriptor_validation(section, key, value):
    mapping = json.loads(json.dumps(descriptor().to_mapping()))
    target = mapping if section == "descriptor" else mapping[section]
    target[key] = value
    with pytest.raises(AudiaGenticError) as caught:
        NodeAdmissionDescriptor.from_mapping(mapping)
    assert "SECRET" not in str(caught.value)


def test_admission_detaches_caller_fields_before_prewrite(tmp_path):
    candidate = node_record()
    original_placement = deepcopy(candidate["node-placement"])

    def mutate_caller():
        candidate["node-placement"]["node-id"] = "other"

    admitted, _ = store.admit_record(tmp_path, candidate, idempotency_key="key", before_write=mutate_caller)
    assert admitted["node-placement"] == original_placement


def test_v10_bound_receipt_migration_retains_attestation_and_all_fences(tmp_path):
    from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
    from audiagentic.components.agents.gateway.node.receipts import Receipt

    from .test_gateway_node_drain import bound_request

    bound = bound_request(tmp_path)
    identity = CommandIdentity.from_mapping(bound["node-dispatch"]["identity"])
    bound = store.apply_owned_node_receipt(
        tmp_path, bound["request-id"], receipt=Receipt(identity, "native-accepted", 3).public_payload(),
        owner_epoch="owner", worker_id="worker", attempt_epoch=1, expected_revision=bound["revision"],
    )
    legacy = deepcopy(bound)
    legacy.pop("node-admission")
    legacy.update({"contract-version": "v10", "session-id": "retained-session",
                   "recovery-required": True, "replay-required": True, "replay-reason": "owner-loss",
                   "recovery": {"reason": "owner-loss", "outcome": "in-place", "attempt": 2}})
    atomic_write_json(gateway_request_path(tmp_path, bound["request-id"]), legacy)
    migrated = store.read_record(tmp_path, bound["request-id"])
    assert migrated == {**legacy, "contract-version": "v11", "node-admission": None}
    assert migrated["node-dispatch"]["attestation-sha256"] == bound["node-dispatch"]["attestation-sha256"]
    assert migrated["node-dispatch"]["receipt-sha256"] == bound["node-dispatch"]["receipt-sha256"]


def test_v11_schema_requires_nullable_descriptor_and_rejects_private_extra():
    record = node_record()
    assert not validate_with_schema("agent-execution-record", record)
    missing = dict(record)
    missing.pop("node-admission")
    assert validate_with_schema("agent-execution-record", missing)
    wrong = deepcopy(dict(record))
    wrong["node-admission"] = json.loads(json.dumps(record["node-admission"]))
    wrong["node-admission"]["policy"]["working-root"] = "/private"
    assert validate_with_schema("agent-execution-record", wrong)


def test_node_policy_profile_must_match_semantic_and_record():
    with pytest.raises(AudiaGenticError):
        replace(descriptor(), policy=replace(descriptor().policy, profile_id="other"))
    with pytest.raises(AudiaGenticError):
        node_record(execution_profile_id="other")


@pytest.mark.parametrize("section", ["semantic", "policy"])
def test_missing_descriptor_fields_are_not_defaulted(section):
    mapping = json.loads(json.dumps(descriptor().to_mapping()))
    del mapping[section][next(iter(mapping[section]))]
    with pytest.raises(AudiaGenticError):
        NodeAdmissionDescriptor.from_mapping(mapping)
