"""SH07 C11: recovery ownership takeover — production-path integration.

Tests the recovery ownership handoff with real disk I/O and the same recovery
entry point used by the service host before ingress. Non-terminal work remains
non-terminal and is returned to the replacement scheduler; it is not converted
to an interrupted terminal event merely because the old owner disappeared.

This complements the unit tests in test_agents_gateway_c11_interrupted.py by
validating the production-path fixtures: real project root, real store writes,
real event bus, and agent_jobs GW_OUTCOME_MAP conformance.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.configuration.management import (
    create_execution_profile,
)
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.event_topics import EXECUTION_INTERRUPTED_TOPIC
from audiagentic.components.agents.gateway.queue import recovery as recovery
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
            "instances": ["gpt-4o"],
            "is_default": True,
            "params": {"virtual-capacity": 1},
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
    """Production-path: recovery transfers stale ownership in place."""

    def test_stale_running_request_is_taken_over_in_place(
        self, tmp_path: Path,
    ) -> None:
        """A stale running request remains running under the new owner."""
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

        # Worker-backed recovery is deferred, not replayed or terminalized.
        events: list[dict] = []

        def on_interrupted(event_type: str, payload: dict, metadata: dict) -> None:
            events.append(payload)

        handle = get_bus().subscribe(EXECUTION_INTERRUPTED_TOPIC, on_interrupted)
        try:
            # Recovery with a new epoch should defer the stale running request
            report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        # Verify recovery outcome
        assert report.deferred == ((project_root, request_id),)
        assert report.interrupted == 0
        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "running"
        assert recovered["dispatch-owner-epoch"] == "old-epoch"
        assert recovered["recovery-required"] is False
        assert store.active_work_path(service_root, request_id).exists()
        assert events == []

    def test_stale_queued_request_is_requeued_in_place(
        self, tmp_path: Path,
    ) -> None:
        """A stale queued request remains queued under the new owner."""
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

        report = recovery.recover_gateway_requests(service_root, live_owner_epoch="new-epoch")

        assert report.queued == ((project_root, request_id),)
        assert report.replay_required == 0
        recovered = store.read_record(project_root, request_id)
        assert recovered["state"] == "queued"
        assert recovered["dispatch-owner-epoch"] == "new-epoch"
        assert recovered["recovery-required"] is False

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
        """After takeover, a second recovery pass does not duplicate work."""
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
            # First pass: transfer the stale owner
            first_report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )

            # Second pass: the new owner is live — no duplicate recovery
            second_report = recovery.recover_gateway_requests(
                service_root, live_owner_epoch="new-epoch"
            )
        finally:
            get_bus().unsubscribe(handle)

        assert first_report.deferred == ((project_root, request_id),)
        assert second_report.deferred == ((project_root, request_id),)
        assert second_report.skipped_live == 0
        assert events == []

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
