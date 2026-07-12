"""Tests for build_job_from_event (EDJ03 event-trigger job creation)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from audiagentic.components.agent_jobs.paths import job_timeline_path
from audiagentic.components.agent_jobs.prompt_launch import build_job_from_event
from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
)


@pytest.fixture(autouse=True, scope="session")
def _load_error_resolutions() -> None:
    config_dirs = [
        Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    ]
    load_all_error_resolutions(config_dirs)


def _write_project_config(project_root: Path, config: dict) -> None:
    config_dir = project_root / ".audiagentic" / "config" / "agent-jobs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "project-config.yaml"
    config_path.write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )


def _write_provider_config(project_root: Path, providers: dict) -> None:
    config_dir = project_root / ".audiagentic" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "providers.yaml"
    config_path.write_text(
        yaml.safe_dump({"providers": providers}),
        encoding="utf-8",
    )


def _envelope(overrides: dict | None = None) -> dict:
    base = {
        "event-id": "evt-001",
        "source-kind": "planning",
        "occurred-at": "2025-06-15T12:00:00Z",
        "metadata": {
            "correlation-id": "corr-test-001",
            "subject": {
                "kind": "plan-item",
                "id": "PM01",
            },
        },
    }
    if overrides:
        base.update(overrides)
    return base


def _trigger_config(overrides: dict | None = None) -> dict:
    base = {
        "trigger-id": "trg-plan-create",
        "agent-profile-id": "test-profile",
        "workflow-profile": "standard",
        "target": {"kind": "adhoc"},
    }
    if overrides:
        base.update(overrides)
    return base


_RESOLVED_PROVIDER = ("test-provider", "test-model", None)


class TestJobRecordFields:
    """Verify the persisted job record has correct event-source and launch-source."""

    def _setup_project(self, project_root: Path) -> None:
        _write_project_config(project_root, {"project-id": "test-project"})
        _write_provider_config(
            project_root,
            {"test-provider": {"enabled": True}},
        )

    def test_event_source_block_populated(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        envelope = _envelope()
        trigger = _trigger_config()

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="planning.item.created",
                trigger_config=trigger,
                envelope=envelope,
                prompt_body="Test prompt.",
                job_id="job_evt_001",
            )

        assert "event-source" in job
        es = job["event-source"]
        assert es["event-type"] == "planning.item.created"
        assert es["trigger-id"] == "trg-plan-create"
        assert es["correlation-id"] == "corr-test-001"
        assert es["subject"]["kind"] == "plan-item"
        assert es["subject"]["id"] == "PM01"
        assert es["source-component"] == "planning"
        assert es["occurred-at"] == "2025-06-15T12:00:00Z"

    def test_launch_source_surface_is_event(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="planning.item.created",
                trigger_config=_trigger_config(),
                envelope=_envelope(),
                prompt_body="Test.",
                job_id="job_evt_002",
            )

        assert job["launch-source"]["surface"] == "event"

    def test_state_is_created(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="planning.item.created",
                trigger_config=_trigger_config(),
                envelope=_envelope(),
                prompt_body="Test.",
                job_id="job_evt_003",
            )

        assert job["state"] == "created"


class TestCorrelationIdHandling:
    """Verify correlation ID comes from envelope or is generated."""

    def _setup_project(self, project_root: Path) -> None:
        _write_project_config(project_root, {"project-id": "test-project"})
        _write_provider_config(
            project_root,
            {"test-provider": {"enabled": True}},
        )

    def test_correlation_id_from_envelope_metadata(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        envelope = _envelope({"metadata": {"correlation-id": "corr-custom"}})

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="test.event",
                trigger_config=_trigger_config(),
                envelope=envelope,
                prompt_body="Test.",
                job_id="job_evt_ci_01",
            )

        assert job["event-source"]["correlation-id"] == "corr-custom"

    def test_correlation_id_fallback_when_absent(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        envelope = _envelope({"metadata": {}})

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ), patch(
            "audiagentic.components.agent_jobs.prompt_launch.get_correlation_id",
            return_value=None,
        ) as mock_gen:
            job = build_job_from_event(
                tmp_path,
                event_type="test.event",
                trigger_config=_trigger_config(),
                envelope=envelope,
                prompt_body="Test.",
                job_id="job_evt_ci_02",
            )

        mock_gen.assert_called()
        assert len(job["event-source"]["correlation-id"]) == 16


class TestTimelineEntry:
    """Verify the first timeline entry is created correctly."""

    def _setup_project(self, project_root: Path) -> None:
        _write_project_config(project_root, {"project-id": "test-project"})
        _write_provider_config(
            project_root,
            {"test-provider": {"enabled": True}},
        )

    def test_timeline_created_with_job_created_event(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            build_job_from_event(
                tmp_path,
                event_type="planning.item.created",
                trigger_config=_trigger_config(),
                envelope=_envelope(),
                prompt_body="Test.",
                job_id="job_evt_tl_01",
            )

        timeline = job_timeline_path(tmp_path, "job_evt_tl_01")
        assert timeline.exists()
        records = [json.loads(line) for line in timeline.read_text(encoding="utf-8").strip().split("\n")]
        first = records[0]
        assert first["event"] == "job.created"
        assert first["state"] == "created"
        assert first["attributes"]["trigger_id"] == "trg-plan-create"
        assert first["attributes"]["event_type"] == "planning.item.created"
        assert first["attributes"]["surface"] == "event"


class TestEventTimestampMapping:
    """Verify occurred-at from envelope is preserved in event-source."""

    def _setup_project(self, project_root: Path) -> None:
        _write_project_config(project_root, {"project-id": "test-project"})
        _write_provider_config(
            project_root,
            {"test-provider": {"enabled": True}},
        )

    def test_occurred_at_mapped_from_envelope(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)
        envelope = _envelope({"occurred-at": "2025-07-10T08:30:00Z"})

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="test.event",
                trigger_config=_trigger_config(),
                envelope=envelope,
                prompt_body="Test.",
                job_id="job_evt_ts_01",
            )

        assert job["event-source"]["occurred-at"] == "2025-07-10T08:30:00Z"


class TestJobIdGeneration:
    """Verify auto-generated job ID follows convention when not provided."""

    def _setup_project(self, project_root: Path) -> None:
        _write_project_config(project_root, {"project-id": "test-project"})
        _write_provider_config(
            project_root,
            {"test-provider": {"enabled": True}},
        )

    def test_auto_generated_job_id(self, tmp_path: Path) -> None:
        self._setup_project(tmp_path)

        with patch(
            "audiagentic.components.agent_jobs.prompt_launch._resolve_agent_provider_model",
            return_value=_RESOLVED_PROVIDER,
        ):
            job = build_job_from_event(
                tmp_path,
                event_type="test.event",
                trigger_config=_trigger_config(),
                envelope=_envelope(),
                prompt_body="Test.",
            )

        assert job["job-id"].startswith("job_")
        assert len(job["job-id"]) >= 12
