from __future__ import annotations

import logging

import pytest

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

    with caplog.at_level(logging.WARNING, logger="audiagentic.foundation.event.event_bus"):
        bus.publish("planning.item.created", {}, mode=DeliveryMode.SYNC)

    failed = _record_by_operation(caplog.records, "event-dispatch")
    assert failed.levelno == logging.WARNING
    assert failed.event_type == "planning.item.created"
    assert failed.event_id
    assert failed.subscription_pattern == "planning.item.*"
    assert failed.handler.endswith("test_subscriber_error_logs_structured_context.<locals>.broken_handler")
    assert failed.exc_info is not None
    assert failed.error_code == "INT-EVT-002"
    bus.close()


def test_subscriber_failure_does_not_block_remaining_subscribers() -> None:
    bus = EventBus()
    calls: list[str] = []

    def broken_handler(*_: object) -> None:
        raise RuntimeError("boom")

    bus.subscribe("planning.item.*", broken_handler)
    bus.subscribe("planning.item.*", lambda *_: calls.append("survivor"))

    bus.publish("planning.item.created", {}, mode=DeliveryMode.SYNC)

    assert calls == ["survivor"]
    bus.close()


def test_bus_uses_event_layer_config() -> None:
    from audiagentic.foundation.event import (
        EventCycleDetectionSettings,
        EventLayerConfig,
    )

    config = EventLayerConfig(
        cycle_detection=EventCycleDetectionSettings(max_depth=3, correlation_tracking=False)
    )
    bus = EventBus(config=config)

    assert bus.config is config
    assert bus._max_depth == 3
    assert bus._correlation_tracking is False
    bus.close()


def test_close_is_idempotent_and_post_close_publish_raises() -> None:
    import pytest

    from audiagentic.foundation.event import EventBusError

    bus = EventBus()
    bus.close()
    bus.close()  # idempotent — no error

    with pytest.raises(EventBusError) as excinfo:
        bus.publish("planning.item.created", {})
    assert excinfo.value.code == "VAL-EVT-002"

    with pytest.raises(EventBusError):
        bus.subscribe("planning.item.*", lambda *_: None)


def test_subscription_count_and_unsubscribe_all() -> None:
    bus = EventBus()
    bus.subscribe("a.*", lambda *_: None)
    bus.subscribe("a.*", lambda *_: None)
    bus.subscribe("b.*", lambda *_: None)

    assert bus.subscription_count("a.*") == 2
    assert bus.subscription_count("b.*") == 1
    assert bus.subscription_count("missing.*") == 0
    assert bus.subscription_count() == 3

    bus.unsubscribe_all()
    assert bus.subscription_count() == 0
    bus.close()


def test_get_bus_singleton_is_thread_safe() -> None:
    import threading

    from audiagentic.foundation.event import get_bus, reset_bus

    reset_bus()
    barrier = threading.Barrier(8)
    instances: list[object] = []
    lock = threading.Lock()

    def _grab() -> None:
        barrier.wait()
        bus = get_bus()
        with lock:
            instances.append(bus)

    threads = [threading.Thread(target=_grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(instances) == 8
    assert all(instance is instances[0] for instance in instances)
    reset_bus()


def test_reset_bus_closes_old_instance_and_carries_config() -> None:
    from audiagentic.foundation.event import (
        EventCycleDetectionSettings,
        EventLayerConfig,
        get_bus,
        reset_bus,
    )

    config = EventLayerConfig(
        cycle_detection=EventCycleDetectionSettings(max_depth=5, correlation_tracking=True)
    )
    reset_bus(config)
    old = get_bus()
    assert old._max_depth == 5

    reset_bus()
    new = get_bus()

    assert new is not old
    assert old._closed is True
    assert new._max_depth == 5  # config carried over
    reset_bus()


def test_correlation_cycle_tracking_has_bounded_lru_retention() -> None:
    from audiagentic.foundation.event import EventCycleDetectionSettings, EventLayerConfig
    from audiagentic.foundation.event.envelope import EventEnvelope
    from audiagentic.foundation.event.event_bus import EventBus

    bus = EventBus(config=EventLayerConfig(
        cycle_detection=EventCycleDetectionSettings(max_correlation_chains=3)
    ))
    for index in range(5):
        bus.publish_envelope(EventEnvelope(
            type="test.event", payload={}, correlation_id=f"correlation-{index}"
        ))

    assert list(bus._correlation_chains) == ["correlation-2", "correlation-3", "correlation-4"]
    bus.close()


def test_one_correlation_chain_has_bounded_event_retention() -> None:
    from audiagentic.foundation.event import EventCycleDetectionSettings, EventLayerConfig
    from audiagentic.foundation.event.envelope import EventEnvelope
    from audiagentic.foundation.event.event_bus import EventBus

    bus = EventBus(config=EventLayerConfig(
        cycle_detection=EventCycleDetectionSettings(max_events_per_correlation=3)
    ))
    for index in range(5):
        bus.publish_envelope(EventEnvelope(
            id=f"event-{index}", type="test.event", payload={}, correlation_id="shared"
        ))

    assert list(bus._correlation_chains["shared"]) == ["event-2", "event-3", "event-4"]
    bus.close()


@pytest.mark.parametrize(
    "field,value",
    [("max_depth", 0), ("max_correlation_chains", True), ("max_events_per_correlation", "3")],
)
def test_cycle_detection_retention_settings_require_positive_integers(
    field: str, value: object
) -> None:
    from audiagentic.foundation.event import EventCycleDetectionSettings

    with pytest.raises(ValueError, match=field):
        EventCycleDetectionSettings(**{field: value})
