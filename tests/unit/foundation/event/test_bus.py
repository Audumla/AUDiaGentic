from __future__ import annotations

import logging

from audiagentic.foundation.event import DeliveryMode, EventBus


def _record_by_operation(records: list[logging.LogRecord], operation: str) -> logging.LogRecord:
    return next(record for record in records if getattr(record, "operation", None) == operation)


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


def test_subscription_logs_structured_context(caplog) -> None:
    bus = EventBus()

    def handler(*_: object) -> None:
        pass

    with caplog.at_level(logging.DEBUG, logger="audiagentic.foundation.event.event_bus"):
        handle = bus.subscribe("planning.item.*", handler)
        bus.unsubscribe(handle)

    subscribed = _record_by_operation(caplog.records, "event-subscribe")
    assert subscribed.subscription_pattern == "planning.item.*"
    assert subscribed.handler.endswith("test_subscription_logs_structured_context.<locals>.handler")

    unsubscribed = _record_by_operation(caplog.records, "event-unsubscribe")
    assert unsubscribed.subscription_pattern == "planning.item.*"
    assert unsubscribed.handler.endswith("test_subscription_logs_structured_context.<locals>.handler")
    bus.close()


def test_subscriber_error_logs_structured_context(caplog) -> None:
    bus = EventBus()

    def broken_handler(*_: object) -> None:
        raise RuntimeError("boom")

    bus.subscribe("planning.item.*", broken_handler)

    with caplog.at_level(logging.ERROR, logger="audiagentic.foundation.event.event_bus"):
        bus.publish("planning.item.created", {}, mode=DeliveryMode.SYNC)

    failed = _record_by_operation(caplog.records, "event-dispatch")
    assert failed.event_type == "planning.item.created"
    assert failed.event_id
    assert failed.subscription_pattern == "planning.item.*"
    assert failed.handler.endswith("test_subscriber_error_logs_structured_context.<locals>.broken_handler")
    assert failed.exc_info is not None
    bus.close()
