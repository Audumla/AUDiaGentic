from __future__ import annotations

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.api import (
    get_execution_diagnostics,
    recover_execution_request,
)
from audiagentic.components.agents.gateway.diagnostics import classify_error
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

    assert diagnosed["diagnostics"]["classification"] == "timeout"
    assert diagnosed["diagnostics"]["phase"] == "reconciliation"
    assert diagnosed["diagnostic-evidence"][-1]["kind"] == "activity-lease-expired"
    projected = get_execution_diagnostics(tmp_path, record["request-id"], limit=1)
    assert len(projected["evidence"]) == 1
    assert "prompt" not in str(projected).lower()


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
