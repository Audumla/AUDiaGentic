"""Revoked-node historical eligibility survives real custody crash windows."""
import hashlib
from dataclasses import replace

import pytest
import yaml

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node import checkpoints as checkpoint_module
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
from audiagentic.components.agents.gateway.node.drain import NodeDrainEligibility
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    build_final_command_payload,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_node_checkpoints import _make_request
from .test_gateway_node_contracts import authorization
from .test_gateway_node_drain import bound_request
from .test_gateway_node_drain import configured as configured


@pytest.fixture
def custody(configured, tmp_path):
    original, service, _ = configured
    raw = yaml.safe_load(original.config_path.read_text(encoding="utf-8"))
    raw["principals"]["principal"] = raw["principals"].pop("alice")
    raw["nodes"]["node"]["principals"] = ["principal"]
    original.config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    config = load_shared_server_config(original.config_path)
    created = service.create(protocol_version="test", owner_epoch="owner")
    service.transition("running", expected_revision=created.revision, expected_epoch="owner")
    local = NodeReceiptStore(
        node_id="node", node_epoch="node-epoch", gateway_owner_epoch="owner", root=tmp_path / "node-local",
    )
    central = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    return config, service, NodeDrainEligibility(config, service), local, central


def target(root, identity):
    current = store.read_record(root, identity.request_id)
    return CanonicalReceiptTarget(root, current["dispatch-owner-epoch"], current["worker-id"],
                                  current["attempt-epoch"], current["revision"])


def accept(custody, receipt, *, central=None, resolver=None):
    config, _, _, local, original = custody
    return (central or original).accept(
        receipt, log_incarnation_id=local.log_incarnation_id, expected_epoch="owner",
        resolve_target=resolver or (lambda identity: target(config.projects["project"], identity)),
    )


def acknowledge(local, ack):
    frame = Frame(1, "reconcile-result", "ack", "node", "node-epoch", "owner", 1,
                  ack.payload(connection_generation=1))
    return local.acknowledge(
        frame, expected_server_id="server",
        current_connection=NodeConnectionIdentity("node", "node-epoch", "owner", 1),
    )


def terminal_outbox(root, local):
    identity, payload = _make_request(root, "effect")
    local.prepare(identity, canonical_json(payload))
    request, reply = authorization(identity)
    scope = dict(node_id=identity.node_id, node_epoch=identity.node_epoch,
                 gateway_owner_epoch=identity.gateway_owner_epoch)
    request = replace(request, **scope)
    reply = replace(reply, **scope, payload={**reply.payload, "authorization-id": "auth-effect"})
    assert local.effect_intent(identity, request, reply, connection_generation=1)
    local.native_accepted(identity, native_ref="private-native-custody-fixture")
    terminal = local.terminal(identity, text="retained terminal custody output")
    return identity, terminal


def prepared_payload(record):
    """Rebuild the deterministic bound_request fixture's protected payload."""
    identity = CommandIdentity.from_mapping(record["node-dispatch"]["identity"])
    binding = PreparationBinding(
        identity.command_id, identity.request_id, identity.node_id, identity.node_epoch,
        identity.gateway_owner_epoch, identity.connection_generation, identity.workspace_id,
        identity.grant_revision, identity.binding_generation, "challenge", "preparation",
    )
    semantic = PromptSemanticIdentity("a" * 64, "b" * 64, "prompt", "profile", 1,
                                      hashlib.sha256(b"expanded").hexdigest(), hashlib.sha256(b"hello").hexdigest())
    preparation = prepare_node_command(
        binding=binding, semantic=semantic, raw_prompt="hello", rendered_prompt="rendered",
        manifest_id="manifest", context_fingerprint="c" * 64, runtime_digest="d" * 64,
        provider_manifest=b"private", worker_id="worker", attempt_epoch=1,
        provider_id="provider", model_id="model", model_alias=None,
    )
    payload = canonical_json(build_final_command_payload(preparation, "hello"))
    assert hashlib.sha256(payload).hexdigest() == identity.payload_sha256
    return identity, payload


