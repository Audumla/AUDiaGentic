"""Tests for EventObserver (EDJ02)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def _setup_project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    (project_root / ".audiagentic" / "config" / "agent-jobs").mkdir(parents=True)
    (project_root / ".audiagentic" / "config" / "project.yaml").write_text("project-id: test-project")
    return project_root


def _yaml_dump(obj) -> str:
    import yaml
    return yaml.safe_dump(obj)


def _mock_build_factory(project_root: Path, job_id: str):
    """Return a side_effect for mocking build_job_from_event that also persists the record."""
    from audiagentic.components.agent_jobs.jobs_store import write_job_record

    def _side_effect(*args, **kwargs):
        now = "2025-01-01T00:00:00Z"
        record = {
            "contract-version": "v1",
            "job-id": job_id,
            "project-id": "test-project",
            "provider-id": "local-openai",
            "workflow-profile": "standard",
            "state": "created",
            "packet-id": "adhoc",
            "created-at": now,
            "updated-at": now,
            "artifacts": [],
            "approvals": [],
        }
        write_job_record(project_root, record)
        return record

    return _side_effect


def _write_triggers(project_root: Path, triggers: list[dict]) -> None:
    cfg_path = project_root / ".audiagentic" / "config" / "agent-jobs" / "event-triggers.yaml"
    cfg_path.write_text(_yaml_dump({"triggers": triggers}))


def _make_trigger(
    trigger_id: str = "t-01",
    event_pattern: str = "planning.item.created",
    enabled: bool = True,
    prompt_template: str | None = "Hello {job.id}",
) -> dict:
    return {
        "contract-version": "v1",
        "trigger-id": trigger_id,
        "kind": "event",
        "enabled": enabled,
        "event-pattern": event_pattern,
        "prompt-template": prompt_template,
    }


class TestEventObserverIdempotent:
    """EDJ02: Idempotent registration."""

    def test_double_initialize_subscribes_once(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        initial_count = get_bus().subscription_count()
        assert initial_count > 0, "should have subscribed to at least one pattern"

        obs.initialize(project_root)  # double-register

        final_count = get_bus().subscription_count()
        assert final_count == initial_count, (
            f"subscription count changed from {initial_count} to {final_count} "
            "after double register"
        )

    def test_subscription_count_matches_enabled_triggers(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        triggers = [
            _make_trigger(trigger_id="t-01", event_pattern="planning.item.created"),
            _make_trigger(trigger_id="t-02", event_pattern="planning.item.*"),
            _make_trigger(trigger_id="t-03", enabled=False, event_pattern="planning.**"),
        ]
        _write_triggers(project_root, triggers)
        reset_bus()

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            before = get_bus().subscription_count()
            obs.initialize(project_root)

            delta = get_bus().subscription_count() - before
            # 2 trigger subscriptions + 4 gateway outcome subscriptions
            assert delta == 6, f"expected 6 new subscriptions (2 triggers + 4 outcomes), got {delta}"


class TestEventObserverDisabledTrigger:
    """EDJ02: Disabled trigger is not subscribed (skipped by loader)."""

    def test_disabled_trigger_not_subscribed(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        # Only a disabled trigger — should NOT create any subscriptions
        _write_triggers(project_root, [_make_trigger(trigger_id="t-disabled", enabled=False)])
        reset_bus()

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        before = get_bus().subscription_count()
        obs.initialize(project_root)

        delta = get_bus().subscription_count() - before
        # 0 trigger subscriptions + 4 gateway outcome subscriptions
        assert delta == 4, f"expected 4 new subscriptions (0 triggers + 4 outcomes), got {delta}"


class TestEventObserverCorrelationId:
    """EDJ02: Correlation ID propagation."""

    def test_inbound_correlation_id_propagated(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        captured_metadata: dict | None = None
        bus = get_bus()
        original_publish = bus.publish

        def wrapping_publish(*args, **kwargs):
            if args and args[0] == "agents.llm.gateway.requested":
                nonlocal captured_metadata
                metadata = kwargs.get("metadata") or (args[2] if len(args) > 2 else {})
                captured_metadata = dict(metadata or {})
            return original_publish(*args, **kwargs)

        with patch.object(bus, "publish", side_effect=wrapping_publish):
            with patch(
                "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
            ) as mock_build:
                mock_build.side_effect = _mock_build_factory(project_root, "test-job-001")

                from audiagentic.components.agent_jobs.event_observer import EventObserver

                obs = EventObserver()
                obs.initialize(project_root)

                bus.publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={"correlation_id": "corr-123"},
                )

        assert captured_metadata is not None, "gateway dispatch should carry metadata"
        assert captured_metadata.get("correlation_id") == "corr-123", (
            f"expected corr-123, got {captured_metadata.get('correlation_id')}"
        )

    def test_missing_correlation_id_generated(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        captured_metadata: dict | None = None
        bus = get_bus()
        original_publish = bus.publish

        def wrapping_publish(*args, **kwargs):
            if args and args[0] == "agents.llm.gateway.requested":
                nonlocal captured_metadata
                metadata = kwargs.get("metadata") or (args[2] if len(args) > 2 else {})
                captured_metadata = dict(metadata or {})
            return original_publish(*args, **kwargs)

        with patch.object(bus, "publish", side_effect=wrapping_publish):
            with patch(
                "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
            ) as mock_build:
                mock_build.side_effect = _mock_build_factory(project_root, "test-job-002")

                from audiagentic.components.agent_jobs.event_observer import EventObserver

                obs = EventObserver()
                obs.initialize(project_root)

                bus.publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={},
                )

        assert captured_metadata is not None
        corr_id = captured_metadata.get("correlation_id")
        assert corr_id is not None and len(corr_id) > 0, (
            "missing correlation_id should be generated"
        )


class TestEventObserverDeadLetter:
    """EDJ02: Malformed payload -> dead-letter without raising."""

    def test_handler_failure_dead_letters(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        original_build = (
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        )

        with patch(original_build, side_effect=Exception("dispatch failure")):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            bus = get_bus()
            # This should NOT raise (subscriber isolation)
            bus.publish(
                "planning.item.created",
                {"test": True},
                metadata={"correlation_id": "corr-dl-01"},
            )

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists(), "dead-letter file should exist after handler failure"
        lines = dl_path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines if line.strip()]
        assert len(entries) >= 1, "at least one dead-letter entry expected"
        assert entries[-1].get("error_code"), "error code should be present"

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        if audit_path.exists():
            audit_lines = audit_path.read_text().strip().split("\n")
            audit_entries = [json.loads(line) for line in audit_lines if line.strip()]
            failed = [e for e in audit_entries if e.get("status") == "failed"]
            assert len(failed) >= 1, "at least one failed audit entry expected"


class TestEventObserverJobCreation:
    """EDJ02: Job created with correct event-source block."""

    def test_job_created_with_event_source(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-test")])
        reset_bus()

        captured_args: dict | None = None

        def capture_build(*args, **kwargs):
            nonlocal captured_args
            captured_args = kwargs
            return {
                "job-id": "test-job-003",
                "project-id": "test-project",
                "provider-id": "local-openai",
                "workflow-profile": "standard",
                "state": "created",
            }

        original_build = (
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        )

        with patch(original_build, side_effect=capture_build):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            bus = get_bus()
            bus.publish(
                "planning.item.created",
                {"item": {"id": "item-001"}},
                metadata={"correlation_id": "corr-job-01"},
            )

        assert captured_args is not None, "build_job_from_event should have been called"
        assert captured_args.get("event_type") == "planning.item.created"


class TestEventObserverAudit:
    """EDJ02: Trigger-audit entry written for fired cases."""

    def test_fired_audit_entry(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-fired")])
        reset_bus()

        original_build = (
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        )

        with patch(original_build) as mock_build:
            mock_build.side_effect = _mock_build_factory(project_root, "test-job-004")

            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            bus = get_bus()
            bus.publish(
                "planning.item.created",
                {"test": True},
                metadata={"correlation_id": "corr-fired-01"},
            )

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        assert audit_path.exists(), "audit file should exist after fired trigger"
        lines = audit_path.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines if line.strip()]
        fired = [e for e in entries if e.get("status") == "fired"]
        assert len(fired) >= 1, f"expected at least one fired entry, got {len(fired)}"
        assert fired[0].get("trigger_id") == "t-fired"
        assert fired[0].get("job_id") == "test-job-004"


class TestEventObserverArchitectureBoundary:
    """EDJ04: event_observer must NOT import agents_gateway_api."""

    def test_no_agents_gateway_api_import(self):
        import audiagentic.components.agent_jobs.event_observer as mod

        members = set(dir(mod))
        assert "agents_gateway_api" not in members, (
            "event_observer must not import or expose agents_gateway_api"
        )

        if hasattr(mod, "__dict__"):
            module_dict = vars(mod)
            for name, obj in module_dict.items():
                mod_name = getattr(obj, "__module__", "")
                assert not mod_name.startswith("audiagentic.components.agents.agents_gateway_api"), (
                    f"event_observer contains reference to agents_gateway_api via {name!r}"
                )


class TestEventObserverDispatchTransitions:
    """EDJ04: job transitions created -> ready -> running before gateway dispatch."""

    def test_dispatch_transitions_ready_and_running(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus
        from audiagentic.components.agent_jobs.jobs_store import write_job_record

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-dispatch")])
        reset_bus()

        def capture_build(*args, **kwargs):
            now = "2025-01-01T00:00:00Z"
            record = {
                "contract-version": "v1",
                "job-id": "test-job-dispatch",
                "project-id": "test-project",
                "provider-id": "local-openai",
                "workflow-profile": "standard",
                "state": "created",
                "packet-id": "adhoc",
                "created-at": now,
                "updated-at": now,
                "artifacts": [],
                "approvals": [],
            }
            write_job_record(project_root, record)
            return record

        original_build = (
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        )

        with patch(original_build, side_effect=capture_build):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            bus = get_bus()
            bus.publish(
                "planning.item.created",
                {"test": True},
                metadata={"correlation_id": "corr-dispatch-01"},
            )

        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        record = read_job_record(project_root, "test-job-dispatch")
        assert record["state"] == "running", (
            f"job should be in running state after dispatch, got {record['state']}"
        )

    def test_gateway_metadata_carrying_job_id(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus
        from audiagentic.components.agent_jobs.jobs_store import write_job_record

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        captured_metadata: dict | None = None
        bus = get_bus()
        original_publish = bus.publish

        def wrapping_publish(*args, **kwargs):
            if args and args[0] == "agents.llm.gateway.requested":
                nonlocal captured_metadata
                metadata = kwargs.get("metadata") or (args[2] if len(args) > 2 else {})
                captured_metadata = dict(metadata or {})
            return original_publish(*args, **kwargs)

        def capture_build(*args, **kwargs):
            now = "2025-01-01T00:00:00Z"
            record = {
                "contract-version": "v1",
                "job-id": "test-job-meta-001",
                "project-id": "test-project",
                "provider-id": "local-openai",
                "workflow-profile": "standard",
                "state": "created",
                "packet-id": "adhoc",
                "created-at": now,
                "updated-at": now,
                "artifacts": [],
                "approvals": [],
            }
            write_job_record(project_root, record)
            return record

        with patch.object(bus, "publish", side_effect=wrapping_publish):
            with patch(
                "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
            ) as mock_build:
                mock_build.side_effect = capture_build

                from audiagentic.components.agent_jobs.event_observer import EventObserver

                obs = EventObserver()
                obs.initialize(project_root)

                bus.publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={"correlation_id": "corr-meta-01"},
                )

        assert captured_metadata is not None, "gateway dispatch should carry metadata"
        assert captured_metadata.get("job-id") == "test-job-meta-001", (
            f"gateway metadata must include job-id, got {captured_metadata}"
        )
