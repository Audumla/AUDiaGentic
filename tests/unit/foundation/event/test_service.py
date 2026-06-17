from __future__ import annotations

from audiagentic.foundation.event import EventBus, EventService, StructuredLog
from audiagentic.foundation.event import event_service as event_service_module


class MemoryLog(StructuredLog):
    def __init__(self) -> None:
        super().__init__(None)
        self.event_ids: list[str] = []

    def emit_event(self, envelope):  # type: ignore[no-untyped-def]
        self.event_ids.append(envelope.id)


def test_event_service_logs_and_dispatches_same_envelope(monkeypatch) -> None:
    log = MemoryLog()
    bus = EventBus()
    dispatched_ids: list[str | None] = []

    def capture(_event_type, _payload, metadata):
        dispatched_ids.append(metadata.get("event_id"))

    def publish_envelope(envelope, mode):  # type: ignore[no-untyped-def]
        envelope.metadata["event_id"] = envelope.id
        return EventBus.publish_envelope(bus, envelope, mode=mode)

    monkeypatch.setattr(event_service_module, "get_bus", lambda: bus)
    monkeypatch.setattr(bus, "publish_envelope", publish_envelope)
    bus.subscribe("planning.item.created", capture)

    EventService(log).publish("planning.item.created", {"id": "task-1"}, mode="sync")

    assert dispatched_ids == log.event_ids
    bus.close()
