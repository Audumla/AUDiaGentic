"""Sparse canonical node milestones cannot change work outcomes on trace faults."""
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.agents_paths import gateway_timeline_path
from audiagentic.components.agents.gateway import observability as journal
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node import observability as module
from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
from audiagentic.components.agents.gateway.node.diagnostics import sanitize_node_error
from audiagentic.components.agents.gateway.node.observability import (
    emit_node_stage,
    node_observation_failure_count,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import iter_ndjson

from .test_gateway_node_admission_contract import node_record
from .test_gateway_node_dispatch_store import apply, authorize, bind, identity, receipt


@pytest.fixture(autouse=True)
def isolated_counter(monkeypatch):
    monkeypatch.setattr(module, "_failures", 0)


@pytest.fixture
def canonical(tmp_path):
    record = node_record()
    store.write_record(tmp_path, record)
    record = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="owner", expected_revision=0)
    record = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="owner", worker_id="worker",
                                       expected_revision=record["revision"])
    record = authorize(tmp_path, bind(tmp_path, record))
    return tmp_path, record


def observed(root, record):
    return journal.read_observation_page(root, record["request-id"])["items"][-1]["facts"]["diagnostic-facts"]


def test_actual_journals_preserve_milestone_and_separate_current_and_command_epochs(canonical):
    root, original = canonical
    current = store.takeover_nonterminal_owner(root, original["request-id"], expected_owner_epoch="owner",
                                               new_owner_epoch="new-owner")
    connection = NodeConnectionIdentity("node", "new-boot", "new-owner", 2)
    emit_node_stage(root, current, "reconciliation-started", connection=connection)
    facts = observed(root, current)
    assert facts["node-stage"] == facts["stage"] == "reconciliation-started"
    assert facts["gateway-owner-epoch"] == "new-owner" and facts["command-epoch"] == "owner"
    assert facts["connection-generation"] == 2 and facts["grant-revision"] == 1
    assert facts["node"]["current-epoch"] == {"id": "new-boot"}
    assert facts["node"]["command-epoch"] == {"id": original["node-dispatch"]["identity"]["node-epoch"]}
    assert facts["node"]["id"] == "node" and facts["command"]["id"] == identity(original).command_id
    assert facts["command"]["artifact-sha256"] == original["node-dispatch"]["identity"]["payload-sha256"]
    assert facts["side-effect-state"] == "may-have-started"
    assert "elapsed-ms" not in facts and "timing-event" not in facts
    timeline = list(iter_ndjson(gateway_timeline_path(root, current["request-id"])))
    assert timeline[-1]["event"] == "node.reconciliation-started"
    assert timeline[-1]["attributes"] == facts
    assert store.read_record(root, current["request-id"]) == current
    assert node_observation_failure_count() == 0


def test_error_retains_safe_failure_control_stage_and_separate_milestone(canonical):
    root, record = canonical
    source = AudiaGenticError("IO-AGND-001", "agents-node", "PRIVATE prompt /private/path",
                             {"stage": "retain-prepared", "reason-code": "prepared-evidence-unavailable",
                              "phase": "pre-submit", "payload": "PRIVATE"})
    error = sanitize_node_error(source)
    emit_node_stage(root, record, "failed", error=error)
    facts = observed(root, record)
    assert facts["node-stage"] == "failed" and facts["stage"] == "retain-prepared"
    assert facts["failure-code"] == "IO-AGND-001" and facts["reason-code"] == "prepared-evidence-unavailable"
    assert facts["phase"] == "pre-submit"
    assert "PRIVATE" not in json.dumps(facts)


@pytest.mark.parametrize("stage,label", [("prepare-requested", "runner-invocation"),
                                         ("command-sent", "runner-invocation"),
                                         ("effect-authorized", "effect-authorization"),
                                         ("effect-denied", "effect-authorization")])
def test_elapsed_is_monotonic_operation_local_and_intent_is_not_native_acceptance(canonical, monkeypatch, stage, label):
    root, record = canonical
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 20_000_000)
    emit_node_stage(root, record, stage, started_ns=5_000_000)
    facts = observed(root, record)
    assert facts["elapsed-ms"] == 15 and facts["timing-event"] == label
    assert facts["side-effect-state"] == "may-have-started"
    assert "receipt-stage" not in facts


