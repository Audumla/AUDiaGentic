"""Preparation timings are durable diagnostics, never provider progress."""
import json

import pytest

from audiagentic.components.agents.gateway import observability
from audiagentic.components.agents.gateway.session.dispatch import _timed_preparation_call


@pytest.mark.parametrize("fails", [False, True])
def test_preparation_trace_is_redacted_and_preserves_outcome(tmp_path, monkeypatch, fails):
    rows = []
    monkeypatch.setattr(observability, "append_observation", lambda *a, **kw: rows.append(kw))
    record = {"request-id": "req_test", "session-id": "ses_test", "attempt-epoch": 2,
              "dispatch-owner-epoch": "private-owner"}
    def operation(secret):
        assert secret == "private-prompt"
        if fails:
            raise ValueError("private-error")
        return "private-result"
    if fails:
        with pytest.raises(ValueError, match="private-error"):
            _timed_preparation_call(tmp_path, record, "provider-prepare", operation, "private-prompt")
    else:
        assert _timed_preparation_call(tmp_path, record, "provider-prepare", operation,
                                      "private-prompt") == "private-result"
    assert [r["action"]["outcome"] for r in rows] == ["begin", "failed" if fails else "completed"]
    for row in rows:
        facts = observability._project_fields(row["diagnostic_facts"])
        assert facts["phase"] == "provider-prepare"
        assert facts["elapsed-ms"] >= 0
        assert row["attempt_epoch"] == 2 and row["force_flush"]
        assert "activity" not in row
    assert "private-" not in json.dumps(rows)


def test_trace_failure_does_not_change_operation(tmp_path, monkeypatch):
    def broken(*a, **kw):
        raise OSError("trace unavailable")
    monkeypatch.setattr(observability, "append_observation", broken)
    assert _timed_preparation_call(tmp_path, {"request-id": "req_test"}, "session-open", lambda: 42) == 42


def test_preparation_spans_round_trip_core_journal(tmp_path):
    record = {"request-id": "req_timing", "session-id": "ses_timing", "attempt-epoch": 3}
    _timed_preparation_call(tmp_path, record, "transport-open", lambda: None)
    rows = observability.read_observation_page(tmp_path, "req_timing", limit=10)["items"]
    assert len(rows) == 2
    assert [r["facts"]["action"]["outcome"] for r in rows] == ["begin", "completed"]
    assert all(r["facts"]["diagnostic-facts"]["phase"] == "transport-open" for r in rows)
    assert all(r["attempt_epoch"] == 3 and r["facts"]["activity"] == {} for r in rows)
