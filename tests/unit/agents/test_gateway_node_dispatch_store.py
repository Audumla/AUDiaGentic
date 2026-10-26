"""SH38 real request-store CAS, migration and node receipt checkpoints."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest

from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json


@pytest.fixture
def running(tmp_path):
    record = store.build_record(
        execution_profile_id="profile", prompt_body="hello", session_id="ses_retained",
        node_placement=placement(),
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="owner", expected_revision=0)
    started = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="owner", worker_id="worker",
        expected_revision=claimed["revision"],
    )
    return tmp_path, started


def identity(record, **changes):
    command = CommandIdentity(
        command_id="cmd-1", request_id=record["request-id"], node_id="node",
        node_epoch="node-epoch", gateway_owner_epoch="owner", connection_generation=1,
        workspace_id="workspace", grant_revision=1, binding_generation=1,
        payload_sha256="a" * 64, execution_profile_id="profile",
    )
    return replace(command, **changes)


def fences(record, **changes):
    return {
        "owner_epoch": record["dispatch-owner-epoch"], "worker_id": record["worker-id"],
        "attempt_epoch": record["attempt-epoch"], "expected_revision": record["revision"],
        **changes,
    }


def bind(root, record, command=None, **changes):
    return store.bind_owned_node_dispatch(
        root, record["request-id"], identity=command or identity(record), **fences(record, **changes),
    )


def authorize(root, record, command=None, **changes):
    command = command or identity(record)
    return store.authorize_owned_node_effect(
        root, record["request-id"], identity=command, authorization_id="auth-1",
        current_node_epoch=command.node_epoch,
        current_connection_generation=command.connection_generation, **fences(record, **changes),
    )


def receipt(command, sequence, stage, output=None):
    return {"identity": command.to_mapping(), "state": stage,
            "receipt-sequence": sequence, "output-sha256": output}


def apply(root, record, value, **changes):
    return store.apply_owned_node_receipt(
        root, record["request-id"], receipt=value, **fences(record, **changes),
    )


def test_new_record_v9_defaults_and_strict_schema(running):
    root, record = running
    assert record["contract-version"] == "v9"
    assert record["node-dispatch"] is None
    missing = dict(record)
    missing.pop("node-dispatch")
    with pytest.raises(AudiaGenticError):
        store.write_record(root, missing)
    bound = bind(root, record)
    malformed = deepcopy(bound)
    malformed["node-dispatch"]["native-ref"] = "private"
    with pytest.raises(AudiaGenticError):
        store.write_record(root, malformed)
    malformed = deepcopy(bound)
    malformed["node-dispatch"]["identity"]["secret"] = "private"
    with pytest.raises(AudiaGenticError):
        store.write_record(root, malformed)


def test_v8_migration_preserves_entire_modern_record(running):
    root, record = running
    legacy = deepcopy(record)
    legacy["contract-version"] = "v8"
    legacy.pop("node-dispatch")
    legacy.pop("node-placement")
    legacy.update({
        "recovery": {"reason": "owner-loss", "outcome": "in-place", "attempt": 2},
        "recovery-required": True, "replay-required": True, "replay-reason": "owner-loss",
        "resumed-from-request-id": "req_previous", "replayed-by-request-id": "req_next",
        "provider-metadata": {"chat-url": "https://chatgpt.com/c/retained"},
    })
    atomic_write_json(gateway_request_path(root, record["request-id"]), legacy)
    migrated = store.read_record(root, record["request-id"])
    assert migrated == {**legacy, "contract-version": "v9", "node-dispatch": None, "node-placement": None}
    assert store.read_record(root, record["request-id"]) == migrated


def test_historic_v7_stays_v7_and_does_not_invent_session(running):
    root, record = running
    legacy = deepcopy(record)
    legacy["contract-version"] = "v7"
    legacy.pop("node-dispatch")
    legacy.pop("node-placement")
    legacy["session-id"] = None
    legacy["continuation-session-id"] = None
    legacy["provider-transport-kind"] = "worker"
    atomic_write_json(gateway_request_path(root, record["request-id"]), legacy)
    migrated = store.read_record(root, record["request-id"])
    assert migrated["contract-version"] == "v7"
    assert migrated["session-id"] is None
    assert migrated["dispatch-owner-epoch"] is None  # historic behavior retained


@pytest.mark.parametrize("operation", ["bind", "authorize", "receipt"])
@pytest.mark.parametrize("field,value,code", [
    ("owner_epoch", "other", "CON-AGW-083"), ("worker_id", "other", "CON-AGW-072"),
    ("attempt_epoch", 22, "CON-AGW-073"), ("expected_revision", 0, "CON-AGW-071"),
])
def test_all_mutators_check_owned_fences_before_writing(running, operation, field, value, code):
    root, record = running
    if operation != "bind":
        record = bind(root, record)
    before = gateway_request_path(root, record["request-id"]).read_bytes()
    with pytest.raises(AudiaGenticError) as error:
        if operation == "bind":
            bind(root, record, **{field: value})
        elif operation == "authorize":
            authorize(root, record, **{field: value})
        else:
            apply(root, record, receipt(identity(record), 1, "prepared"), **{field: value})
    assert error.value.code == code
    assert gateway_request_path(root, record["request-id"]).read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("command_id", "other"), ("request_id", "req_other"), ("node_id", "other"),
    ("workspace_id", "other"), ("node_epoch", "other"), ("gateway_owner_epoch", "other"),
    ("connection_generation", 2), ("binding_generation", 2), ("grant_revision", 2),
    ("payload_sha256", "b" * 64), ("execution_profile_id", "other"),
])
def test_changed_identity_never_rebinds_or_erases_authorization(running, field, value):
    root, record = running
    record = authorize(root, bind(root, record))
    changed = identity(record, **{field: value})
    for action in (
        lambda: bind(root, record, changed),
        lambda: authorize(root, record, changed),
        lambda: apply(root, record, receipt(changed, 1, "prepared")),
    ):
        with pytest.raises(AudiaGenticError) as error:
            action()
        assert error.value.code == "CON-AGND-001"
    assert store.read_record(root, record["request-id"]) == record


def test_bind_and_authorize_exact_replay_are_no_write(running):
    root, record = running
    record = bind(root, record)
    assert bind(root, record) == record
    record = authorize(root, record)
    assert authorize(root, record) == record
    assert bind(root, record) == record
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store.authorize_owned_node_effect(
            root, record["request-id"], identity=identity(record), authorization_id="different",
            current_node_epoch="node-epoch", current_connection_generation=1, **fences(record),
        )


@pytest.mark.parametrize("epoch,generation", [("old-epoch", 1), ("node-epoch", 2)])
def test_stale_live_connection_cannot_authorize(running, epoch, generation):
    root, record = running
    record = bind(root, record)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store.authorize_owned_node_effect(
            root, record["request-id"], identity=identity(record), authorization_id="auth-1",
            current_node_epoch=epoch, current_connection_generation=generation, **fences(record),
        )
    assert store.read_record(root, record["request-id"]) == record


def test_receipts_monotonic_replay_and_node_wide_sequence_gaps(running):
    root, record = running
    command = identity(record)
    record = bind(root, record)
    record = apply(root, record, receipt(command, 3, "prepared"))
    assert record["node-dispatch"]["authorization-state"] == "not-authorized"
    record = authorize(root, record)
    for sequence, stage, state in [
        (7, "effect-intent", "uncertain"), (12, "native-accepted", "effect-observed"),
        (19, "terminal", "terminal"),
    ]:
        value = receipt(command, sequence, stage, "c" * 64 if stage == "terminal" else None)
        record = apply(root, record, value)
        assert record["node-dispatch"]["authorization-state"] == state
        assert apply(root, record, value) == record
        if stage != "terminal":
            with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
                authorize(root, record)
    assert record["state"] == "running"  # evidence checkpoint does not terminalize the request
    assert record["node-dispatch"]["authorization-id"] == "auth-1"
    assert len(record["node-dispatch"]["receipt-sha256"]) == 64
    for value in [
        receipt(command, 18, "native-accepted"), receipt(command, 20, "prepared"),
        receipt(command, 19, "terminal", "d" * 64),
        receipt(command, 21, "terminal", "c" * 64),
    ]:
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            apply(root, record, value)


def test_effect_receipt_requires_durable_authorization(running):
    root, record = running
    record = bind(root, record)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        apply(root, record, receipt(identity(record), 1, "effect-intent"))


def test_old_epoch_receipts_are_original_command_evidence_only(running):
    root, record = running
    command = identity(record)
    record = authorize(root, bind(root, record))
    # Emulate an already validated owner takeover; old command remains immutable.
    record["dispatch-owner-epoch"] = "new-owner"
    record["revision"] += 1
    store.write_record(root, record)
    record = apply(root, record, receipt(command, 10, "native-accepted"))
    assert record["node-dispatch"]["identity"] == command.to_mapping()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        authorize(root, record, command)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        bind(root, record, replace(command, node_epoch="new-node", gateway_owner_epoch="new-owner"))


def test_parallel_bind_same_revision_has_one_cas_winner(running):
    root, record = running
    def compete():
        try:
            bind(root, record)
            return "won"
        except AudiaGenticError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: compete(), range(2)))
    assert sorted(results) == ["CON-AGW-071", "won"]


@pytest.mark.parametrize("flag", ["cancel-requested", "recovery-required"])
def test_cancel_or_recovery_does_not_grant_fresh_authorization(running, flag):
    root, record = running
    record = bind(root, record)
    record[flag] = True
    store.write_record(root, record)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        authorize(root, record)


@pytest.mark.parametrize("sequence,stage,output", [
    (True, "prepared", None), (0, "prepared", None), (-1, "prepared", None),
    (2**63, "prepared", None), (1, "unknown", None),
    (1, "terminal", None), (1, "terminal", "bad"),
    (1, "prepared", "c" * 64),
])
def test_invalid_receipt_never_mutates_checkpoint(running, sequence, stage, output):
    root, record = running
    record = authorize(root, bind(root, record))
    before = gateway_request_path(root, record["request-id"]).read_bytes()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        apply(root, record, receipt(identity(record), sequence, stage, output))
    assert gateway_request_path(root, record["request-id"]).read_bytes() == before


def test_receipt_does_not_reauthorize_on_new_connection(running):
    root, record = running
    command = identity(record)
    record = authorize(root, bind(root, record))
    record = apply(root, record, receipt(command, 100, "effect-intent"))
    assert record["node-dispatch"]["authorization-state"] == "uncertain"
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store.authorize_owned_node_effect(
            root, record["request-id"], identity=command, authorization_id="auth-1",
            current_node_epoch="node-epoch", current_connection_generation=2, **fences(record),
        )
    assert store.read_record(root, record["request-id"]) == record


def placement():
    return {"node-id": "node", "workspace-id": "workspace", "principal-id": "principal",
            "server-project-id": "server-project", "grant-revision": 1}


def test_placement_is_admission_only_and_not_an_effect_grant(tmp_path):
    selected = placement()
    record = store.build_record(execution_profile_id="profile", prompt_body="hello", node_placement=selected)
    assert record["node-placement"] == selected
    assert record["node-dispatch"] is None
    assert "node-placement" not in record["metadata"]
    selected["node-id"] = "caller-mutated"
    assert record["node-placement"]["node-id"] == "node"
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="owner", expected_revision=0)
    running_record = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="owner", worker_id="worker",
        expected_revision=claimed["revision"],
    )
    assert running_record["node-placement"] == placement()
    assert running_record["node-dispatch"] is None
    bound = bind(tmp_path, running_record)
    assert bound["node-placement"] == placement()
    assert bound["node-dispatch"]["authorization-state"] == "not-authorized"


@pytest.mark.parametrize("updates", [
    {"node-placement": None}, {"node-placement": {"node-id": "different"}},
    {"node_placement": None},
])
def test_generic_transition_cannot_change_placement(running, updates):
    root, record = running
    record["node-placement"] = placement()
    store.write_record(root, record)
    with pytest.raises(AudiaGenticError, match="VAL-AGW-098"):
        store.transition_record(root, record["request-id"], "failed", updates=updates)
    assert store.read_record(root, record["request-id"])["node-placement"] == placement()


@pytest.mark.parametrize("key,value", [
    ("node-id", "different"), ("workspace-id", "different"), ("grant-revision", 2),
])
def test_command_must_match_admitted_placement(running, key, value):
    root, record = running
    selected = placement()
    selected[key] = value
    record["node-placement"] = selected
    store.write_record(root, record)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        bind(root, record)
    assert store.read_record(root, record["request-id"])["node-dispatch"] is None


@pytest.mark.parametrize("invalid", [
    {}, {"node-id": "node"}, {**placement(), "token": "forbidden"},
    {**placement(), "grant-revision": True}, {**placement(), "grant-revision": 0},
    {**placement(), "principal-id": ""}, {**placement(), "server-project-id": "../client-path"},
])
def test_placement_schema_rejects_incomplete_or_extra_authority(invalid):
    with pytest.raises(AudiaGenticError):
        store.build_record(execution_profile_id="profile", prompt_body="hello", node_placement=invalid)


def test_missing_v9_placement_defaults_without_clearing_ownership(running):
    root, record = running
    old = deepcopy(record)
    old.pop("node-placement")
    atomic_write_json(gateway_request_path(root, record["request-id"]), old)
    migrated = store.read_record(root, record["request-id"])
    assert migrated == {**old, "node-placement": None}


@pytest.mark.parametrize("operation", ["bind", "authorize"])
@pytest.mark.parametrize("invalid_placement", [
    None, {}, {"node-id": "node"},
    {**placement(), "principal-id": ""},
    {**placement(), "server-project-id": "../unsealed"},
    {**placement(), "grant-revision": True},
    {**placement(), "extra-authority": "forbidden"},
])
def test_node_mutators_require_complete_sealed_placement_before_writing(
    running, operation, invalid_placement
):
    root, record = running
    if operation == "authorize":
        record = bind(root, record)
    record["node-placement"] = invalid_placement
    # Model both schema-valid ordinary admission (null) and corrupted sealed
    # facts. The canonical locked reader must reject malformed tuples.
    path = gateway_request_path(root, record["request-id"])
    atomic_write_json(path, record)
    before = path.read_bytes()
    files_before = {entry.relative_to(root) for entry in root.rglob("*") if entry.is_file()}
    with pytest.raises(AudiaGenticError) as error:
        if operation == "bind":
            bind(root, record)
        else:
            authorize(root, record)
    assert error.value.code == ("CON-AGND-001" if invalid_placement is None else "VAL-AGW-005")
    assert path.read_bytes() == before
    assert {entry.relative_to(root) for entry in root.rglob("*") if entry.is_file()} == files_before


@pytest.mark.parametrize("field,value", [
    ("node-id", "other-node"), ("workspace-id", "other-workspace"), ("grant-revision", 2),
])
def test_authorize_rechecks_exact_admission_placement_without_writing(running, field, value):
    root, record = running
    record = bind(root, record)
    record["node-placement"][field] = value
    # Corruption/replacement cannot turn existing command ownership into a
    # fresh grant; principal/project policy still belongs to the outer owner.
    store.write_record(root, record)
    path = gateway_request_path(root, record["request-id"])
    before = path.read_bytes()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        authorize(root, record)
    assert path.read_bytes() == before


def test_bind_and_authorize_preserve_sealed_principal_project_facts(running):
    root, record = running
    admitted = deepcopy(record["node-placement"])
    bound = bind(root, record)
    authorized = authorize(root, bound)
    assert admitted["principal-id"] == "principal"
    assert admitted["server-project-id"] == "server-project"
    assert bound["node-placement"] == authorized["node-placement"] == admitted
    assert authorized["node-dispatch"]["authorization-state"] == "authorized"
