"""SH07 C11: interrupted terminal lifecycle event and downstream job mapping."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.event_topics import EXECUTION_INTERRUPTED_TOPIC
from audiagentic.components.agents.gateway.queue.queue import (
    _LIFECYCLE_SUFFIX_TOPIC_MAP,
    _TERMINAL_EVENT_SUFFIXES,
    _publish_lifecycle_event,
)
from audiagentic.foundation.event import get_bus

# ---------------------------------------------------------------------------
# Topic registration / conformance
# ---------------------------------------------------------------------------

class TestInterruptedTopicRegistration:
    """C11: agents.execution.interrupted is registered and conforms."""

    def test_constant_value(self):
        assert EXECUTION_INTERRUPTED_TOPIC == "agents.execution.interrupted"

    def test_in_terminal_suffixes(self):
        assert "interrupted" in _TERMINAL_EVENT_SUFFIXES

    def test_in_lifecycle_map(self):
        assert "interrupted" in _LIFECYCLE_SUFFIX_TOPIC_MAP
        assert _LIFECYCLE_SUFFIX_TOPIC_MAP["interrupted"] == EXECUTION_INTERRUPTED_TOPIC

    def test_topic_is_registered(self):
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        registry = get_topic_registry()
        assert registry.is_registered(EXECUTION_INTERRUPTED_TOPIC)

    def test_topic_payload_has_replay_required(self):
        """The registered topic declares replay_required as optional payload."""
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        registry = get_topic_registry()
        spec = registry.get_topic(EXECUTION_INTERRUPTED_TOPIC)
        assert spec is not None
        assert "replay_required" in (spec.payload_optional or [])


# ---------------------------------------------------------------------------
# Lifecycle event publish — terminal payload includes replay_required
# ---------------------------------------------------------------------------

class TestInterruptedLifecycleEventPublish:
    """C11: publishing interrupted terminal carries replay_required."""

    def test_interrupted_terminal_carries_replay_required(self, tmp_path):
        record = store.build_record(execution_profile_id="default", prompt_body="test")
        record["state"] = "interrupted"
        record["recovery"] = {"outcome": "replay-required"}
        captured = {}

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            captured[topic] = payload

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            _publish_lifecycle_event("interrupted", record)
            assert EXECUTION_INTERRUPTED_TOPIC in captured
            ev = captured[EXECUTION_INTERRUPTED_TOPIC]
            assert ev["state"] == "interrupted"
            assert "request-id" in ev
            assert "execution-profile-id" in ev
            # Terminal fields present
            assert "provider-id" in ev
            assert "model-id" in ev
            assert "error" in ev
            assert "attempt_count" in ev
            # Replay-required flag derived from recovery.outcome
            assert ev["replay_required"] is True
        finally:
            get_bus().unsubscribe(handle)

    def test_interrupted_stale_running_has_replay_required_false(self, tmp_path):
        """Stale running recovery sets resubmit-required → replay_required=False in event."""
        record = store.build_record(execution_profile_id="default", prompt_body="test")
        record["state"] = "interrupted"
        record["recovery"] = {"outcome": "resubmit-required"}
        captured = {}

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            captured[topic] = payload

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            _publish_lifecycle_event("interrupted", record)
            ev = captured[EXECUTION_INTERRUPTED_TOPIC]
            assert ev["replay_required"] is False
        finally:
            get_bus().unsubscribe(handle)

    def test_interrupted_no_recovery_outcome_defaults_false(self, tmp_path):
        record = store.build_record(execution_profile_id="default", prompt_body="test")
        record["state"] = "interrupted"
        captured = {}

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            captured[topic] = payload

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            _publish_lifecycle_event("interrupted", record)
            ev = captured[EXECUTION_INTERRUPTED_TOPIC]
            assert ev["replay_required"] is False
        finally:
            get_bus().unsubscribe(handle)

    def test_interrupted_redacts_no_prompt(self, tmp_path):
        """The event payload must not contain prompt body."""
        record = store.build_record(execution_profile_id="default", prompt_body="test")
        record["state"] = "interrupted"
        captured = {}

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            captured[topic] = payload

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            _publish_lifecycle_event("interrupted", record)
            ev = captured[EXECUTION_INTERRUPTED_TOPIC]
            assert "prompt-body" not in ev
        finally:
            get_bus().unsubscribe(handle)


# ---------------------------------------------------------------------------
# Recovery publishes exactly-one interrupted event
# ---------------------------------------------------------------------------

def _record(project_root: Path, prompt: str = "hello") -> dict:
    record = store.build_record(execution_profile_id="default", prompt_body=prompt)
    store.write_record(project_root, record)
    return record


class TestRecoveryInterruptedExactlyOnce:
    """C11: recovery publishes agents.execution.interrupted exactly once per request."""

    def test_recovery_interrupted_publishes_event(self, tmp_path: Path) -> None:
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )
        store.start_owned_attempt(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            worker_id="worker-a",
            expected_revision=claimed["revision"],
        )

        events_received: list[str] = []

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            events_received.append(topic)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            from audiagentic.components.agents.gateway.queue import recovery as recovery

            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert report.interrupted == 1
        assert events_received == [EXECUTION_INTERRUPTED_TOPIC]

    def test_duplicate_recovery_does_not_republish(self, tmp_path: Path) -> None:
        """Second recovery pass on already-interrupted request publishes nothing."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )
        store.start_owned_attempt(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            worker_id="worker-a",
            expected_revision=claimed["revision"],
        )

        events_received: list[str] = []

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            events_received.append(topic)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            from audiagentic.components.agents.gateway.queue import recovery as recovery

            # First pass: transitions to interrupted, publishes event
            report1 = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
            assert report1.interrupted == 1
            first_count = len(events_received)

            # Second pass: already terminal, cleared without republish
            report2 = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert first_count == 1
        assert len(events_received) == 1  # no second event
        # Second pass has nothing to examine (active-work already cleared)
        assert report2.examined == 0

    def test_recovery_queued_interrupted_publishes_event(self, tmp_path: Path) -> None:
        """Queued stale record also publishes interrupted event on recovery."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        record = _record(project_root)
        store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )

        events_received: list[str] = []

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            events_received.append(topic)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            from audiagentic.components.agents.gateway.queue import recovery as recovery

            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert report.replay_required == 1
        assert events_received == [EXECUTION_INTERRUPTED_TOPIC]

    def test_recovery_queued_event_has_replay_required_true(self, tmp_path: Path) -> None:
        """End-to-end: queued recovery → replay-required outcome → event replay_required=True."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        record = _record(project_root)
        store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )

        events_payload: list[dict] = []

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            events_payload.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            from audiagentic.components.agents.gateway.queue import recovery as recovery

            recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert len(events_payload) == 1
        ev = events_payload[0]
        # C6: queued recovery → replay-required → replay_required=True
        assert ev["replay_required"] is True

    def test_recovery_running_event_has_replay_required_false(self, tmp_path: Path) -> None:
        """End-to-end: running recovery → resubmit-required outcome → event replay_required=False."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        record = _record(project_root)
        claimed = store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )
        store.start_owned_attempt(
            project_root,
            record["request-id"],
            owner_epoch="old-epoch",
            worker_id="worker-a",
            expected_revision=claimed["revision"],
        )

        events_payload: list[dict] = []

        def handler(topic: str, payload: dict, metadata: dict) -> None:
            events_payload.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, handler)
        try:
            from audiagentic.components.agents.gateway.queue import recovery as recovery

            recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert len(events_payload) == 1
        ev = events_payload[0]
        # C6: running recovery → resubmit-required → replay_required=False
        assert ev["replay_required"] is False


# ---------------------------------------------------------------------------
# Agent-jobs mapping: interrupted -> failed
# ---------------------------------------------------------------------------

class TestAgentJobsInterruptedMapping:
    """C11: agent-jobs maps interrupted gateway outcome to failed job state."""

    def test_interrupted_in_gw_outcome_topics(self):
        from audiagentic.components.agent_jobs.event_observer import (
            GW_OUTCOME_TOPICS,
        )

        assert EXECUTION_INTERRUPTED_TOPIC in GW_OUTCOME_TOPICS

    def test_interrupted_maps_to_failed(self):
        from audiagentic.components.agent_jobs.event_observer import EventObserver

        mapping = EventObserver.GW_OUTCOME_MAP
        assert mapping.get(EXECUTION_INTERRUPTED_TOPIC) == "failed"

    def test_interrupted_topic_registered_for_conformance(self):
        """The agent-jobs mirror constant is a registered topic."""
        import audiagentic.foundation.event.topic_registry as mod
        from audiagentic.foundation.event.topic_registry import (
            get_topic_registry,
            load_all_event_topics,
        )
        mod._registry_instance = None
        load_all_event_topics()
        registry = get_topic_registry()

        assert registry.is_registered(EXECUTION_INTERRUPTED_TOPIC)


# ---------------------------------------------------------------------------
# Public status / progress: interrupted is redacted
# ---------------------------------------------------------------------------

class TestInterruptedProgressRedaction:
    """C11: public progress projection shows interrupted without leaking internals."""

    def test_interrupted_phase_is_terminal_in_progress(self):
        from audiagentic.components.agents.gateway.queue.progress import (
            _TERMINAL_PHASES,
            _TERMINAL_STATE_TO_PHASE,
        )

        assert "interrupted" in _TERMINAL_PHASES
        assert _TERMINAL_STATE_TO_PHASE.get("interrupted") == "interrupted"
