"""Bounded presubmit exhaustion must preserve complete negative send proof."""

from copy import deepcopy

import pytest

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.api import recover_execution_request
from audiagentic.components.agents.gateway.diagnostics import classify_error, merge_diagnostics
from audiagentic.components.agents.gateway.queue.queue import GatewayQueueManager
from audiagentic.components.agents.gateway.queue.recovery_control import RecoveryDeferred
from audiagentic.components.agents.gateway.store._records import _redact_error
from audiagentic.foundation.contracts.errors import AudiaGenticError


def root_error():
    return {
        "code": "EXT-GPTAUTO-004",
        "kind": "providers",
        "details": {
            "failure-stage": "readiness",
            "submission-state": "not_started",
            "submission-attempted": False,
            "submission-proven": False,
            "submission-ambiguous": False,
            "previous-turn-unresolved": False,
        },
    }


def wrapped():
    return {
        "code": "CON-AGW-084",
        "kind": "agents",
        "details": {
            "recovery-phase": "presubmit-retry",
            "side-effect-state": "not-started",
            "submission-proven": False,
            "root-recovery-error": root_error(),
        },
    }


@pytest.mark.parametrize("redact", [False, True])
@pytest.mark.parametrize("phase", ["presubmit-retry", "presubmit-reconcile"])
def test_wrapper_preserves_complete_root_proof(redact, phase):
    error = wrapped()
    error["details"]["recovery-phase"] = phase
    if redact:
        error = _redact_error(error)
    result = classify_error(error)
    direct = classify_error(root_error())
    for key in ("classification", "phase", "side-effect-state", "recovery"):
        assert result[key] == direct[key]
    assert result["failure-code"] == "CON-AGW-084"
    assert result["reason-code"] == "EXT-GPTAUTO-004"


@pytest.mark.parametrize("missing", list(root_error()["details"]))
def test_incomplete_nested_proof_stays_fenced(missing):
    error = wrapped()
    del error["details"]["root-recovery-error"]["details"][missing]
    assert classify_error(error)["side-effect-state"] == "may-have-started"


CONFLICTS = [
    ("submission-state", "submitted"),
    ("submission-state", "unknown"),
    ("submission-attempted", True),
    ("submission-proven", True),
    ("submission-ambiguous", True),
    ("previous-turn-unresolved", True),
    ("side-effect-attempted", True),
    ("send-intent-ever", True),
    ("send-button-clicked", True),
    ("enter-dispatched", True),
    ("turn-state", "submitted"),
    ("turn-state", "unknown"),
    ("turn-state", "side-effect-attempted"),
    ("turn-state", "submission-ambiguous"),
    ("side-effect-state", "may-have-started"),
    ("side-effect-state", "submission-proven"),
    ("submission-attempted", "false"),
    ("submission-proven", "false"),
    ("submission-ambiguous", "false"),
    ("previous-turn-unresolved", "false"),
]


@pytest.mark.parametrize("level", ["outer", "root"])
@pytest.mark.parametrize("key,value", CONFLICTS)
def test_conflicting_evidence_stays_fenced(level, key, value):
    error = wrapped()
    details = error["details"]
    if level == "root":
        details = details["root-recovery-error"]["details"]
    details[key] = value
    result = classify_error(error)
    assert result["side-effect-state"] != "not-started"
    assert "clear-not-submitted" not in result["recovery"]["allowed-actions"]


@pytest.mark.parametrize(
    "mutation",
    [
        "restart",
        "phase",
        "missing-phase",
        "missing-side",
        "root-code",
        "missing-root",
        "malformed-root",
        "fence",
    ],
)
def test_other_exhaustion_is_not_safe(mutation):
    error = wrapped()
    details = error["details"]
    if mutation == "restart":
        details.clear()
    elif mutation == "phase":
        details["recovery-phase"] = "followup-reconcile"
    elif mutation == "missing-phase":
        del details["recovery-phase"]
    elif mutation == "missing-side":
        del details["side-effect-state"]
    elif mutation == "root-code":
        details["root-recovery-error"]["code"] = "EXT-GPTAUTO-003"
    elif mutation == "missing-root":
        del details["root-recovery-error"]
    elif mutation == "malformed-root":
        details["root-recovery-error"]["details"] = []
    else:
        details["session-fence-state"] = "manual-reconcile-required"
    assert classify_error(error)["side-effect-state"] == "may-have-started"


@pytest.mark.parametrize(
    "state", ["may-have-started", "submission-proven", "terminal-evidence-seen"]
)
def test_explicit_and_previously_persisted_uncertainty_is_never_downgraded(state):
    assert classify_error(wrapped(), side_effect_state=state)["side-effect-state"] == state
    candidate = classify_error(wrapped())
    previous = classify_error(
        {"code": "EXT-GPTAUTO-004", "details": {"submission-ambiguous": True}}
    )
    previous["side-effect-state"] = state
    before = deepcopy(previous)
    merged = merge_diagnostics(previous, candidate)
    assert previous == before
    assert merged["side-effect-state"] == state
    assert merged["recovery"]["allowed-actions"] == ["reconcile", "abandon"]


@pytest.mark.no_parallel
@pytest.mark.parametrize("prior_uncertainty", [False, True])
def test_queue_exhaustion_and_clear_api_preserve_proof_and_prior_fences(
    tmp_path, prior_uncertainty
):
    manager = GatewayQueueManager()
    record = store.build_record(execution_profile_id="unsent-exhaustion", prompt_body="x")
    if prior_uncertainty:
        record["diagnostics"] = classify_error(
            {"code": "EXT-GPTAUTO-004", "details": {"submission-ambiguous": True}}
        )
    store.write_record(tmp_path, record)
    attempts = []

    def runner(_root, _record, **kwargs):
        attempts.append(True)
        root = root_error()
        raise RecoveryDeferred(
            AudiaGenticError(
                code=root["code"],
                kind="providers",
                message="readiness failed",
                details=root["details"],
            ),
            phase="presubmit-retry",
            side_effect_state="not-started",
        )

    manager.enqueue(
        tmp_path,
        record,
        {
            "virtual-capacity": 1,
            "provider-session-recovery-initial-delay-seconds": 0.01,
            "provider-session-recovery-max-delay-seconds": 0.01,
            "provider-session-recovery-max-attempts": 2,
        },
        runner,
    )
    terminal = manager.wait(tmp_path, record["request-id"], timeout_seconds=3)
    assert len(attempts) == 2
    assert terminal["state"] == "interrupted"
    assert terminal["error"]["code"] == "CON-AGW-084"
    assert terminal["recovery"]["last-error-details"] == root_error()["details"]
    if prior_uncertainty:
        assert terminal["diagnostics"]["side-effect-state"] == "may-have-started"
        with pytest.raises(AudiaGenticError, match="CON-AGW-146"):
            recover_execution_request(tmp_path, record["request-id"], action="clear-not-submitted")
    else:
        assert terminal["diagnostics"]["side-effect-state"] == "not-started"
        result = recover_execution_request(
            tmp_path, record["request-id"], action="clear-not-submitted"
        )
        assert result["diagnostics"]["resolution-state"] == "cleared-not-submitted"
