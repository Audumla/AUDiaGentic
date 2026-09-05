from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.queue.watchdog_policy import load_watchdog_policy


def test_missing_watchdog_policy_is_non_destructive_and_diagnostic(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_WATCHDOG_POLICY", str(tmp_path / "missing.json"))
    policy = load_watchdog_policy()
    assert policy.available is False
    assert policy.activity_lease_seconds == 300.0
    assert policy.absolute_safety_ceiling_seconds == 0.0
    assert policy.initial_activity_grace_seconds == 30.0


def test_watchdog_policy_is_machine_scoped_and_digestable(monkeypatch, tmp_path: Path):
    path = tmp_path / "watchdog.json"
    path.write_text(
        '{"policy-id":"ops","activity-lease-seconds":900,'
        '"absolute-safety-ceiling-seconds":7200,"diagnostic-grace-seconds":45,'
        '"initial-activity-grace-seconds":60,'
        '"secret":"not projected"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_WATCHDOG_POLICY", str(path))
    policy = load_watchdog_policy()
    assert policy.available is True
    assert policy.activity_lease_seconds == 900.0
    assert policy.absolute_safety_ceiling_seconds == 7200.0
    assert policy.initial_activity_grace_seconds == 60.0
    assert policy.snapshot["policy-id"] == "ops"
    assert "secret" not in policy.snapshot


def test_invalid_watchdog_values_fail_closed_to_non_destructive_defaults(monkeypatch, tmp_path: Path):
    path = tmp_path / "watchdog.json"
    path.write_text('{"activity-lease-seconds": "NaN"}', encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_WATCHDOG_POLICY", str(path))
    policy = load_watchdog_policy()
    assert policy.available is False
    assert policy.digest == "invalid"


def test_watchdog_policy_snapshot_is_persisted_at_admission(tmp_path: Path, monkeypatch):
    path = tmp_path / "watchdog.json"
    path.write_text(
        '{"policy-id":"admit-v1","activity-lease-seconds":900,'
        '"absolute-safety-ceiling-seconds":0,"diagnostic-grace-seconds":45}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_WATCHDOG_POLICY", str(path))
    record = store.build_record(
        execution_profile_id="policy-profile",
        prompt_body="long review",
        watchdog_policy=load_watchdog_policy().snapshot,
    )
    store.write_record(tmp_path, record)
    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["watchdog-policy"]["policy-id"] == "admit-v1"
    assert persisted["watchdog-policy"]["activity-lease-seconds"] == 900.0
