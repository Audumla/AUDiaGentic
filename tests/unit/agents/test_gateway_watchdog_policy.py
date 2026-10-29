from __future__ import annotations

from pathlib import Path

from tests.helpers.gateway_settings import use_gateway_settings

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue.watchdog_policy import load_watchdog_policy


def test_missing_watchdog_policy_is_non_destructive_and_diagnostic(monkeypatch, tmp_path: Path):
    policy = load_watchdog_policy()
    assert policy.available is False
    assert policy.activity_lease_seconds == 300.0
    assert policy.absolute_safety_ceiling_seconds == 0.0
    assert policy.initial_activity_grace_seconds == 30.0


def test_watchdog_policy_is_machine_scoped_and_digestable(monkeypatch, tmp_path: Path):
    use_gateway_settings(
        monkeypatch, tmp_path,
        watchdog={
            "policy_id": "ops", "activity_lease_seconds": 900, "absolute_safety_ceiling_seconds": 7200,
            "diagnostic_grace_seconds": 45, "initial_activity_grace_seconds": 60,
        },
    )
    policy = load_watchdog_policy()
    assert policy.available is True
    assert policy.activity_lease_seconds == 900.0
    assert policy.absolute_safety_ceiling_seconds == 7200.0
    assert policy.initial_activity_grace_seconds == 60.0
    assert policy.snapshot["policy-id"] == "ops"
    assert set(policy.snapshot) == {
        "policy-id", "policy-digest", "activity-lease-seconds", "absolute-safety-ceiling-seconds",
        "diagnostic-grace-seconds", "initial-activity-grace-seconds", "available",
    }


def test_unknown_watchdog_keys_make_the_policy_invalid(monkeypatch, tmp_path: Path):
    use_gateway_settings(monkeypatch, tmp_path, watchdog={"policy_id": "ops", "secret": "not accepted"})
    policy = load_watchdog_policy()
    assert policy.available is False
    assert policy.digest == "invalid"


def test_invalid_watchdog_values_fail_closed_to_non_destructive_defaults(monkeypatch, tmp_path: Path):
    use_gateway_settings(monkeypatch, tmp_path, watchdog={"activity_lease_seconds": "NaN"})
    policy = load_watchdog_policy()
    assert policy.available is False
    assert policy.digest == "invalid"


def test_watchdog_policy_snapshot_is_persisted_at_admission(tmp_path: Path, monkeypatch):
    use_gateway_settings(
        monkeypatch, tmp_path,
        watchdog={
            "policy_id": "admit-v1", "activity_lease_seconds": 900,
            "absolute_safety_ceiling_seconds": 0, "diagnostic_grace_seconds": 45,
        },
    )
    record = store.build_record(
        execution_profile_id="policy-profile",
        prompt_body="long review",
        watchdog_policy=load_watchdog_policy().snapshot,
    )
    store.write_record(tmp_path, record)
    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["watchdog-policy"]["policy-id"] == "admit-v1"
    assert persisted["watchdog-policy"]["activity-lease-seconds"] == 900.0
