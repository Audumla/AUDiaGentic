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

    def test_subscription_count_matches_configured_triggers(self, tmp_path):
        """EDJ23 FIX 1/2: every configured trigger subscribes, including disabled ones."""
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
            # 3 trigger subscriptions (disabled included) + 5 gateway outcome subscriptions
            assert delta == 8, f"expected 8 new subscriptions (3 triggers + 5 outcomes), got {delta}"

    def test_shared_pattern_triggers_both_fire(self, tmp_path):
        """EDJ23 FIX 1: two triggers sharing one pattern BOTH fire on a matching event."""
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(
            project_root,
            [
                _make_trigger(trigger_id="t-shared-a", event_pattern="planning.item.created"),
                _make_trigger(trigger_id="t-shared-b", event_pattern="planning.item.created"),
            ],
        )
        reset_bus()

        job_counter = {"n": 0}

        def build_side_effect(*args, **kwargs):
            job_counter["n"] += 1
            return _mock_build_factory(project_root, f"shared-job-{job_counter['n']:03d}")(
                *args, **kwargs
            )

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event",
            side_effect=build_side_effect,
        ):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            get_bus().publish(
                "planning.item.created",
                {"test": True},
                metadata={"correlation_id": "corr-shared-01"},
            )

        assert job_counter["n"] == 2, "both triggers on the shared pattern should fire"

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n") if l.strip()]
        fired_ids = sorted(e["trigger_id"] for e in entries if e.get("status") == "fired")
        assert fired_ids == ["t-shared-a", "t-shared-b"]

    def test_component_lifecycle_initializes_observer(self, tmp_path, monkeypatch):
        """EDJ22: descriptor-loaded lifecycle observer activates configured triggers."""
        import audiagentic.components.agent_jobs.event_observer as observer_module

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        instance = observer_module.EventObserver()
        monkeypatch.setattr(observer_module, "_observer_instance", instance)

        observer_module._initialize_for_component_lifecycle(project_root, {}, {})

        assert instance._subscribed is True


class TestEventObserverDisabledTrigger:
    """EDJ23 FIX 2: disabled trigger is subscribed and suppressed with an audit record."""

    def test_disabled_trigger_suppressed_with_audit(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-disabled", enabled=False)])
        reset_bus()

        dispatched = []

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            before = get_bus().subscription_count()
            obs.initialize(project_root)

            delta = get_bus().subscription_count() - before
            # 1 trigger subscription (disabled included) + 4 gateway outcome subscriptions
            assert delta == 6, f"expected 6 new subscriptions (1 trigger + 5 outcomes), got {delta}"

            bus = get_bus()
            original_publish = bus.publish

            def track_dispatch(*args, **kwargs):
                if args and args[0] == "agents.execution.gateway.requested":
                    dispatched.append(args)
                return original_publish(*args, **kwargs)

            with patch.object(bus, "publish", side_effect=track_dispatch):
                bus.publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={"correlation_id": "corr-suppressed-01"},
                )

            assert not mock_build.called, "suppressed trigger must not create a job"
            assert not dispatched, "suppressed trigger must not publish a gateway request"

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        assert audit_path.exists(), "suppression must be auditable"
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n") if l.strip()]
        suppressed = [e for e in entries if e.get("status") == "suppressed"]
        assert len(suppressed) == 1, f"expected exactly one suppressed entry, got {len(suppressed)}"
        assert suppressed[0]["trigger_id"] == "t-disabled"


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
            if args and args[0] == "agents.execution.gateway.requested":
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
            if args and args[0] == "agents.execution.gateway.requested":
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


class TestEventObserverRenderErrorDeadLetter:
    """RV246: Render errors propagate to dead-letter, no empty dispatch."""

    def test_render_error_produces_dead_letter_and_no_dispatch(self, tmp_path):
        import json as _json

        from audiagentic.foundation.contracts.errors import AudiaGenticError
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-render-fail")])
        reset_bus()

        bus = get_bus()
        dispatched = []
        original_publish = bus.publish

        def track_dispatch(*args, **kwargs):
            if args and args[0] == "agents.execution.gateway.requested":
                dispatched.append(dict(kwargs))
            return original_publish(*args, **kwargs)

        with patch.object(bus, "publish", side_effect=track_dispatch):
            with patch(
                "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
            ) as mock_build:
                with patch(
                    "audiagentic.components.agent_jobs.event_observer.render_prompt_template",
                    side_effect=AudiaGenticError("VAL-TPL-001", "template-rendering", "missing placeholder"),
                ):
                    mock_build.side_effect = _mock_build_factory(project_root, "test-job-err")

                    from audiagentic.components.agent_jobs.event_observer import EventObserver

                    obs = EventObserver()
                    obs.initialize(project_root)

                    bus.publish(
                        "planning.item.created",
                        {"test": True},
                        metadata={"correlation_id": "corr-render-err"},
                    )

        assert not dispatched, "render error should prevent gateway dispatch"

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists(), "dead-letter should exist after render error"
        entries = [_json.loads(l) for l in dl_path.read_text().strip().split("\n") if l.strip()]
        err_entries = [e for e in entries if e.get("error_code") == "VAL-TPL-001"]
        assert len(err_entries) >= 1, f"expected dead-letter entry with VAL-TPL-001, got {len(err_entries)}"


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
        from audiagentic.components.agent_jobs.jobs_store import write_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

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
        from audiagentic.components.agent_jobs.jobs_store import write_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        captured_metadata: dict | None = None
        bus = get_bus()
        original_publish = bus.publish

        def wrapping_publish(*args, **kwargs):
            if args and args[0] == "agents.execution.gateway.requested":
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


