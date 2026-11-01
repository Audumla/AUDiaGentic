"""SH32-B: the policy purge of one session - claim, plan, resumable shared deletion."""
from __future__ import annotations

import pytest

from audiagentic.components.agents.agents_paths import gateway_request_dir, gateway_session_dir
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.session import lineage_delete, sessions_store
from audiagentic.components.agents.gateway.session.purge_engine import purge_session_under_policy
from audiagentic.foundation.contracts.errors import AudiaGenticError
from tests.helpers.session_purge import (
    DAY,
    enable_policy,
    link_request,
    make_project,
    make_request,
    make_session,
)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    session_id = make_session(root)
    request_ids = [make_request(root, session_id), make_request(root, session_id)]
    for request_id in request_ids:
        link_request(root, session_id, request_id)
    return root, session_id, request_ids


def _purge(root, session_id, operation_id="op_1"):
    return purge_session_under_policy(root, session_id, operation_id=operation_id, policy=load_retention_policy())


def test_an_eligible_session_is_purged_with_its_requests_and_parent_last(setup, monkeypatch):
    root, session_id, request_ids = setup
    order = []
    real = lineage_delete._remove

    def recording(path, *, strict):
        order.append(path.name)
        real(path, strict=strict)

    monkeypatch.setattr(lineage_delete, "_remove", recording)
    assert _purge(root, session_id) == {"session-id": session_id, "outcome": "purged"}
    assert not gateway_session_dir(root, session_id).exists()
    assert all(not gateway_request_dir(root, rid).exists() for rid in request_ids)
    assert order[-1] == session_id and set(request_ids) <= set(order[:-1])  # the parent session goes last


@pytest.mark.parametrize("make,reason", [
    (lambda root, tmp: make_session(root, age=60), "inactivity-below-threshold"),
    (lambda root, tmp: make_session(root, state="active"), "session-not-closed"),
    (lambda root, tmp: make_session(root, clock=False), "no-accepted-turn-clock"),
])
def test_a_blocked_session_is_untouched_and_unclaimed(monkeypatch, tmp_path, make, reason):
    enable_policy(monkeypatch, tmp_path)
    root = make_project(tmp_path)
    session_id = make(root, tmp_path)
    before = sessions_store.read_session_record(root, session_id)
    assert _purge(root, session_id) == {"session-id": session_id, "outcome": "blocked", "reason": reason}
    assert sessions_store.read_session_record(root, session_id) == before


def test_a_disabled_policy_never_claims_or_deletes(monkeypatch, tmp_path, setup):
    root, session_id, _ = setup
    from tests.helpers.gateway_settings import use_gateway_settings

    use_gateway_settings(monkeypatch, tmp_path, retention={"purge_enabled": False})
    assert _purge(root, session_id)["reason"] == "policy-disabled"
    assert "retention-claim" not in sessions_store.read_session_record(root, session_id)


def test_work_that_appears_after_the_first_check_blocks_and_releases_the_claim(setup, monkeypatch):
    root, session_id, _ = setup
    from audiagentic.components.agents.gateway.session import purge_eligibility

    calls = []
    real = purge_eligibility.session_blocker

    def late_active(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:  # the recheck under the claim
            return "session-has-active-requests"
        return real(*args, **kwargs)

    monkeypatch.setattr(purge_eligibility, "session_blocker", late_active)
    assert _purge(root, session_id)["reason"] == "session-has-active-requests"
    assert "retention-claim" not in sessions_store.read_session_record(root, session_id)  # released: nothing destroyed


def test_a_claimed_session_cannot_be_resumed_or_continued(setup):
    root, session_id, _ = setup
    sessions_store.claim_retention(root, session_id, operation_id="op_other")
    with pytest.raises(AudiaGenticError) as raised:
        sessions_store.assert_no_retention_claim(root, session_id)
    assert raised.value.code == "CON-AGW-158"
    assert _purge(root, session_id, "op_1")["reason"] == "retention-claimed"


def test_a_crash_before_any_deletion_resumes_from_the_recorded_plan(setup, monkeypatch):
    root, session_id, request_ids = setup
    real_delete = lineage_delete.delete_session_lineage

    def crash(*_args, **_kwargs):
        raise RuntimeError("crash")

    monkeypatch.setattr(lineage_delete, "delete_session_lineage", crash)
    with pytest.raises(RuntimeError):
        _purge(root, session_id)
    claim = sessions_store.read_session_record(root, session_id)["retention-claim"]
    assert claim["stage"] == "deleting" and claim["plan"]["request-ids"] == sorted(request_ids)
    with pytest.raises(AudiaGenticError) as raised:  # destruction has begun: it can only be completed
        sessions_store.release_retention_claim(root, session_id, operation_id="op_1")
    assert raised.value.code == "CON-AGW-168"
    with pytest.raises(AudiaGenticError) as raised:  # and nothing may resume or continue the lineage
        sessions_store.assert_no_retention_claim(root, session_id)
    assert raised.value.code == "CON-AGW-158"
    monkeypatch.setattr(lineage_delete, "delete_session_lineage", real_delete)
    assert _purge(root, session_id) == {"session-id": session_id, "outcome": "purged"}


def test_a_crash_midway_leaves_the_parent_and_a_replay_finishes(setup, monkeypatch):
    root, session_id, request_ids = setup
    real = lineage_delete._remove
    seen = []

    def failing(path, *, strict):
        seen.append(path.name)
        if len(seen) == 3:
            raise OSError("disk error")
        real(path, strict=strict)

    monkeypatch.setattr(lineage_delete, "_remove", failing)
    with pytest.raises(OSError):
        _purge(root, session_id)
    assert gateway_session_dir(root, session_id).exists()  # parent last: still there, still carrying the plan
    monkeypatch.setattr(lineage_delete, "_remove", real)
    assert _purge(root, session_id)["outcome"] == "purged"
    assert all(not gateway_request_dir(root, rid).exists() for rid in request_ids)
    assert not gateway_session_dir(root, session_id).exists()


def test_a_missing_session_is_unchanged_never_purged(setup):
    root, session_id, _ = setup
    assert _purge(root, session_id)["outcome"] == "purged"
    assert _purge(root, session_id) == {"session-id": session_id, "outcome": "unchanged", "reason": "session-not-found"}


def test_the_manual_purge_still_removes_the_same_lineage(setup):
    from audiagentic.components.agents.gateway import api

    root, session_id, request_ids = setup
    assert api.purge_execution_session(root, session_id)["outcome"] == "purged"
    assert not gateway_session_dir(root, session_id).exists()
    assert all(not gateway_request_dir(root, rid).exists() for rid in request_ids)
    assert store.list_records(root) == []
