from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import gateway_timeline_path
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.activity import RequestActivityRelay
from audiagentic.components.agents.gateway.session import turn_events
from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.transports.agent_session import (
    CorrelationQuality,
    TransportObservation,
    TransportObservationKind,
)

ACTIVITY_LABELS = (
    ("talked-to-app", "external-app"),
    ("read-resource", "resource-read"),
    ("called-tool", "tool"),
    ("searching-web", "web-search"),
    ("thinking", "thinking"),
)


def test_relay_preserves_all_activity_labels_in_durable_request_history(
    tmp_path: Path,
) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        expected_revision=0,
    )
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )
    relay = RequestActivityRelay(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        provider_capability="supported",
        min_interval_seconds=999.0,
    )
    for sequence, (label, _group) in enumerate(ACTIVITY_LABELS, start=1):
        relay.observe_provider(
            source="session-transport",
            source_instance="session:ses-1:turn:req-1",
            source_sequence=sequence,
            phase=label,
        )

    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["activity-sequence"] == len(ACTIVITY_LABELS)
    assert persisted["activity"]["provider"]["activity-label"] == "thinking"
    assert persisted["activity"]["provider"]["activity-group"] == "thinking"
    evidence = persisted["diagnostic-evidence"][-len(ACTIVITY_LABELS) :]
    assert [
        (item["activity-label"], item["activity-group"]) for item in evidence
    ] == list(ACTIVITY_LABELS)

    timeline = load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))
    activity_events = [
        entry for entry in timeline if entry["event"] == "activity.renewed"
    ]
    assert [
        (entry["attributes"]["activity-label"], entry["attributes"]["activity-group"])
        for entry in activity_events
    ] == list(ACTIVITY_LABELS)


@pytest.mark.asyncio
async def test_session_timeline_retains_every_later_activity_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []
    published: list[str] = []

    def record_session_timeline(
        project_root,
        session_id,
        event,
        *,
        state,
        attributes,
    ):
        recorded.append(
            {
                "project-root": project_root,
                "session-id": session_id,
                "event": event,
                "state": state,
                "attributes": dict(attributes),
            }
        )
        return {}

    def publish_turn_event(topic, payload, *, correlation_id=None):
        published.append(topic)

    monkeypatch.setattr(
        turn_events.session_store,
        "record_session_timeline",
        record_session_timeline,
    )
    monkeypatch.setattr(turn_events, "_publish_turn_event", publish_turn_event)
    callback = turn_events._make_on_event_callback(
        "ses-1", tmp_path, "req-1", "profile-1", "corr-1"
    )
    for sequence, (label, _group) in enumerate(ACTIVITY_LABELS, start=1):
        await callback(
            TransportObservation(
                ag_session_id="ag-s-1",
                turn_id="req-1",
                sequence=sequence,
                kind=TransportObservationKind.ACTIVITY,
                observed_at=f"2026-09-04T00:00:0{sequence}Z",
                correlation_quality=CorrelationQuality.REQUEST_SCOPED,
                attributes={"model_activity": label},
            )
        )

    activity_entries = [
        entry for entry in recorded if entry["event"] == "session.turn.activity"
    ]
    assert len(activity_entries) == len(ACTIVITY_LABELS)
    assert [
        (entry["attributes"]["activity-label"], entry["attributes"]["activity-group"])
        for entry in activity_entries
    ] == list(ACTIVITY_LABELS)
    assert published == [turn_events.TURN_MODEL_STARTED_TOPIC]


@pytest.mark.asyncio
async def test_pre_readiness_activity_reaches_real_relay_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifecycle marker must renew the durable lease before CDP readiness."""
    relay = RequestActivityRelay(
        tmp_path,
        "req-early-activity",
        owner_epoch="owner",
        worker_id="worker",
        attempt_epoch=1,
    )
    recorded: list[dict] = []
    monkeypatch.setattr(
        store,
        "record_owned_activity",
        lambda *args, **kwargs: recorded.append(dict(kwargs)) or {},
    )
    monkeypatch.setattr(
        turn_events.session_store,
        "record_session_timeline",
        lambda *args, **kwargs: {},
    )
    callback = turn_events._make_on_event_callback(
        "ses-early-activity",
        tmp_path,
        "req-early-activity",
        "profile-1",
        "corr-1",
        activity_relay=relay,
    )

    await callback(
        TransportObservation(
            ag_session_id="ag-s-1",
            turn_id="req-early-activity",
            sequence=None,
            kind=TransportObservationKind.ACTIVITY,
            observed_at="2026-09-04T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={"model_activity": "inspected"},
        )
    )

    assert len(recorded) == 1
    assert recorded[0]["phase"] == "inspected"


@pytest.mark.asyncio
async def test_timing_milestones_are_timeline_only_not_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict] = []
    marker_calls: list[bool] = []
    relay_calls: list[bool] = []

    monkeypatch.setattr(
        turn_events.session_store,
        "record_session_timeline",
        lambda project_root, session_id, event, *, state, attributes: recorded.append(
            {"event": event, "attributes": dict(attributes)}
        ) or {},
    )
    callback = turn_events._make_on_event_callback(
        "ses-1",
        tmp_path,
        "req-1",
        "profile-1",
        "corr-1",
        activity_marker=lambda: marker_calls.append(True),
        activity_relay=type(
            "Relay",
            (),
            {"observe_provider": lambda self, **kwargs: relay_calls.append(True)},
        )(),
    )
    await callback(
        TransportObservation(
            ag_session_id="ag-s-1",
            turn_id="req-1",
            sequence=0,
            kind=TransportObservationKind.TIMING,
            observed_at="2026-09-04T00:00:00Z",
            correlation_quality=CorrelationQuality.REQUEST_SCOPED,
            attributes={"timing-event": "attempt-start"},
        )
    )
    assert marker_calls == []
    assert relay_calls == []
    assert recorded[0]["event"] == "session.turn.timing"
    assert recorded[0]["attributes"]["timing-event"] == "attempt-start"
