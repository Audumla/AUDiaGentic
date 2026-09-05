from __future__ import annotations

from datetime import datetime

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.api import (
    get_execution_diagnostics,
    recover_execution_request,
)
from audiagentic.components.agents.gateway.diagnostics import (
    activity_monitoring_snapshot,
    classify_error,
    merge_diagnostics,
)
from audiagentic.components.agents.gateway.queue.dispatch import diagnose_activity_lease


def test_ambiguous_gpt_auto_error_is_not_provider_failure() -> None:
    result = classify_error(
        {
            "code": "EXT-GPTAUTO-004",
            "details": {
                "submission-ambiguous": True,
                "failure-reason": "prompt-text-digest-not-found",
                "dom-signals": ["completion-control", "more-actions-menu"],
            },
        }
    )
    assert result["classification"] == "ambiguous-side-effect"
    assert result["side-effect-state"] == "may-have-started"
    assert result["recovery"]["disposition"] == "operator-adopt-available"
    assert result["provider-signals"] == ["completion-control", "more-actions-menu"]


def test_response_policy_timeout_is_reconciliation_timeout() -> None:
    result = classify_error(
        {
            "code": "EXT-GPTAUTO-002",
            "details": {"failure-reason": "response-policy-timeout"},
        }
    )
    assert result["classification"] == "timeout"
    assert result["side-effect-state"] == "may-have-started"
    assert result["recovery"]["disposition"] == "reconcile-required"


def test_attempted_without_submission_proof_is_ambiguous() -> None:
    result = classify_error(
        {
            "code": "EXT-GPTAUTO-003",
            "details": {"submission-attempted": True, "submission-proven": False},
        }
    )
    assert result["classification"] == "ambiguous-side-effect"
    assert result["side-effect-state"] == "may-have-started"
    assert result["recovery"]["disposition"] == "reconcile-required"


def test_gateway_restart_interruption_is_explicitly_classified() -> None:
    result = classify_error(
        {"code": "CON-AGW-084", "kind": "agents", "message": "owning service generation is gone"}
    )
    assert result["classification"] == "gateway-restart"
    assert result["failure-code"] == "CON-AGW-084"
    assert result["reason-code"] == "service-restart"
    assert result["side-effect-state"] == "may-have-started"
    assert result["recovery"]["disposition"] == "reconcile-required"


def test_diagnostics_side_effect_state_never_regresses() -> None:
    previous = classify_error(
        {
            "code": "EXT-GPTAUTO-004",
            "details": {"submission-ambiguous": True},
        }
    )
    candidate = classify_error({"code": "EXT-GPTAUTO-003", "details": {}})
    merged = merge_diagnostics(previous, candidate)
    assert merged["classification"] == "ambiguous-side-effect"
    assert merged["side-effect-state"] == "may-have-started"
    assert merged["resolution-state"] == "unresolved"


def test_diagnostics_can_resolve_after_stronger_side_effect_evidence() -> None:
    previous = classify_error(
        {"code": "EXT-GPTAUTO-004", "details": {"submission-ambiguous": True}}
    )
    candidate = {
        "version": 1,
        "classification": "timeout",
        "certainty": "strong",
        "phase": "terminal-observation",
        "side-effect-state": "submission-proven",
        "resolution-state": "resolved",
        "recovery": {"disposition": "none", "allowed-actions": []},
    }
    merged = merge_diagnostics(previous, candidate)
    assert merged["side-effect-state"] == "submission-proven"
    assert merged["classification"] == "timeout"
    assert merged["resolution-state"] == "resolved"


