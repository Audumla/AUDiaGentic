"""Tests for job control gateway-cancel propagation (EDJ08)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from audiagentic.components.agent_jobs import control as job_control
from audiagentic.components.agent_jobs.jobs_store import read_job_record, write_job_record
from audiagentic.foundation.event.event_bus import get_bus, reset_bus


def _setup_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".audiagentic" / "config").mkdir(parents=True)
    (project_root / ".audiagentic" / "config" / "project.yaml").write_text(
        "project-id: test-project", encoding="utf-8"
    )
    return project_root


def _write_job(
    project_root: Path,
    job_id: str,
    state: str,
    artifacts: list | None = None,
) -> dict:
    now = "2025-01-01T00:00:00Z"
    record = {
        "contract-version": "v1",
        "job-id": job_id,
        "project-id": "test-project",
        "provider-id": "local-openai",
        "workflow-profile": "standard",
        "state": state,
        "packet-id": "adhoc",
        "created-at": now,
        "updated-at": now,
        "artifacts": artifacts or [],
        "approvals": [],
    }
    write_job_record(project_root, record)
    return record


def _control_payload(job_id: str) -> dict:
    return job_control.build_job_control_request(
        job_id=job_id,
        project_id="test-project",
        requested_action="cancel",
        requested_by="operator",
        reason="test cancellation",
    )


def _collect_cancel_events():
    received: list[tuple] = []

    def handler(event_type, payload, metadata):
        received.append((event_type, payload, metadata))

    get_bus().subscribe("agents.execution.gateway.cancel-requested", handler)
    return received


class TestGatewayCancelPropagation:
    def test_migrated_job_delegates_cancellation_to_canonical_work(self, tmp_path):
        project_root = _setup_project(tmp_path)
        _write_job(project_root, "job-work-01", "ready")
        record = read_job_record(project_root, "job-work-01")
        record["work-id"] = "work_01"
        write_job_record(project_root, record)

        with patch(
            "audiagentic.components.agents.work.work_api.cancel",
            return_value={"work_id": "work_01", "state": "cancelled"},
        ) as cancel_work:
            result = job_control.request_job_control(
                project_root, _control_payload("job-work-01")
            )

        assert result["result"] == "applied"
        cancel_work.assert_called_once_with(project_root, "work_01")
        # The compatibility record is not a second lifecycle owner.
        assert read_job_record(project_root, "job-work-01")["state"] == "ready"
        legacy_root = project_root / ".audiagentic" / "runtime" / "jobs" / "job-work-01"
        assert not (legacy_root / "job-control.json").exists()
        assert not (legacy_root / "control-events.ndjson").exists()
        assert not (legacy_root / "timeline.ndjson").exists()

    def test_cancel_with_gateway_artifact_publishes_cancel_requested(self, tmp_path):
        project_root = _setup_project(tmp_path)
        reset_bus()
        received = _collect_cancel_events()

        _write_job(
            project_root,
            "job-cancel-01",
            "ready",
            artifacts=[{"kind": "gateway-request", "request-id": "req_abc123"}],
        )

        result = job_control.request_job_control(
            project_root, _control_payload("job-cancel-01")
        )

        assert result["result"] == "applied"
        assert read_job_record(project_root, "job-cancel-01")["state"] == "cancelled"
        assert len(received) == 1, "exactly one cancel-requested event expected"
        _, payload, metadata = received[0]
        assert payload["request-id"] == "req_abc123"
        assert payload["project-root"] == str(project_root)
        assert metadata["job-id"] == "job-cancel-01"
        assert "correlation_id" in metadata

        timeline_path = (
            project_root / ".audiagentic" / "runtime" / "jobs" / "job-cancel-01" / "timeline.ndjson"
        )
        entries = [
            json.loads(line)
            for line in timeline_path.read_text().strip().split("\n")
            if line.strip()
        ]
        cancel_entries = [e for e in entries if e.get("event") == "job.gateway-cancel-requested"]
        assert len(cancel_entries) == 1
        assert (cancel_entries[0].get("attributes") or {}).get("request-id") == "req_abc123"

    def test_cancel_without_artifact_publishes_nothing(self, tmp_path):
        project_root = _setup_project(tmp_path)
        reset_bus()
        received = _collect_cancel_events()

        _write_job(project_root, "job-cancel-02", "ready")

        result = job_control.request_job_control(
            project_root, _control_payload("job-cancel-02")
        )

        assert result["result"] == "applied"
        assert not received, "no gateway-request artifact => no cancel event"

    def test_pending_control_application_publishes_cancel(self, tmp_path):
        project_root = _setup_project(tmp_path)
        reset_bus()
        received = _collect_cancel_events()

        _write_job(
            project_root,
            "job-cancel-03",
            "running",
            artifacts=[{"kind": "gateway-request", "request-id": "req_def456"}],
        )

        pending = job_control.request_job_control(
            project_root, _control_payload("job-cancel-03")
        )
        assert pending["result"] == "pending"
        assert not received, "pending control must not publish yet"

        applied = job_control.apply_pending_job_control(project_root, "job-cancel-03")
        assert applied is not None and applied["result"] == "applied"
        assert len(received) == 1
        assert received[0][1]["request-id"] == "req_def456"

    def test_terminal_job_control_ignored_no_publish(self, tmp_path):
        project_root = _setup_project(tmp_path)
        reset_bus()
        received = _collect_cancel_events()

        _write_job(
            project_root,
            "job-cancel-04",
            "completed",
            artifacts=[{"kind": "gateway-request", "request-id": "req_x"}],
        )

        result = job_control.request_job_control(
            project_root, _control_payload("job-cancel-04")
        )
        assert result["result"] == "ignored"
        assert not received

    def test_publish_failure_dead_letters_and_keeps_cancellation(self, tmp_path):
        project_root = _setup_project(tmp_path)
        reset_bus()

        _write_job(
            project_root,
            "job-cancel-05",
            "ready",
            artifacts=[{"kind": "gateway-request", "request-id": "req_fail"}],
        )

        failing_bus = MagicMock()
        failing_bus.publish.side_effect = RuntimeError("bus down")

        with patch(
            "audiagentic.components.agent_jobs.control.get_bus",
            return_value=failing_bus,
        ):
            result = job_control.request_job_control(
                project_root, _control_payload("job-cancel-05")
            )

        assert result["result"] == "applied", "publish failure must not raise or roll back"
        assert read_job_record(project_root, "job-cancel-05")["state"] == "cancelled"

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists(), "publish failure must dead-letter"
        entries = [
            json.loads(line)
            for line in dl_path.read_text().strip().split("\n")
            if line.strip()
        ]
        assert any(
            e.get("event_type") == "agents.execution.gateway.cancel-requested"
            and e.get("job_id") == "job-cancel-05"
            for e in entries
        )


class TestArchitectureBoundary:
    def test_control_does_not_import_agents_gateway_api(self):
        import audiagentic.components.agent_jobs.control as mod

        for name, obj in vars(mod).items():
            mod_name = getattr(obj, "__module__", "")
            assert not mod_name.startswith(
                "audiagentic.components.agents.gateway.api"
            ), f"control.py contains reference to agents_gateway_api via {name!r}"
