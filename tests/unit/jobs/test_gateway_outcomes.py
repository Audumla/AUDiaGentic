"""Tests for EDJ05: Gateway outcome propagation to job state."""
from __future__ import annotations

import json
from pathlib import Path


def _setup_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".audiagentic" / "config" / "agent-jobs").mkdir(parents=True)
    (project_root / ".audiagentic" / "config" / "project.yaml").write_text("project-id: test-project")
    return project_root


def _yaml_dump(obj) -> str:
    import yaml
    return yaml.safe_dump(obj)


def _write_triggers(project_root: Path, triggers: list[dict]) -> None:
    cfg_path = project_root / ".audiagentic" / "config" / "agent-jobs" / "event-triggers.yaml"
    cfg_path.write_text(_yaml_dump({"triggers": triggers}))


def _make_trigger(
    trigger_id: str = "t-01",
    event_pattern: str = "planning.item.created",
    enabled: bool = True,
    prompt_template: str | None = "test template",
) -> dict:
    return {
        "contract-version": "v1",
        "trigger-id": trigger_id,
        "kind": "event",
        "enabled": enabled,
        "event-pattern": event_pattern,
        "prompt-template": prompt_template,
    }


def _write_job_record(project_root: Path, job_id: str, state: str) -> dict:
    from audiagentic.components.agent_jobs.jobs_store import write_job_record

    record = {
        "contract-version": "v1",
        "job-id": job_id,
        "project-id": "test-project",
        "provider-id": "local-openai",
        "workflow-profile": "standard",
        "state": state,
        "packet-id": "adhoc",
        "created-at": "2025-01-01T00:00:00Z",
        "updated-at": "2025-01-01T00:00:00Z",
        "artifacts": [],
        "approvals": [],
    }
    write_job_record(project_root, record)
    return record


def _read_timeline_entries(project_root: Path, job_id: str) -> list[dict]:
    from audiagentic.components.agent_jobs.paths import job_timeline_path

    timeline_path = job_timeline_path(project_root, job_id)
    if not timeline_path.exists():
        return []
    entries = []
    for line in timeline_path.read_text().strip().split("\n"):
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


class TestGatewayOutcomeCompleted:
    """EDJ05: agents.llm.completed -> job completed."""

    def test_completed_transitions_running_to_completed(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-completed"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {
                "request-id": "gw-req-001",
                "provider-id": "local-openai",
                "model-id": "gpt-4o",
                "attempt_count": 1,
            },
            metadata={
                "job-id": job_id,
                "correlation_id": "corr-001",
            },
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        assert record["state"] == "completed"

    def test_completed_captures_request_id_as_artifact(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-artifact"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {"request-id": "gw-req-artifact"},
            metadata={"job-id": job_id, "correlation_id": "corr-artifact"},
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        artifacts = record.get("artifacts", [])
        gateway_artifacts = [a for a in artifacts if a.get("kind") == "gateway-request"]
        assert len(gateway_artifacts) >= 1
        assert gateway_artifacts[0]["request-id"] == "gw-req-artifact"

    def test_completed_persists_outcome_summary(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-summary"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {
                "request-id": "gw-req-summary",
                "provider-id": "test-provider",
                "model-id": "test-model",
                "attempt_count": 2,
            },
            metadata={"job-id": job_id, "correlation_id": "corr-summary"},
        )

        entries = _read_timeline_entries(project_root, job_id)
        propagated = [e for e in entries if e.get("event") == "job.state-propagated"]
        assert len(propagated) >= 1
        attrs = propagated[-1].get("attributes", {})
        assert attrs.get("provider-id") == "test-provider"
        assert attrs.get("model-id") == "test-model"
        assert attrs.get("attempt_count") == 2


class TestGatewayOutcomeFailed:
    """EDJ05: agents.llm.failed -> job failed."""

    def test_failed_transitions_running_to_failed(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-failed"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.failed",
            {"request-id": "gw-req-failed", "error": "provider timeout"},
            metadata={"job-id": job_id, "correlation_id": "corr-failed"},
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        assert record["state"] == "failed"


class TestGatewayOutcomeRejected:
    """EDJ05: agents.llm.rejected -> job failed."""

    def test_rejected_transitions_running_to_failed(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-rejected"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.rejected",
            {"request-id": "gw-req-rejected", "error": "profile not found"},
            metadata={"job-id": job_id, "correlation_id": "corr-rejected"},
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        assert record["state"] == "failed"


class TestGatewayOutcomeCancelled:
    """EDJ05: agents.llm.cancelled -> job cancelled."""

    def test_cancelled_transitions_running_to_cancelled(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-cancelled"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.cancelled",
            {"request-id": "gw-req-cancelled"},
            metadata={"job-id": job_id, "correlation_id": "corr-cancelled"},
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        assert record["state"] == "cancelled"


class TestGatewayOutcomeIdempotency:
    """EDJ05: duplicate terminal events are ignored."""

    def test_duplicate_terminal_event_ignored(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-idempotent"
        _write_job_record(project_root, job_id, state="running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {"request-id": "gw-req-idem"},
            metadata={"job-id": job_id, "correlation_id": "corr-idem"},
        )

        timeline_before = _read_timeline_entries(project_root, job_id)

        bus.publish(
            "agents.llm.completed",
            {"request-id": "gw-req-idem-dup"},
            metadata={"job-id": job_id, "correlation_id": "corr-idem"},
        )

        timeline_after = _read_timeline_entries(project_root, job_id)
        state_propagated_before = [
            e for e in timeline_before if e.get("event") == "job.state-propagated"
        ]
        state_propagated_after = [
            e for e in timeline_after if e.get("event") == "job.state-propagated"
        ]
        assert len(state_propagated_after) == len(state_propagated_before), (
            "duplicate terminal event should not create extra timeline entry"
        )

    def test_unknown_job_id_ignored(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {"request-id": "gw-req-unknown"},
            metadata={"job-id": "nonexistent-job", "correlation_id": "corr-unknown"},
        )


class TestGatewayOutcomeAwaitingApproval:
    """EDJ05: outcome during awaiting-approval is out-of-band."""

    def test_outcome_during_awaiting_approval_no_transition(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        job_id = "test-job-awaiting"
        _write_job_record(project_root, job_id, state="awaiting-approval")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        bus = get_bus()
        bus.publish(
            "agents.llm.completed",
            {"request-id": "gw-req-awaiting"},
            metadata={"job-id": job_id, "correlation_id": "corr-awaiting"},
        )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, job_id)
        assert record["state"] == "awaiting-approval", (
            "state must NOT change when outcome arrives during awaiting-approval"
        )

        entries = _read_timeline_entries(project_root, job_id)
        outcome_received = [
            e for e in entries if e.get("event") == "job.gateway-outcome-received"
        ]
        assert len(outcome_received) >= 1, (
            "gateway-outcome-received timeline entry should exist"
        )