def test_null_bind_and_valid_terminal_receipt_determine_side_effect_without_hints(canonical):
    root, record = canonical
    unbound = node_record()
    store.write_record(root, unbound)
    unbound["metadata"] = {"side-effect-state": "submission-proven"}
    emit_node_stage(root, unbound, "admission-validated")
    assert observed(root, unbound)["side-effect-state"] == "not-started"
    terminal = apply(root, record, receipt(identity(record), 4, "terminal", "a" * 64))
    emit_node_stage(root, terminal, "reconciliation-deferred")
    facts = observed(root, terminal)
    assert facts["side-effect-state"] == "terminal-evidence-seen"
    assert facts["artifact-sha256"] == "a" * 64
    assert facts["receipt-stage"] == "terminal" and facts["receipt-sequence"] == 4
    assert "artifact-kind" not in facts and "ack-sequence" not in facts


def test_private_record_content_is_not_forwarded_to_either_sink(canonical, monkeypatch):
    root, record = canonical
    private = deepcopy(record)
    private.update({"prompt-body": "PRIVATE-PROMPT", "output": "PRIVATE-OUTPUT",
                    "native-ref": "PRIVATE-NATIVE", "socket": object(), "exception": ValueError("PRIVATE-ERROR")})
    private["metadata"] = {"path": "/PRIVATE-PATH", "token": "PRIVATE-TOKEN"}
    timeline, observation = Mock(), Mock()
    monkeypatch.setattr(store, "record_gateway_timeline", timeline)
    monkeypatch.setattr(journal, "append_observation", observation)
    emit_node_stage(root, private, "command-sent")
    assert timeline.call_count == observation.call_count == 1
    assert "PRIVATE" not in json.dumps(timeline.call_args.kwargs)
    assert "PRIVATE" not in json.dumps(observation.call_args.kwargs)
    assert observation.call_args.kwargs["event_kind"] == "node-stage-observed"
    assert observation.call_args.kwargs["source"] == "node-runtime"
    assert observation.call_args.kwargs["force_flush"] is True


@pytest.mark.parametrize("change", [
    {"request-id": "../PRIVATE"}, {"dispatch-owner-epoch": "/PRIVATE"}, {"worker-id": "/PRIVATE"},
    {"attempt-epoch": True}, {"node-admission": None},
])
def test_invalid_identity_skips_both_sinks_and_counts_once(canonical, monkeypatch, change):
    root, record = canonical
    timeline, observation, warning = Mock(), Mock(), Mock()
    monkeypatch.setattr(store, "record_gateway_timeline", timeline)
    monkeypatch.setattr(journal, "append_observation", observation)
    monkeypatch.setattr(module.logger, "warning", warning)
    assert emit_node_stage(root, {**record, **change}, "failed") is None
    assert node_observation_failure_count() == 1
    timeline.assert_not_called()
    observation.assert_not_called()
    warning.assert_called_once_with("Node observation unavailable; canonical work unchanged")


@pytest.mark.parametrize("bad", [
    {"node_id": "node"}, NodeConnectionIdentity("node", "/PRIVATE", "owner", 1),
    NodeConnectionIdentity("node", "boot", "other-owner", 1), NodeConnectionIdentity("node", "boot", "owner", True),
])
def test_current_connection_requires_valid_typed_canonical_scope(canonical, bad, monkeypatch):
    root, record = canonical
    sink = Mock()
    monkeypatch.setattr(journal, "append_observation", sink)
    emit_node_stage(root, record, "connection-qualified", connection=bad)
    sink.assert_not_called()
    assert node_observation_failure_count() == 1


@pytest.mark.parametrize("mutation", ["identity", "stage", "sequence", "hash"])
def test_invalid_bound_receipt_evidence_does_not_emit_authoritative_looking_fields(canonical, mutation, monkeypatch):
    root, record = canonical
    terminal = apply(root, record, receipt(identity(record), 4, "terminal", "a" * 64))
    wrong = deepcopy(terminal)
    dispatch = wrong["node-dispatch"]
    if mutation == "identity":
        dispatch["identity"]["request-id"] = "other-request"
    elif mutation == "stage":
        dispatch["receipt-stage"] = "PRIVATE"
    elif mutation == "sequence":
        dispatch["receipt-sequence"] = True
    else:
        dispatch["receipt-sha256"] = "b" * 64
    sink = Mock()
    monkeypatch.setattr(journal, "append_observation", sink)
    emit_node_stage(root, wrong, "reconciliation-deferred")
    sink.assert_not_called()
    assert node_observation_failure_count() == 1