def test_terminal_applied_before_cursor_failure_remains_drain_eligible_and_replays(custody, monkeypatch):
    config, service, drain, local, central = custody
    root = config.projects["project"]
    identity, terminal = terminal_outbox(root, local)
    for receipt in local.receipts_after():
        if receipt.sequence < terminal.sequence:
            previous_ack = accept(custody, receipt)
            acknowledge(local, previous_ack)
    cursor_before = central.path.read_bytes()
    assert previous_ack.sequence == terminal.sequence - 1
    original_write = checkpoint_module.atomic_write_json

    def fail_cursor(path, value):
        assert path == central.path
        raise OSError("cursor commit interrupted")

    monkeypatch.setattr(checkpoint_module, "atomic_write_json", fail_cursor)
    with pytest.raises(OSError, match="cursor commit interrupted"):
        accept(custody, terminal)
    applied = store.read_record(root, identity.request_id)
    assert applied["node-dispatch"]["receipt-stage"] == "terminal"
    assert applied["node-dispatch"]["receipt-sha256"] == terminal.digest
    assert central.path.read_bytes() == cursor_before
    assert local.ack_checkpoint().through_sequence == terminal.sequence - 1
    assert drain.eligible(config, config.nodes[0])
    assert local.receipts_after(local.ack_checkpoint().through_sequence) == (terminal,)
    with pytest.raises(AudiaGenticError):
        accept(custody, terminal)  # failed stream owner stays poisoned

    monkeypatch.setattr(checkpoint_module, "atomic_write_json", original_write)
    restarted = NodeReceiptCheckpoints(service, server_id="server", node_id="node")
    ack = accept(custody, terminal, central=restarted)
    assert ack.sequence == terminal.sequence and ack.receipt_sha256 == terminal.digest
    assert store.read_record(root, identity.request_id) == applied  # exact canonical replay is no write
    checkpoint = acknowledge(local, ack)
    assert checkpoint.through_sequence == terminal.sequence
    assert local.receipts_after(checkpoint.through_sequence) == ()
    assert local.output(identity) == "retained terminal custody output"


def test_cursor_committed_but_ack_lost_returns_duplicate_cumulative_ack(custody):
    config, service, drain, local, _ = custody
    identity, terminal = terminal_outbox(config.projects["project"], local)
    for receipt in local.receipts_after():
        ack = accept(custody, receipt)
        if receipt.sequence < terminal.sequence:
            acknowledge(local, ack)
    # Drop terminal ACK: cursor commit is real, no local acknowledgement occurs.
    before = store.read_record(config.projects["project"], identity.request_id)
    assert local.ack_checkpoint().through_sequence == terminal.sequence - 1
    assert drain.eligible(config, config.nodes[0])
    restarted = NodeReceiptCheckpoints(service, server_id="server", node_id="node")

    def forbidden(_identity):
        pytest.fail("committed duplicate must return cumulative ACK without reapplying")

    duplicate = accept(custody, terminal, central=restarted, resolver=forbidden)
    assert duplicate == ack
    assert store.read_record(config.projects["project"], identity.request_id) == before
    assert acknowledge(local, duplicate).through_sequence == terminal.sequence
    # There is no ACK-of-ACK requirement and no outbox pruning inferred here.
    assert drain.eligible(config, config.nodes[0])
    assert local.receipts_after()[-1] == terminal


def test_prepared_head_is_retained_and_global_replay_precedes_authorized_tail(custody):
    config, _, drain, local, _ = custody
    root = config.projects["project"]
    record = bound_request(root, principal="principal", authorized=False)
    head_identity, payload = prepared_payload(record)
    local.advance_epoch(node_epoch="boot", gateway_owner_epoch="owner")
    local = NodeReceiptStore(node_id="node", node_epoch="boot", gateway_owner_epoch="owner", root=local.root)
    head = local.prepare(head_identity, payload)
    assert not drain.eligible(config, config.nodes[0])
    assert local.get(head_identity).state == "prepared"
    assert local.receipts_after() == (head,)
    local.advance_epoch(node_epoch="node-epoch", gateway_owner_epoch="owner")
    local = NodeReceiptStore(node_id="node", node_epoch="node-epoch", gateway_owner_epoch="owner", root=local.root)
    _, terminal = terminal_outbox(root, local)
    pending = local.receipts_after()
    assert pending[0] == head and pending[-1] == terminal
    assert drain.eligible(config, config.nodes[0])
    # Drain replays the whole node log in C+1 order, not only eligible commands.
    for receipt in pending:
        ack = accept(custody, receipt)
        assert ack.sequence == receipt.sequence
        acknowledge(local, ack)
    retained = store.read_record(root, record["request-id"])
    assert retained["node-dispatch"]["authorization-state"] == "not-authorized"
    assert retained["node-dispatch"]["receipt-stage"] == "prepared"
    assert local.get(head_identity).state == "prepared"
    assert local.receipts_after()[0] == head
    assert local.ack_checkpoint().through_sequence == terminal.sequence


@pytest.mark.parametrize("change", [
    {"node": "foreign"}, {"workspace": "foreign"}, {"project": "foreign"}, {"principal": "foreign"},
])
def test_wrong_exact_sealed_scope_cannot_open_drain_despite_retained_outbox(custody, change):
    config, _, drain, local, _ = custody
    root = config.projects["project"]
    args = {"principal": "principal", **change}
    record = bound_request(root, **args)
    identity, payload = prepared_payload(record)
    # Use an actual outbox for the command's node identity, including foreign-node evidence.
    outbox = NodeReceiptStore(
        node_id=identity.node_id, node_epoch="boot", gateway_owner_epoch="owner",
        root=local.root.parent / "scope-outbox",
    )
    receipt = outbox.prepare(identity, payload)
    assert not drain.eligible(config, config.nodes[0])
    assert store.read_record(root, record["request-id"]) == record
    assert outbox.receipts_after() == (receipt,)
