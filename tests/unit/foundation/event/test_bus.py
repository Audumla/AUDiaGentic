from __future__ import annotations

from audiagentic.foundation.event import DeliveryMode, EventBus


def test_subscription_handles_are_unique() -> None:
    bus = EventBus()
    calls: list[str] = []

    first = bus.subscribe("planning.item.*", lambda *_: calls.append("first"))
    second = bus.subscribe("planning.item.*", lambda *_: calls.append("second"))

    assert first != second

    bus.unsubscribe(first)
    bus.publish("planning.item.created", {}, mode=DeliveryMode.SYNC)

    assert calls == ["second"]
    bus.close()


def test_async_dispatch_uses_same_bus_instance() -> None:
    bus = EventBus()
    calls: list[str] = []
    bus.subscribe("planning.item.created", lambda *_: calls.append("called"))

    bus.publish("planning.item.created", {}, mode=DeliveryMode.ASYNC)
    bus.wait_idle(timeout=2)

    assert calls == ["called"]
    bus.close()