class TestEventObserverMetadataImmutability:
    """EDJ23 FIX 5: inbound bus metadata dict is never mutated by handlers."""

    def test_trigger_handler_does_not_mutate_inbound_metadata(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            mock_build.side_effect = _mock_build_factory(project_root, "test-job-immut")

            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            inbound = {"source-component": "planning"}
            snapshot = dict(inbound)
            get_bus().publish("planning.item.created", {"test": True}, metadata=inbound)

        assert inbound == snapshot, (
            f"handler mutated inbound metadata: {inbound} != {snapshot}"
        )

    def test_outcome_handler_does_not_mutate_inbound_metadata(self, tmp_path):
        from audiagentic.components.agent_jobs.jobs_store import write_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        now = "2025-01-01T00:00:00Z"
        write_job_record(project_root, {
            "contract-version": "v1",
            "job-id": "job-immut-out",
            "project-id": "test-project",
            "provider-id": "local-openai",
            "workflow-profile": "standard",
            "state": "running",
            "packet-id": "adhoc",
            "created-at": now,
            "updated-at": now,
            "artifacts": [],
            "approvals": [],
        })

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        inbound = {"job-id": "job-immut-out"}
        snapshot = dict(inbound)
        get_bus().publish("agents.execution.completed", {"request-id": "req-1"}, metadata=inbound)

        assert inbound == snapshot, (
            f"outcome handler mutated inbound metadata: {inbound} != {snapshot}"
        )


class TestGatewayOutcomeNeverRaises:
    """EDJ23 FIX 3/4: outcome handler never raises; pre-dispatch jobs stay unchanged."""

    def _write_job(self, project_root, job_id: str, state: str) -> None:
        from audiagentic.components.agent_jobs.jobs_store import write_job_record

        now = "2025-01-01T00:00:00Z"
        write_job_record(project_root, {
            "contract-version": "v1",
            "job-id": job_id,
            "project-id": "test-project",
            "provider-id": "local-openai",
            "workflow-profile": "standard",
            "state": state,
            "packet-id": "adhoc",
            "created-at": now,
            "updated-at": now,
            "artifacts": [],
            "approvals": [],
        })

    def test_outcome_for_created_job_dead_letters_without_transition(self, tmp_path):
        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        self._write_job(project_root, "job-pre-dispatch", "created")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        # Must not raise even though the transition is refused
        get_bus().publish(
            "agents.execution.completed",
            {"request-id": "req-pre"},
            metadata={"job-id": "job-pre-dispatch", "correlation_id": "corr-pre-01"},
        )

        record = read_job_record(project_root, "job-pre-dispatch")
        assert record["state"] == "created", "pre-dispatch job state must remain unchanged"

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists(), "refused propagation must be dead-lettered"
        entries = [json.loads(l) for l in dl_path.read_text().strip().split("\n") if l.strip()]
        assert any(e.get("error_code") == "CON-STATE-001" for e in entries)

        timeline_path = (
            project_root / ".audiagentic" / "runtime" / "jobs" / "job-pre-dispatch" / "timeline.ndjson"
        )
        assert timeline_path.exists(), "refused propagation must leave a timeline entry"
        tl = [json.loads(l) for l in timeline_path.read_text().strip().split("\n") if l.strip()]
        assert any(e.get("event") == "job.gateway-outcome-received" for e in tl)

    def test_outcome_handler_refuses_created_to_failed_even_with_new_edges(self, tmp_path):
        """created→failed is legal for dispatch failures only; outcome events must not use it."""
        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        self._write_job(project_root, "job-pre-fail", "created")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        get_bus().publish(
            "agents.execution.failed",
            {"request-id": "req-pre-f"},
            metadata={"job-id": "job-pre-fail"},
        )

        record = read_job_record(project_root, "job-pre-fail")
        assert record["state"] == "created", (
            "outcome handler must not drive created→failed even though the edge exists"
        )

    def test_audiagentic_error_in_outcome_handler_is_swallowed(self, tmp_path):
        """A raise would bypass dead-lettering; AudiaGenticError must be handled too."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        self._write_job(project_root, "job-agerr", "running")

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        with patch(
            "audiagentic.components.agent_jobs.event_observer.transition_and_persist",
            side_effect=AudiaGenticError("CON-STATE-001", "agent-jobs", "forced"),
        ):
            get_bus().publish(
                "agents.execution.completed",
                {"request-id": "req-agerr"},
                metadata={"job-id": "job-agerr"},
            )

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists()
        entries = [json.loads(l) for l in dl_path.read_text().strip().split("\n") if l.strip()]
        assert any(e.get("error_code") == "CON-STATE-001" for e in entries)


class TestDispatchFailureJobLifecycle:
    """EDJ23 FIX 4: dispatch failures transition the job to failed, never strand it."""

    def test_render_failure_leaves_job_failed(self, tmp_path):
        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        from audiagentic.foundation.contracts.errors import AudiaGenticError
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-render-lifecycle")])
        reset_bus()

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            mock_build.side_effect = _mock_build_factory(project_root, "job-render-fail")
            with patch(
                "audiagentic.components.agent_jobs.event_observer.render_prompt_template",
                side_effect=AudiaGenticError("VAL-TPL-001", "template-rendering", "boom"),
            ):
                from audiagentic.components.agent_jobs.event_observer import EventObserver

                obs = EventObserver()
                obs.initialize(project_root)

                get_bus().publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={"correlation_id": "corr-lifecycle-01"},
                )

        record = read_job_record(project_root, "job-render-fail")
        assert record["state"] == "failed", (
            f"render failure must fail the job, got {record['state']}"
        )

        timeline_path = (
            project_root / ".audiagentic" / "runtime" / "jobs" / "job-render-fail" / "timeline.ndjson"
        )
        tl = [json.loads(l) for l in timeline_path.read_text().strip().split("\n") if l.strip()]
        failed_entries = [e for e in tl if e.get("event") == "job.failed"]
        assert failed_entries, "job.failed timeline entry expected"
        attrs = failed_entries[-1].get("attributes") or {}
        assert attrs.get("error-code") == "VAL-TPL-001"
        assert "boom" not in json.dumps(tl), "timeline must carry only the error code"

    def test_publish_failure_leaves_job_failed(self, tmp_path):
        from audiagentic.components.agent_jobs.jobs_store import read_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-publish-lifecycle")])
        reset_bus()

        bus = get_bus()
        original_publish = bus.publish

        def failing_gateway_publish(*args, **kwargs):
            if args and args[0] == "agents.execution.gateway.requested":
                raise RuntimeError("gateway publish failure")
            return original_publish(*args, **kwargs)

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            mock_build.side_effect = _mock_build_factory(project_root, "job-publish-fail")

            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            with patch.object(bus, "publish", side_effect=failing_gateway_publish):
                bus.publish(
                    "planning.item.created",
                    {"test": True},
                    metadata={"correlation_id": "corr-lifecycle-02"},
                )

        record = read_job_record(project_root, "job-publish-fail")
        assert record["state"] == "failed", (
            f"publish failure must fail the job (not leave it running), got {record['state']}"
        )


class TestDeadLetterRedaction:
    """EDJ24: dead-letter content is structurally summarized — no raw secrets on disk."""

    def test_malformed_payload_secrets_never_reach_dead_letter_file(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger(trigger_id="t-secret")])
        reset_bus()

        secret_payload = {
            "prompt-body": "SECRET_PROMPT",
            "api_key": "sk-123",
            "nested": {"token": "tkn-nested-1"},
        }
        secret_metadata = {
            "correlation_id": "corr-secret-01",
            "session_token": "tok-meta-1",
            "subject": {"kind": "job", "id": "j-1"},
        }

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event",
            side_effect=Exception("dispatch failure"),
        ):
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            get_bus().publish("planning.item.created", secret_payload, metadata=secret_metadata)

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists(), "dead-letter entry expected"
        raw = dl_path.read_text(encoding="utf-8")
        for secret in ("SECRET_PROMPT", "sk-123", "tkn-nested-1", "tok-meta-1"):
            assert secret not in raw, f"secret {secret!r} leaked into dead-letter file"

        entries = [json.loads(l) for l in raw.strip().split("\n") if l.strip()]
        entry = entries[-1]
        # metadata is allowlist-only: unexpected keys dropped, join keys kept
        assert "session_token" not in entry["metadata"]
        assert entry["metadata"]["correlation_id"] == "corr-secret-01"
        assert entry["metadata"]["subject"] == {"kind": "job", "id": "j-1"}

    def test_outcome_handler_dead_letter_redacted(self, tmp_path):
        from audiagentic.components.agent_jobs.jobs_store import write_job_record
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [_make_trigger()])
        reset_bus()

        now = "2025-01-01T00:00:00Z"
        write_job_record(project_root, {
            "contract-version": "v1",
            "job-id": "job-secret-out",
            "project-id": "test-project",
            "provider-id": "local-openai",
            "workflow-profile": "standard",
            "state": "created",
            "packet-id": "adhoc",
            "created-at": now,
            "updated-at": now,
            "artifacts": [],
            "approvals": [],
        })

        from audiagentic.components.agent_jobs.event_observer import EventObserver

        obs = EventObserver()
        obs.initialize(project_root)

        # created-state job => refused propagation => dead-letter path exercised
        get_bus().publish(
            "agents.execution.completed",
            {"request-id": "req-s", "output": "RAW_MODEL_OUTPUT"},
            metadata={"job-id": "job-secret-out"},
        )

        dl_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "dead-letter.ndjson"
        assert dl_path.exists()
        raw = dl_path.read_text(encoding="utf-8")
        assert "RAW_MODEL_OUTPUT" not in raw, "model output leaked into dead-letter file"


class TestFilterSuppression:
    """EDJ15: filter conditions gate dispatch with an auditable suppression."""

    def _trigger_with_filter(self, filter_spec: dict) -> dict:
        trigger = _make_trigger(trigger_id="t-filter")
        trigger["filter"] = filter_spec
        return trigger

    def test_matching_filter_fires(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [self._trigger_with_filter({"payload.priority": ["P0", "P1"]})])
        reset_bus()

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            mock_build.side_effect = _mock_build_factory(project_root, "job-filter-hit")

            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            get_bus().publish(
                "planning.item.created",
                {"priority": "P1"},
                metadata={"correlation_id": "corr-f1"},
            )

        assert mock_build.called, "matching filter must fire the trigger"

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n") if l.strip()]
        assert any(e.get("status") == "fired" for e in entries)

    def test_non_matching_filter_suppressed_with_reason(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [self._trigger_with_filter({"payload.priority": ["P0", "P1"]})])
        reset_bus()

        dispatched = []

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            bus = get_bus()
            original_publish = bus.publish

            def track(*args, **kwargs):
                if args and args[0] == "agents.execution.gateway.requested":
                    dispatched.append(args)
                return original_publish(*args, **kwargs)

            with patch.object(bus, "publish", side_effect=track):
                bus.publish(
                    "planning.item.created",
                    {"priority": "P3"},
                    metadata={"correlation_id": "corr-f2"},
                )

            assert not mock_build.called, "non-matching filter must not create a job"
            assert not dispatched, "non-matching filter must not publish a gateway request"

        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n") if l.strip()]
        suppressed = [e for e in entries if e.get("status") == "suppressed"]
        assert len(suppressed) == 1
        assert suppressed[0].get("reason") == "filter"
        assert suppressed[0]["trigger_id"] == "t-filter"
        assert suppressed[0]["correlation_id"] == "corr-f2"

    def test_missing_payload_path_suppressed_without_error(self, tmp_path):
        from audiagentic.foundation.event.event_bus import get_bus, reset_bus

        project_root = _setup_project(tmp_path)
        _write_triggers(project_root, [self._trigger_with_filter({"payload.priority": "P1"})])
        reset_bus()

        with patch(
            "audiagentic.components.agent_jobs.event_observer.build_job_from_event"
        ) as mock_build:
            from audiagentic.components.agent_jobs.event_observer import EventObserver

            obs = EventObserver()
            obs.initialize(project_root)

            # payload lacks 'priority' entirely — must suppress, never raise
            get_bus().publish(
                "planning.item.created",
                {"other": 1},
                metadata={"correlation_id": "corr-f3"},
            )

        assert not mock_build.called
        audit_path = project_root / ".audiagentic" / "runtime" / "agent-jobs" / "trigger-audit.ndjson"
        entries = [json.loads(l) for l in audit_path.read_text().strip().split("\n") if l.strip()]
        assert any(
            e.get("status") == "suppressed" and e.get("reason") == "filter" for e in entries
        )
