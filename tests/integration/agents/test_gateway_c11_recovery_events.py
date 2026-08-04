"""SH07 C11: interrupted recovery event propagation — production-path integration.

Tests the full recovery→interrupted-event→agent_jobs-mapping chain with real disk
I/O, a fresh QueueManager (matching the production QueueManager singleton), and
direct event-bus subscription. No process kill required; the recovery path is
exercised by creating stale active-work entries and calling recover_gateway_requests
which is the same function the service host invokes before ingress.

This complements the unit tests in test_agents_gateway_c11_interrupted.py by
validating the production-path fixtures: real project root, real store writes,
real event bus, and agent_jobs GW_OUTCOME_MAP conformance.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.event_topics import EXECUTION_INTERRUPTED_TOPIC
from audiagentic.components.agents.gateway.queue import recovery as recovery
from audiagentic.components.agents.models.execution_profile_api import (
    create_execution_profile,
)
from audiagentic.foundation.event import get_bus
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _make_profile(project_root: Path) -> None:
    """Create a default profile for the project root."""
    create_execution_profile(
        project_root,
        {
            "profile_id": "default",
            "provider_id": "local-openai",
            "model_id": "gpt-4o",
            "is_default": True,
            "params": {"max-concurrency": 1},
        },
    )
    set_implementation_state(
        project_root,
        "providers",
        "local-openai",
        ImplementationState(enabled=True),
    )


# ---------------------------------------------------------------------------
# C11: full recovery→event→mapping chain
# ---------------------------------------------------------------------------

class TestC11RecoveryEventPropagation:
    """Production-path: recovery transitions stale requests to interrupted,
    publishes exactly one agents.execution.interrupted event per stale request,
    and agent_jobs maps it to failed-equivalent."""

    def test_stale_running_request_interrupted_event_published(
        self, tmp_path: Path,
    ) -> None:
        """A stale running request recovered by a new epoch publishes one
        agents.execution.interrupted event with correct payload fields."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        _make_profile(project_root)

        # Create and persist a queued record via the real store
        record = store.build_record(execution_profile_id="default", prompt_body="stale work")
        store.write_record(project_root, record)
        request_id = record["request-id"]

        # Simulate stale dispatch: claim with old epoch, start attempt
        claimed = store.claim_dispatch(
            project_root,
            request_id,
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )
        store.start_owned_attempt(
            project_root,
            request_id,
            owner_epoch="old-epoch",
            worker_id="worker-old",
            expected_revision=claimed["revision"],
        )
        # Active-work entry now exists

        # Subscribe to the interrupted topic on the shared event bus
        events: list[dict] = []

        def on_interrupted(event_type: str, payload: dict, metadata: dict) -> None:
            events.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, on_interrupted)
        try:
            # Recovery with a new epoch should interrupt the stale running request
            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        # Verify recovery outcome
        assert report.interrupted == 1
        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "interrupted"
        assert recovered["error"]["code"] == "CON-AGW-084"
        assert not store.active_work_path(service_root, request_id).exists()

        # Verify exactly one interrupted event was published
        assert len(events) == 1
        ev = events[0]
        assert ev["request-id"] == request_id
        assert ev["state"] == "interrupted"
        assert ev["execution-profile-id"] == "default"
        # Terminal payload fields present (may be None for provider-id/model-id
        # since the request was interrupted before provider dispatch)
        assert "provider-id" in ev
        assert "model-id" in ev
        assert "error" in ev
        assert "attempt_count" in ev
        assert "replay_required" in ev

    def test_stale_queued_request_interrupted_event_with_replay_required(
        self, tmp_path: Path,
    ) -> None:
        """A stale queued request recovered by a new epoch publishes one
        agents.execution.interrupted event with replay_required=true."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        _make_profile(project_root)

        record = store.build_record(execution_profile_id="default", prompt_body="stale queued")
        store.write_record(project_root, record)
        request_id = record["request-id"]

        # Simulate stale queued dispatch: claim with old epoch (no attempt started)
        store.claim_dispatch(
            project_root,
            request_id,
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )

        events: list[dict] = []

        def on_interrupted(event_type: str, payload: dict, metadata: dict) -> None:
            events.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, on_interrupted)
        try:
            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        # Queued → replay_required counter
        assert report.replay_required == 1
        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "interrupted"
        assert recovered["replay-required"] is True
        assert recovered["error"]["code"] == "CON-AGW-102"

        # Exactly one event, with replay_required=true
        assert len(events) == 1
        ev = events[0]
        assert ev["request-id"] == request_id
        assert ev["state"] == "interrupted"
        assert ev["replay_required"] is True

    def test_no_stale_requests_publishes_no_event(self, tmp_path: Path) -> None:
        """If recovery finds no stale requests, no interrupted event is published."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        _make_profile(project_root)

        # Create a fresh record with current epoch (not stale)
        record = store.build_record(execution_profile_id="default", prompt_body="fresh")
        store.write_record(project_root, record)
        store.claim_dispatch(
            project_root,
            record["request-id"],
            owner_epoch="current-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )

        events: list[dict] = []

        def on_interrupted(event_type: str, payload: dict, metadata: dict) -> None:
            events.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, on_interrupted)
        try:
            # Recovery with same epoch — no stale requests to interrupt
            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="current-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert report.interrupted == 0
        assert report.replay_required == 0
        # At least one live request was skipped (the fresh one we created)
        assert report.skipped_live >= 1
        assert len(events) == 0

    def test_second_recovery_pass_publishes_no_duplicate_event(
        self, tmp_path: Path,
    ) -> None:
        """After recovery interrupts a stale request, a second recovery pass
        on the same service root does not republish an interrupted event."""
        service_root = tmp_path / "service"
        project_root = tmp_path / "project"
        _make_profile(project_root)

        record = store.build_record(execution_profile_id="default", prompt_body="stale")
        store.write_record(project_root, record)
        request_id = record["request-id"]

        store.claim_dispatch(
            project_root,
            request_id,
            owner_epoch="old-epoch",
            expected_revision=record["revision"],
            service_root=service_root,
        )
        # Already claimed above; just start the attempt
        store.start_owned_attempt(
            project_root,
            request_id,
            owner_epoch="old-epoch",
            worker_id="worker-old",
            expected_revision=record["revision"] + 1,
        )

        events: list[dict] = []

        def on_interrupted(event_type: str, payload: dict, metadata: dict) -> None:
            events.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, on_interrupted)
        try:
            # First pass: interrupt the stale request
            recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
            first_count = len(events)

            # Second pass: already terminal, cleared — no new event
            recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert first_count == 1
        assert len(events) == 1  # no duplicate from second pass

    def test_agent_jobs_outcome_map_handles_interrupted(
        self, tmp_path: Path,
    ) -> None:
        """agent_jobs GW_OUTCOME_MAP maps agents.execution.interrupted to failed.
        This is the downstream contract that prevents interrupted gateway
        requests from leaving agent_jobs in an indefinite running state."""
        from audiagentic.components.agent_jobs.event_observer import (
            EventObserver,
        )

        # The mapping must exist and point to a terminal job state
        mapping = EventObserver.GW_OUTCOME_MAP
        assert EXECUTION_INTERRUPTED_TOPIC in mapping, (
            "C11: agent_jobs must handle interrupted gateway outcomes"
        )
        mapped_state = mapping[EXECUTION_INTERRUPTED_TOPIC]
        assert mapped_state == "failed", (
            f"C11: interrupted should map to failed; got {mapped_state!r}. "
            "SH12 may later introduce a dedicated 'interrupted' job state."
        )

        # Verify the topic is in GW_OUTCOME_TOPICS (subscription guard)
        from audiagentic.components.agent_jobs.event_observer import (
            GW_OUTCOME_TOPICS,
        )

        assert EXECUTION_INTERRUPTED_TOPIC in GW_OUTCOME_TOPICS
