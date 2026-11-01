"""SH32-A: the machine session-purge policy and its read-only eligibility report."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import management_api, store
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.gateway.session.purge_eligibility import session_purge_report
from tests.helpers.gateway_settings import use_gateway_settings

DAY = 86400.0


def _enable(monkeypatch, tmp_path, **retention):
    base = {"purge_enabled": False, "session_purge_enabled": True, "session_purge_inactivity_seconds": DAY}
    return use_gateway_settings(monkeypatch, tmp_path, retention={**base, **retention})


def _iso(delta_seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


def _session(root: Path, *, state="closed", age=2 * DAY, requests=(), claim=None, clock=True):
    record = sessions_store.build_session_record(execution_profile_id="default")
    record["state"] = state
    timing = dict(record.get("timing") or {})
    if clock:
        timing["last-accepted-turn-at"] = _iso(age)
    else:
        timing.pop("last-accepted-turn-at", None)
    record["timing"] = timing
    record["activity"] = {**(record.get("activity") or {}), "request-ids": list(requests)}
    if claim:
        record["retention-claim"] = {"operation-id": claim, "claimed-at": _iso(0)}
    sessions_store.write_session_record(root, record)
    return record["session-id"]


def _request(root: Path, session_id: str, state="completed") -> str:
    record = store.build_record(execution_profile_id="default", prompt_body="x", session_id=session_id)
    store.write_record(root, record)
    if state != "queued":
        store.transition_record(root, record["request-id"], "running")
        if state != "running":
            store.transition_record(root, record["request-id"], state)
    return record["request-id"]


def _link(root: Path, session_id: str, request_id: str) -> None:
    record = sessions_store.read_session_record(root, session_id)
    activity = dict(record.get("activity") or {})
    activity["request-ids"] = sorted({*activity.get("request-ids", []), request_id})
    sessions_store.write_session_record(root, {**record, "activity": activity})


def _project(tmp_path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


def _blocked(report, session_id):
    return next(item["reason"] for item in report["blocked"] if item.get("session-id") == session_id)


def test_policy_is_disabled_by_default_and_changes_no_existing_digest(monkeypatch, tmp_path):
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": True, "minimum_archive_age_seconds": 3600})
    before = load_retention_policy()
    assert before.session_purge_enabled is False and before.session_purge_inactivity_seconds == 0.0
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": True, "minimum_archive_age_seconds": 3600,
                                                          "session_purge_enabled": True,
                                                          "session_purge_inactivity_seconds": DAY})
    after = load_retention_policy()
    assert after.session_purge_enabled is True and after.session_purge_inactivity_seconds == DAY
    assert after.digest != before.digest  # configured: the digest covers it
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": True, "minimum_archive_age_seconds": 3600})
    assert load_retention_policy().digest == before.digest  # unset: unchanged


@pytest.mark.parametrize("retention", [
    {"session_purge_enabled": True},
    {"session_purge_enabled": True, "session_purge_inactivity_seconds": 60},
])
def test_enabling_requires_a_threshold_of_at_least_an_hour(monkeypatch, tmp_path, retention):
    use_gateway_settings(monkeypatch, tmp_path, retention=retention)
    policy = load_retention_policy()
    # An invalid combination never yields a usable policy: it is reported invalid and everything stays off.
    assert policy.policy_id == "invalid" and not policy.available and not policy.session_purge_enabled


def test_a_disabled_policy_reports_nothing_eligible(monkeypatch, tmp_path):
    root = _project(tmp_path)
    _session(root)
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": False})
    report = management_api.gateway_session_purge_report(root)
    assert report["eligible"] == [] and report["blocked"] == [{"reason": "policy-disabled"}]


def test_an_old_closed_session_with_terminal_work_is_eligible(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    sid = _session(root)
    rid = _request(root, sid)
    _link(root, sid, rid)
    report = management_api.gateway_session_purge_report(root)
    assert report["eligible"] == [sid] and report["blocked"] == []
    assert "remote provider conversations are never touched" in report["scope"]


@pytest.mark.parametrize("kwargs,reason", [
    ({"state": "active"}, "session-not-closed"),
    ({"state": "failed"}, "session-not-closed"),
    ({"age": 60}, "inactivity-below-threshold"),
    ({"clock": False}, "no-accepted-turn-clock"),
    ({"claim": "op_other"}, "retention-claimed"),
])
def test_session_level_blockers(monkeypatch, tmp_path, kwargs, reason):
    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    sid = _session(root, **kwargs)
    report = session_purge_report(root)
    assert report["eligible"] == [] and _blocked(report, sid) == reason


def test_an_active_or_unreadable_request_blocks(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    sid = _session(root)
    _request(root, sid, state="running")
    assert _blocked(session_purge_report(root), sid) == "session-has-active-requests"
    sid2 = _session(root)
    _link(root, sid2, "req_example_000000000000")
    assert _blocked(session_purge_report(root), sid2) == "request-record-unreadable"


def test_a_request_shared_with_another_session_blocks_both(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    first = _session(root)
    rid = _request(root, first)
    second = _session(root)
    _link(root, first, rid)
    _link(root, second, rid)
    report = session_purge_report(root)
    assert _blocked(report, first) == "request-shared-with-another-session"
    assert _blocked(report, second) == "request-shared-with-another-session"


def test_a_live_runtime_blocks(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from audiagentic.components.agents.gateway.session import sessions

    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    sid = _session(root)
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: SimpleNamespace(live_session_ids=lambda: [sid]))
    assert _blocked(session_purge_report(root), sid) == "session-live"


def test_the_report_never_mutates_anything(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path)
    root = _project(tmp_path)
    sid = _session(root)
    before = sessions_store.read_session_record(root, sid)
    session_purge_report(root)
    assert sessions_store.read_session_record(root, sid) == before
