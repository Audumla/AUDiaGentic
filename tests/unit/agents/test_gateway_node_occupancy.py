"""Canonical occupancy evidence, including outer terminals and restart scans."""
import pytest

from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.occupancy import NodeOccupancy, record_holds_node

from .test_gateway_node_dispatch_store import apply, authorize, bind, identity, placement, receipt


def running_record(root):
    record = store.build_record(execution_profile_id="profile", prompt_body="hello", node_placement=placement())
    store.write_record(root, record)
    record = store.claim_dispatch(root, record["request-id"], owner_epoch="owner", expected_revision=0)
    return store.start_owned_attempt(
        root, record["request-id"], owner_epoch="owner", worker_id="worker",
        expected_revision=record["revision"],
    )


@pytest.mark.parametrize("stage", [None, "prepared", "effect-intent", "native-accepted"])
def test_outer_terminal_and_lost_ack_do_not_release(tmp_path, stage):
    record = authorize(tmp_path, bind(tmp_path, running_record(tmp_path)))
    if stage:
        record = apply(tmp_path, record, receipt(identity(record), 1, stage))
    record = store.transition_record(tmp_path, record["request-id"], "failed")
    before = gateway_request_path(tmp_path, record["request-id"]).read_bytes()
    for _ in range(2):
        snapshot = NodeOccupancy((tmp_path,), server_id="server").snapshot()
        assert snapshot.occupied("server", "node")
        assert not snapshot.occupied("server", "other")
        assert not snapshot.occupied("other", "node")
        assert not snapshot.occupied("server", "node", exclude_request=(tmp_path, record["request-id"]))
    assert gateway_request_path(tmp_path, record["request-id"]).read_bytes() == before


def test_terminal_native_receipt_releases_even_after_outer_timeout(tmp_path):
    record = authorize(tmp_path, bind(tmp_path, running_record(tmp_path)))
    record = store.transition_record(tmp_path, record["request-id"], "failed")
    value = receipt(identity(record), 1, "terminal", "a" * 64)
    record = apply(tmp_path, record, value)
    before = gateway_request_path(tmp_path, record["request-id"]).read_bytes()
    assert apply(tmp_path, record, value) == record
    for _ in range(2):
        assert not NodeOccupancy((tmp_path,), server_id="server").snapshot().occupied("server", "node")
    assert gateway_request_path(tmp_path, record["request-id"]).read_bytes() == before


def test_null_command_never_holds_from_status_or_owner_metadata(tmp_path):
    record = store.build_record(execution_profile_id="profile", prompt_body="hello", node_placement=placement())
    store.write_record(tmp_path, record)
    projection = NodeOccupancy((tmp_path,), server_id="server")
    assert not projection.snapshot().occupied("server", "node")
    record = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="owner", expected_revision=0)
    assert not projection.snapshot().occupied("server", "node")
    record = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="owner", worker_id="worker",
        expected_revision=record["revision"],
    )
    assert not projection.snapshot().occupied("server", "node")
    store.transition_record(tmp_path, record["request-id"], "failed")
    assert not projection.snapshot().occupied("server", "node")


def test_unreadable_canonical_record_fails_closed_and_roots_are_owner_supplied(tmp_path):
    with pytest.raises(ValueError):
        NodeOccupancy((tmp_path,))
    foreign = tmp_path / "foreign"
    configured = tmp_path / "configured"
    record = running_record(foreign)
    projection = NodeOccupancy((configured,), server_id="server")
    assert not projection.snapshot().occupied("server", "node")
    projection = NodeOccupancy((foreign,), server_id="server")
    gateway_request_path(foreign, record["request-id"]).write_text("broken", encoding="utf-8")
    assert projection.snapshot().unproven
    assert projection.snapshot().occupied("server", "any-node")


def test_unknown_or_incomplete_terminal_evidence_never_releases():
    record = {"state": "failed", "node-dispatch": {"authorization-state": "unknown"}}
    assert record_holds_node(record)
    record["node-dispatch"] = {"authorization-state": "terminal", "receipt-stage": "terminal"}
    assert record_holds_node(record)


def test_terminal_digest_mismatch_retains_occupancy(tmp_path):
    record = authorize(tmp_path, bind(tmp_path, running_record(tmp_path)))
    record = apply(tmp_path, record, receipt(identity(record), 1, "terminal", "a" * 64))
    assert not record_holds_node(record)
    record["node-dispatch"]["receipt-sha256"] = "b" * 64
    store.write_record(tmp_path, record)
    assert NodeOccupancy((tmp_path,), server_id="server").snapshot().occupied("server", "node")