def test_lease_expiry_persists_bounded_diagnostics_and_evidence(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="inspect")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service", expected_revision=0)
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service",
        worker_id="worker",
        expected_revision=claimed["revision"],
    )
    expired = dict(running)
    expired["activity-lease-expires-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)

    diagnosed = diagnose_activity_lease(tmp_path, expired)

    assert diagnosed["diagnostics"]["classification"] == "stale-progress"
    assert diagnosed["diagnostics"]["failure-code"] is None
    assert diagnosed["diagnostics"]["phase"] == "reconciliation"
    assert diagnosed["diagnostic-evidence"][-1]["kind"] == "activity-lease-expired"
    projected = get_execution_diagnostics(tmp_path, record["request-id"], limit=1)
    assert len(projected["evidence"]) == 1
    assert "prompt" not in str(projected).lower()


def test_activity_monitoring_reports_first_activity_latency(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="inspect")
    record["state"] = "running"
    record["started-at"] = "2026-09-05T00:00:00Z"
    record["activity-sequence"] = 2
    record["activity"] = {
        **record["activity"],
        "provider": {
            **record["activity"]["provider"],
            "first-at": "2026-09-05T00:00:04.250000Z",
            "last-at": "2026-09-05T00:00:06Z",
        },
    }

    snapshot = activity_monitoring_snapshot(
        record, now=datetime.fromisoformat("2026-09-05T00:00:10+00:00")
    )

    assert snapshot["watcher-state"] == "observing"
    assert snapshot["activity-sequence"] == 2
    assert snapshot["first-activity-latency-seconds"] == 4.25
    store.write_record(tmp_path, record)
    public = get_execution_diagnostics(tmp_path, record["request-id"], limit=1)
    assert public["monitoring"]["watcher-state"] == "observing"
    assert public["monitoring"]["first-activity-latency-seconds"] == 4.25


def test_activity_monitoring_reports_zero_activity_wait_without_failure() -> None:
    record = {
        "state": "running",
        "started-at": "2026-09-05T00:00:00Z",
        "activity-sequence": 0,
        "activity": {"provider": {"first-at": None, "last-at": None}},
    }

    snapshot = activity_monitoring_snapshot(
        record, now=datetime.fromisoformat("2026-09-05T00:00:42+00:00")
    )

    assert snapshot["watcher-state"] == "awaiting-first-activity"
    assert snapshot["activity-sequence"] == 0
    assert snapshot["no-activity-seconds"] == 42.0


def test_lease_expiry_then_valid_activity_resolves_stale_observation(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="inspect")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service", expected_revision=0)
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service",
        worker_id="worker",
        expected_revision=claimed["revision"],
    )
    expired = dict(running)
    expired["activity-lease-expires-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)
    diagnosed = diagnose_activity_lease(tmp_path, expired)
    resumed = store.record_owned_activity(
        tmp_path,
        record["request-id"],
        owner_epoch="service",
        worker_id="worker",
        attempt_epoch=running["attempt-epoch"],
        kind="provider",
        source="provider-progress",
        source_instance="worker",
        source_sequence=1,
        phase="response-progress",
        activity_lease_seconds=300,
    )
    assert diagnosed["state"] == "running"
    assert resumed["state"] == "running"
    assert resumed["diagnostics"]["classification"] == "stale-progress"
    assert resumed["diagnostics"]["resolution-state"] == "resolved"
    assert resumed["diagnostics"]["reason-code"] == "activity-resumed"


def test_initial_zero_activity_gets_non_terminal_reconciliation_diagnostic(tmp_path) -> None:
    record = store.build_record(
        execution_profile_id="gpt-auto",
        prompt_body="inspect",
        watchdog_policy={
            "policy-id": "test",
            "policy-digest": "test",
            "activity-lease-seconds": 300.0,
            "absolute-safety-ceiling-seconds": 0.0,
            "diagnostic-grace-seconds": 30.0,
            "initial-activity-grace-seconds": 1.0,
            "available": True,
        },
    )
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service", expected_revision=0)
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service",
        worker_id="worker",
        expected_revision=claimed["revision"],
    )
    expired = dict(running)
    expired["started-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)

    diagnosed = diagnose_activity_lease(tmp_path, expired)

    assert diagnosed["state"] == "running"
    assert diagnosed["activity-sequence"] == 0
    assert diagnosed["watchdog-reason"] == "initial-activity-observation-expired"
    assert diagnosed["diagnostics"]["reason-code"] == "initial-activity-observation-expired"
    assert diagnosed["diagnostic-evidence"][-1]["kind"] == "initial-activity-timeout"


def test_cancellation_provenance_is_durable(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="cancel")
    store.write_record(tmp_path, record)
    cancelled = store.cancel_queued_or_mark_requested(
        tmp_path,
        record["request-id"],
        source="api",
        actor_type="client",
        actor_id="caller-1",
        reason="user-request",
    )
    assert cancelled["cancel-provenance"] == {
        "source": "api",
        "actor-type": "client",
        "actor-id": "caller-1",
        "reason": "user-request",
        "requested-at": cancelled["cancel-provenance"]["requested-at"],
    }


def test_recovery_requires_proven_absence_for_clear_not_submitted(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="recover")
    store.write_record(tmp_path, record)
    store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"error": {"code": "EXT-GPTAUTO-003", "details": {"submission-ambiguous": True}}},
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        recover_execution_request(tmp_path, record["request-id"], action="clear-not-submitted")
    except AudiaGenticError as exc:
        assert exc.code == "CON-AGW-146"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("ambiguous side effect was incorrectly cleared")


def test_cancellation_preserves_unresolved_side_effect_diagnostics(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="cancel")
    store.write_record(tmp_path, record)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"error": {"code": "EXT-GPTAUTO-003", "details": {"submission-ambiguous": True}}},
    )
    cancelled = store.cancel_queued_or_mark_requested(
        tmp_path,
        record["request-id"],
        source="operator",
        actor_type="operator",
        reason="diagnostic-recovery-abandon",
        expected_revision=running["revision"],
    )
    assert cancelled["diagnostics"]["classification"] == "ambiguous-side-effect"
    assert cancelled["diagnostics"]["side-effect-state"] == "may-have-started"
    assert cancelled["diagnostics"]["resolution-state"] == "unresolved"


def test_mark_cancel_requested_preserves_unresolved_side_effect_diagnostics(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="cancel")
    store.write_record(tmp_path, record)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"error": {"code": "EXT-GPTAUTO-003", "details": {"submission-ambiguous": True}}},
    )
    cancelled = store.mark_cancel_requested(
        tmp_path,
        record["request-id"],
        source="watchdog",
        actor_type="system",
        reason="lease-expired",
    )
    assert cancelled["revision"] == running["revision"] + 1
    assert cancelled["diagnostics"]["classification"] == "ambiguous-side-effect"
    assert cancelled["diagnostics"]["resolution-state"] == "unresolved"


def test_abandon_recovery_is_single_cas_operation(tmp_path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="abandon")
    store.write_record(tmp_path, record)
    running = store.transition_record(
        tmp_path,
        record["request-id"],
        "running",
        updates={"error": {"code": "EXT-GPTAUTO-003", "details": {"submission-ambiguous": True}}},
    )
    result = recover_execution_request(
        tmp_path,
        record["request-id"],
        action="abandon",
        expected_revision=running["revision"],
    )
    assert result["disposition"] == "accepted"
    assert result["revision"] == running["revision"] + 1
    assert result["diagnostics"]["resolution-state"] == "abandon-requested"
