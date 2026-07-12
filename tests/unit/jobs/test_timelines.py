"""Tests for agent-jobs timeline events and canonical event-name coverage (EDJ07)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from audiagentic.components.agent_jobs.control import (
    build_job_control_request,
    request_job_control,
)
from audiagentic.components.agent_jobs.events import (
    JOB_TIMELINE_EVENTS,
    record_job_timeline_event,
    state_to_event_name,
)
from audiagentic.components.agent_jobs.jobs_store import write_job_record
from audiagentic.components.agent_jobs.paths import job_timeline_path
from audiagentic.components.agent_jobs.records import build_job_record
from audiagentic.components.agent_jobs.state_machine import transition_and_persist

_STATE_NAMES = frozenset(
    {"created", "ready", "running", "awaiting-approval", "completed", "failed", "cancelled"}
)


def _make_record(
    project_root: Path,
    job_id: str = "job_test_001",
    state: str = "created",
    trigger_id: str | None = None,
) -> dict:
    record = build_job_record(
        job_id=job_id,
        packet_id="pkt-001",
        project_id="proj-001",
        provider_id="anthropic-bedrock-claude-sonnet-4-20250514",
        workflow_profile="standard",
        state=state,
    )
    if trigger_id is not None:
        record["trigger-id"] = trigger_id
    return record


class TestJobTimelinePath:
    def test_returns_correct_path(self, tmp_path: Path) -> None:
        p = job_timeline_path(tmp_path, "job_abc")
        assert p == tmp_path / ".audiagentic" / "runtime" / "jobs" / "job_abc" / "timeline.ndjson"


class TestStateToEventName:
    def test_all_states_mapped(self) -> None:
        for state in _STATE_NAMES:
            name = state_to_event_name(state)
            assert name is not None, f"missing mapping for state {state!r}"
            assert name == f"job.{state}", f"unexpected event name {name!r} for state {state!r}"

    def test_unknown_state_returns_none(self) -> None:
        assert state_to_event_name("nonexistent") is None


class TestRecordJobTimelineEvent:
    def test_writes_one_json_line_with_canonical_fields(self, tmp_path: Path) -> None:
        record_job_timeline_event(
            tmp_path,
            "job_001",
            "job.running",
            state="running",
            correlation_id="corr-xyz",
        )
        timeline = job_timeline_path(tmp_path, "job_001")
        assert timeline.exists()
        entries = timeline.read_text(encoding="utf-8").strip().split("\n")
        assert len(entries) == 1

        rec = json.loads(entries[0])
        assert rec["event"] == "job.running"
        assert rec["state"] == "running"
        assert rec["component"] == "agent-jobs"
        assert rec["resource-kind"] == "job"
        assert rec["resource-id"] == "job_001"
        assert rec["correlation-id"] == "corr-xyz"
        assert rec["attributes"]["job-id"] == "job_001"

    def test_attributes_passthrough(self, tmp_path: Path) -> None:
        record_job_timeline_event(
            tmp_path,
            "job_002",
            "job.completed",
            state="completed",
            attributes={"trigger-id": "trg-55"},
        )
        timeline = job_timeline_path(tmp_path, "job_002")
        rec = json.loads(timeline.read_text(encoding="utf-8").strip())
        assert rec["attributes"]["trigger-id"] == "trg-55"


class TestTransitionTimelineEvent:
    def _setup(self, tmp_path: Path, state: str = "created", trigger_id: str | None = None) -> str:
        record = _make_record(tmp_path, state=state, trigger_id=trigger_id)
        write_job_record(tmp_path, record)
        return record["job-id"]

    def test_single_transition_writes_one_timeline_entry(self, tmp_path: Path) -> None:
        job_id = self._setup(tmp_path, state="created")
        transition_and_persist(tmp_path, job_id, "ready", correlation_id="corr-1")
        timeline = job_timeline_path(tmp_path, job_id)
        assert timeline.exists()
        entries = timeline.read_text(encoding="utf-8").strip().split("\n")
        assert len(entries) == 1
        rec = json.loads(entries[0])
        assert rec["event"] == "job.ready"
        assert rec["state"] == "ready"

    def test_two_transitions_write_two_entries(self, tmp_path: Path) -> None:
        job_id = self._setup(tmp_path, state="created")
        transition_and_persist(tmp_path, job_id, "ready", correlation_id="corr-1")
        transition_and_persist(tmp_path, job_id, "running", correlation_id="corr-2")
        timeline = job_timeline_path(tmp_path, job_id)
        entries = timeline.read_text(encoding="utf-8").strip().split("\n")
        assert len(entries) == 2
        events = [json.loads(e)["event"] for e in entries]
        assert events == ["job.ready", "job.running"]

    def test_lifecycle_events_include_job_id_and_correlation(self, tmp_path: Path) -> None:
        job_id = self._setup(tmp_path, state="created")
        transition_and_persist(tmp_path, job_id, "ready", correlation_id="corr-abc")
        timeline = job_timeline_path(tmp_path, job_id)
        rec = json.loads(timeline.read_text(encoding="utf-8").strip())
        assert rec["resource-id"] == job_id
        assert rec["correlation-id"] == "corr-abc"
        assert rec["attributes"]["job-id"] == job_id

    def test_event_triggered_job_includes_trigger_id(self, tmp_path: Path) -> None:
        job_id = self._setup(tmp_path, state="created", trigger_id="trg-42")
        transition_and_persist(
            tmp_path,
            job_id,
            "ready",
            correlation_id="corr-t",
            trigger_id="trg-42",
        )
        timeline = job_timeline_path(tmp_path, job_id)
        rec = json.loads(timeline.read_text(encoding="utf-8").strip())
        assert rec["attributes"]["trigger-id"] == "trg-42"

    def test_state_attributes_include_previous_state(self, tmp_path: Path) -> None:
        job_id = self._setup(tmp_path, state="created")
        transition_and_persist(tmp_path, job_id, "ready", correlation_id="corr-s")
        timeline = job_timeline_path(tmp_path, job_id)
        rec = json.loads(timeline.read_text(encoding="utf-8").strip())
        assert rec["attributes"]["previous-state"] == "created"

    def test_request_id_passthrough(self, tmp_path: Path) -> None:
        record = _make_record(tmp_path, state="created")
        record["packet-id"] = "pkt-req-123"
        write_job_record(tmp_path, record)

        transition_and_persist(tmp_path, "job_test_001", "ready", correlation_id="corr-r")
        timeline = job_timeline_path(tmp_path, "job_test_001")
        rec = json.loads(timeline.read_text(encoding="utf-8").strip())
        assert rec["attributes"]["request-id"] == "pkt-req-123"


class TestCanonicalEventNameCoverage:
    def test_tuple_covers_every_event_name_written_in_agent_jobs(self) -> None:
        agent_jobs_dir = Path(__file__).resolve().parents[4] / "src" / "audiagentic" / "components" / "agent_jobs"

        seen_event_names: set[str] = set()
        for root, _dirs, files in os.walk(agent_jobs_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                filepath = Path(root) / fname
                text = filepath.read_text(encoding="utf-8")
                lines = text.splitlines()
                for line in lines:
                    stripped = line.strip()
                    if "JOB_TIMELINE_EVENTS" in stripped and not stripped.startswith("#"):
                        continue
                    if "state_to_event_name" in stripped:
                        continue
                    tokens = stripped.replace('"', ' ').replace("'", " ").split()
                    for token in tokens:
                        token = token.strip(",;():")
                        if token.startswith("job.") and "." in token:
                            seen_event_names.add(token)

        canonical = set(JOB_TIMELINE_EVENTS)
        extras = seen_event_names - canonical
        assert not extras, (
            f"event names found in agent_jobs code but not in JOB_TIMELINE_EVENTS tuple: {sorted(extras)}"
        )


class TestControlTimelineEvents:
    def _setup_job(self, tmp_path: Path, state: str = "ready") -> str:
        record = build_job_record(
            job_id="job_ctrl_001",
            packet_id="pkt-ctrl",
            project_id="proj-ctrl",
            provider_id="anthropic-bedrock-claude-sonnet-4-20250514",
            workflow_profile="standard",
            state=state,
        )
        write_job_record(tmp_path, record)
        return "job_ctrl_001"

    def test_control_applied_writes_timeline_entry(self, tmp_path: Path) -> None:
        job_id = self._setup_job(tmp_path, state="ready")
        payload = build_job_control_request(
            job_id=job_id,
            project_id="proj-ctrl",
            requested_action="cancel",
            requested_by="test-user",
            reason="manual cancellation",
        )
        request_job_control(tmp_path, payload)
        timeline = job_timeline_path(tmp_path, job_id)
        entries = timeline.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(e)["event"] for e in entries]
        assert "job.control.requested" in events

    def test_control_ignored_writes_timeline_entry(self, tmp_path: Path) -> None:
        job_id = self._setup_job(tmp_path, state="completed")
        payload = build_job_control_request(
            job_id=job_id,
            project_id="proj-ctrl",
            requested_action="cancel",
            requested_by="test-user",
            reason="attempt on terminal job",
        )
        result = request_job_control(tmp_path, payload)
        assert result["result"] == "ignored"
        timeline = job_timeline_path(tmp_path, job_id)
        entries = timeline.read_text(encoding="utf-8").strip().split("\n")
        events = [json.loads(e)["event"] for e in entries]
        assert "job.control.ignored" in events
