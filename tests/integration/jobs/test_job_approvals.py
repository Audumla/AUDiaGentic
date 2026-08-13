from __future__ import annotations

# The test harness adds the repository source roots before importing project modules.
# ruff: noqa: E402
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.components.agent_jobs.approvals import (
    check_job_approval,
    request_job_approval,
    update_approval_state,
)
from audiagentic.components.agents.work.contracts import AgentWorkState


def test_work_linked_approval_waits_on_canonical_work(monkeypatch, tmp_path: Path) -> None:
    import audiagentic.components.agent_jobs.approvals as approvals
    waiting = []
    work = type("Work", (), {"revision": 3})()
    monkeypatch.setattr(
        "audiagentic.components.agents.work.service.get_work",
        lambda root, work_id: work,
    )
    monkeypatch.setattr(
        approvals.interaction,
        "request_interaction",
        lambda **kwargs: "apr-work",
    )
    monkeypatch.setattr(
        approvals.interaction,
        "read_record",
        lambda root, request_id: {
            "request_id": request_id,
            "kind": "job-continue",
            "title": "Continue job",
            "state": "pending",
            "source_kind": "agent-work",
            "source_id": "work-1",
            "requested_at": "2026-08-13T00:00:00Z",
            "ttl_seconds": 3600,
        },
    )

    def set_waiting(_self, root, work_id, *, interaction_id, reason, expected_revision):
        waiting.append((work_id, interaction_id, reason, expected_revision))
        return type("Waiting", (), {"state": AgentWorkState.WAITING})()

    monkeypatch.setattr(
        "audiagentic.components.agents.work.store.AgentWorkStore.set_waiting",
        set_waiting,
    )

    result = request_job_approval(
        tmp_path,
        job_id="work-1",
        work_id="work-1",
        project_id="project",
        kind="job-continue",
        summary="Continue job",
        approval_id="apr-work",
        now_ts="2026-08-13T00:00:00Z",
    )

    assert result["state"] == "pending"
    assert waiting[0][0:2] == ("work-1", "apr-work")
    assert waiting[0][2].value == "approval"


def test_work_approval_does_not_read_or_write_legacy_job_store(monkeypatch, tmp_path: Path) -> None:
    import audiagentic.components.agent_jobs.approvals as approvals
    work = type("Work", (), {"revision": 4, "state": AgentWorkState.ACTIVE})()
    monkeypatch.setattr(
        "audiagentic.components.agents.work.service.get_work",
        lambda _root, _work_id: work,
    )
    monkeypatch.setattr(
        approvals.interaction,
        "request_interaction",
        lambda **_kwargs: "apr-explicit-work",
    )
    monkeypatch.setattr(
        approvals.interaction,
        "read_record",
        lambda _root, request_id: {
            "request_id": request_id,
            "kind": "job-continue",
            "title": "Continue job",
            "state": "pending",
            "source_kind": "agent-work",
            "source_id": "work-explicit",
            "requested_at": "2026-08-13T00:00:00Z",
            "ttl_seconds": 3600,
        },
    )
    waiting = []
    monkeypatch.setattr(
        "audiagentic.components.agents.work.store.AgentWorkStore.set_waiting",
        lambda _self, root, current_work_id, **kwargs: waiting.append(
            (root, current_work_id, kwargs)
        ),
    )

    result = request_job_approval(
        tmp_path,
        job_id="unused-legacy-id",
        work_id="work-explicit",
        project_id="project",
        kind="job-continue",
        summary="Continue job",
        approval_id="apr-explicit-work",
        now_ts="2026-08-13T00:00:00Z",
    )

    assert result["state"] == "pending"
    assert waiting[0][1] == "work-explicit"


def test_work_linked_approval_response_uses_work_api(monkeypatch, tmp_path: Path) -> None:
    import audiagentic.components.agent_jobs.approvals as approvals

    monkeypatch.setattr(
        approvals.interaction,
        "read_record",
        lambda _root, _request_id: {
            "request_id": "apr-answer",
            "kind": "job-continue",
            "title": "Continue job",
            "state": "pending",
            "source_kind": "agent-work",
            "source_id": "work-answer",
            "project_id": "project",
            "requested_at": "2026-08-13T00:00:00Z",
            "ttl_seconds": 3600,
        },
    )
    answered = []
    monkeypatch.setattr(
        "audiagentic.components.agents.work.work_api.answer",
        lambda root, current_work_id, **kwargs: answered.append(
            (root, current_work_id, kwargs)
        ),
    )
    monkeypatch.setattr(
        approvals.interaction,
        "respond",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy interaction response")
        ),
    )

    result = update_approval_state(
        tmp_path,
        "apr-answer",
        "approved",
        work_id="work-answer",
    )

    assert result["approval-id"] == "apr-answer"
    assert answered == [
        (
            tmp_path,
            "work-answer",
            {"choice": "approved", "details": {"project_id": "project"}},
        )
    ]


def test_explicit_work_id_check_resumes_without_legacy_state_transition(monkeypatch, tmp_path: Path) -> None:
    import audiagentic.components.agent_jobs.approvals as approvals
    monkeypatch.setattr(
        approvals.interaction,
        "read_record",
        lambda _root, _request_id: {
            "request_id": "apr-check",
            "kind": "job-continue",
            "title": "Continue job",
            "state": "answered",
            "answer": {"choice": "approved", "details": {"project_id": "project"}},
            "source_kind": "agent-work",
            "source_id": "work-check",
            "project_id": "project",
            "requested_at": "2026-08-13T00:00:00Z",
            "ttl_seconds": 3600,
        },
    )
    resumed = []
    monkeypatch.setattr(
        "audiagentic.components.agents.work.interactions.resume_after_interaction",
        lambda root, current_work_id: resumed.append((root, current_work_id)),
    )

    result = check_job_approval(
        tmp_path,
        job_id="unused-legacy-id",
        work_id="work-check",
        approval_id="apr-check",
        now_ts="2026-08-13T01:00:00Z",
    )

    assert result["state"] == "approved"
    assert resumed == [(tmp_path, "work-check")]
