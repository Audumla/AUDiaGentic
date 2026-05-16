from __future__ import annotations

from audiagentic.runtime.state.session_input_store import build_session_input_record


def test_build_session_input_record_includes_core_fields() -> None:
    record = build_session_input_record(
        job_id="job_20260331_0001",
        prompt_id="prm_20260331_0001",
        provider_id="cline",
        surface="cli",
        stage="running",
        event_kind="input-submitted",
        message="Please continue from the previous step.",
        timestamp="2026-03-31T00:00:00Z",
        details={"mode": "interactive"},
    )

    assert record == {
        "contract-version": "v1",
        "job-id": "job_20260331_0001",
        "prompt-id": "prm_20260331_0001",
        "provider-id": "cline",
        "surface": "cli",
        "stage": "running",
        "event-kind": "input-submitted",
        "message": "Please continue from the previous step.",
        "timestamp": "2026-03-31T00:00:00Z",
        "details": {"mode": "interactive"},
    }