@pytest.mark.parametrize("sink", ["timeline", "observation"])
def test_each_sink_failure_is_isolated_and_partial_commit_is_not_retried(canonical, monkeypatch, sink):
    root, record = canonical
    original = store.read_record(root, record["request-id"])
    timeline, observation, warning = Mock(), Mock(), Mock()
    failing = timeline if sink == "timeline" else observation
    failing.side_effect = OSError("PRIVATE trace failure after append")
    monkeypatch.setattr(store, "record_gateway_timeline", timeline)
    monkeypatch.setattr(journal, "append_observation", observation)
    monkeypatch.setattr(module.logger, "warning", warning)
    emit_node_stage(root, record, "command-bound")
    assert timeline.call_count == observation.call_count == 1
    assert node_observation_failure_count() == 1
    assert store.read_record(root, record["request-id"]) == original
    assert "PRIVATE" not in str(warning.call_args)


def test_trace_and_logger_faults_never_escape_and_exact_counter_is_diagnostic(canonical, monkeypatch):
    root, record = canonical
    timeline = Mock(side_effect=OSError("PRIVATE timeline"))
    observation = Mock(side_effect=RuntimeError("PRIVATE observation"))
    warning = Mock(side_effect=RuntimeError("PRIVATE logger"))
    monkeypatch.setattr(store, "record_gateway_timeline", timeline)
    monkeypatch.setattr(journal, "append_observation", observation)
    monkeypatch.setattr(module.logger, "warning", warning)
    emit_node_stage(root, record, "command-bound")
    assert node_observation_failure_count() == 2
    emit_node_stage(root, record, "command-bound")
    assert node_observation_failure_count() == 4
    assert timeline.call_count == observation.call_count == 2 and warning.call_count == 1
    assert store.read_record(root, record["request-id"]) == record


@pytest.mark.parametrize("control", [KeyboardInterrupt, SystemExit])
def test_control_flow_is_not_swallowed_as_diagnostic_fault(canonical, monkeypatch, control):
    root, record = canonical
    monkeypatch.setattr(store, "record_gateway_timeline", Mock(side_effect=control()))
    observation = Mock()
    monkeypatch.setattr(journal, "append_observation", observation)
    with pytest.raises(control):
        emit_node_stage(root, record, "command-bound")
    observation.assert_not_called()
    assert node_observation_failure_count() == 0


def test_first_failure_is_counted_before_warning_without_double_counting_logger(canonical, monkeypatch):
    root, record = canonical
    counts = []

    def warning(*args, **kwargs):
        counts.append(node_observation_failure_count())
        raise RuntimeError("logging failed")

    monkeypatch.setattr(module.logger, "warning", warning)
    monkeypatch.setattr(store, "record_gateway_timeline", Mock(side_effect=OSError()))
    monkeypatch.setattr(journal, "append_observation", Mock())
    emit_node_stage(root, record, "command-bound")
    assert counts == [1] and node_observation_failure_count() == 1


def test_scalar_counter_is_locked_and_warning_is_attempted_once(canonical, monkeypatch):
    root, record = canonical
    warning = Mock()
    monkeypatch.setattr(module.logger, "warning", warning)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: emit_node_stage(root, record, "PRIVATE-invalid-stage"), range(40)))
    assert node_observation_failure_count() == 40
    warning.assert_called_once()


@pytest.mark.parametrize("start", [True, -1, 30_000_000])
def test_invalid_elapsed_clock_input_skips_diagnostic_emission(canonical, monkeypatch, start):
    root, record = canonical
    monkeypatch.setattr(module.time, "monotonic_ns", lambda: 20_000_000)
    sink = Mock()
    monkeypatch.setattr(journal, "append_observation", sink)
    emit_node_stage(root, record, "command-sent", started_ns=start)
    sink.assert_not_called()
    assert node_observation_failure_count() == 1
