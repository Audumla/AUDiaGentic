from __future__ import annotations

from audiagentic.foundation.event import EventBus, EventEnvelope, ReplayService


class MemoryStore:
    def __init__(self, envelope: EventEnvelope) -> None:
        self.envelope = envelope

    def query(self, **_kwargs):  # type: ignore[no-untyped-def]
        return [self.envelope]


def test_replay_dispatches_stored_envelope_identity() -> None:
    bus = EventBus()
    envelope = EventEnvelope(
        id="evt-1",
        type="planning.item.created",
        payload={"id": "task-1"},
        metadata={"correlation_id": "corr-1"},
    )
    seen: list[tuple[str | None, bool]] = []

    def capture(_event_type, _payload, metadata):
        seen.append((metadata.get("correlation_id"), envelope.is_replay))

    bus.subscribe("planning.item.created", capture)
    ReplayService(bus, MemoryStore(envelope), dispatch_on_replay=True).replay()

    assert seen == [("corr-1", True)]
    bus.close()
