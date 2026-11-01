"""SH32-A: the machine session-purge policy and its read-only eligibility report."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.gateway import management_api
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.gateway.session.purge_eligibility import session_purge_report
from tests.helpers.gateway_settings import use_gateway_settings
from tests.helpers.session_purge import (
    DAY,
    blocked_reason,
    enable_policy,
    link_request,
    make_project,
    make_request,
    make_session,
)


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
    root = make_project(tmp_path)
    make_session(root)
    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": False})
    report = management_api.gateway_session_purge_report(root)
    assert report["eligible"] == [] and report["blocked"] == [{"reason": "policy-disabled"}]


def test_an_old_closed_session_with_terminal_work_is_eligible(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    sid = make_session(root)
    rid = make_request(root, sid)
    link_request(root, sid, rid)
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
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    sid = make_session(root, **kwargs)
    report = session_purge_report(root)
    assert report["eligible"] == [] and blocked_reason(report, sid) == reason


def test_an_active_or_unreadable_request_blocks(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    sid = make_session(root)
    make_request(root, sid, state="running")
    assert blocked_reason(session_purge_report(root), sid) == "session-has-active-requests"
    sid2 = make_session(root)
    link_request(root, sid2, "req_example_000000000000")
    assert blocked_reason(session_purge_report(root), sid2) == "request-record-unreadable"


def test_a_request_shared_with_another_session_blocks_both(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    first = make_session(root)
    rid = make_request(root, first)
    second = make_session(root)
    link_request(root, first, rid)
    link_request(root, second, rid)
    report = session_purge_report(root)
    assert blocked_reason(report, first) == "request-shared-with-another-session"
    assert blocked_reason(report, second) == "request-shared-with-another-session"


def test_a_live_runtime_blocks(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from audiagentic.components.agents.gateway.session import sessions

    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    sid = make_session(root)
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: SimpleNamespace(live_session_ids=lambda: [sid]))
    assert blocked_reason(session_purge_report(root), sid) == "session-live"


def test_the_report_never_mutates_anything(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    sid = make_session(root)
    before = sessions_store.read_session_record(root, sid)
    session_purge_report(root)
    assert sessions_store.read_session_record(root, sid) == before
