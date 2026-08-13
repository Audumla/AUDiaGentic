from __future__ import annotations

from audiagentic.components.agent_jobs.session_input_store import (
    build_and_persist_session_input,
    build_session_input_record,
    persist_session_input,
)


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


def test_persist_session_input_for_work_uses_canonical_message(monkeypatch, tmp_path) -> None:
    calls = []

    def add_message(root, work_id, *, message_id, text, inputs):
        calls.append((root, work_id, message_id, text, inputs))
        return {"work_id": work_id}

    monkeypatch.setattr(
        "audiagentic.components.agents.work.work_api.add_message",
        add_message,
    )
    record = build_session_input_record(
        job_id="legacy-job",
        prompt_id=None,
        provider_id="provider",
        surface="cli",
        stage="running",
        event_kind="input-submitted",
        message="continue",
        timestamp="2026-08-13T00:00:00Z",
        details={"mode": "interactive"},
    )
    record["work-id"] = "work-1"

    assert persist_session_input(tmp_path, record) == record
    assert calls == [
        (
            tmp_path,
            "work-1",
            "session-input:input-submitted:2026-08-13T00:00:00Z",
            "continue",
            {
                "event-kind": "input-submitted",
                "surface": "cli",
                "stage": "running",
                "mode": "interactive",
            },
        )
    ]
    assert not list(tmp_path.rglob("*.ndjson"))


def test_build_work_input_does_not_read_legacy_job_store(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "audiagentic.components.agents.work.work_api.add_message",
        lambda *args, **kwargs: {"work_id": "work-1"},
    )

    def unexpected_job_read(*args, **kwargs):
        raise AssertionError("canonical Work input must not read the legacy job store")

    record = build_and_persist_session_input(
        tmp_path,
        job_id="legacy-job",
        work_id="work-1",
        prompt_id=None,
        provider_id=None,
        surface="api",
        stage="waiting",
        event_kind="user.input",
        message="answer",
        timestamp="2026-08-13T00:00:00Z",
        job_store=unexpected_job_read,
    )

    assert record["work-id"] == "work-1"
