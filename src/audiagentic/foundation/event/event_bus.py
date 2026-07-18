"""Event bus implementation for in-process event dispatch.

Implements EventBusProtocol with SYNC/ASYNC dispatch, wildcard pattern matching,
subscriber isolation, and cycle detection.

MQ Migration: This implementation can be replaced with ExternalMQBus that
implements the same EventBusProtocol interface.
"""

from __future__ import annotations

import logging
import threading
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeVar

from .envelope import EventEnvelope
from .event_config import EventLayerConfig
from .event_exceptions import CycleDetectedError, EventBusError, SubscriberError
from .patterns import pattern_matches

logger = logging.getLogger(__name__)


def _handler_name(handler: Callable[..., Any]) -> str:
    module = getattr(handler, "__module__", "")
    qualname = getattr(handler, "__qualname__", repr(handler))
    return f"{module}.{qualname}" if module else qualname


class DeliveryMode(Enum):
    """Event delivery mode."""

    SYNC = "sync"
    ASYNC = "async"


PayloadT = TypeVar("PayloadT", bound=dict, contravariant=True)


class EventHandler(Protocol[PayloadT]):
    """Structural type for event handlers with an optionally-typed payload.

    Payload types are TypedDicts (plain dicts at runtime), so typed and
    untyped handlers are interchangeable on the bus — this is static typing
    only, with no runtime dispatch difference. Default usage:
    ``EventHandler[dict[str, Any]]``.
    """

    def __call__(
        self, event_type: str, payload: PayloadT, metadata: dict[str, Any]
    ) -> None: ...


@dataclass
class SubscriptionHandle:
    """Handle for unsubscribing from events."""

    pattern: str
    handler: Callable[[str, dict[str, Any], dict[str, Any]], None]
    _id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __hash__(self) -> int:
        return hash(self._id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SubscriptionHandle):
            return False
        return self._id == other._id


class EventBusProtocol(ABC):
    """Abstract protocol for event bus implementations.

    This interface allows swapping between in-process and external MQ
    transports. Implementations must provide graceful shutdown via
    :meth:`close` (idempotent; post-close publishes raise VAL-EVT-002),
    envelope passthrough via :meth:`publish_envelope`, and the
    :meth:`wait_idle`/:meth:`subscription_count` observability surface.
    """

    @abstractmethod
    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        pass

    @abstractmethod
    def publish_envelope(
        self,
        envelope: EventEnvelope,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        pass

    @abstractmethod
    def subscribe(
        self,
        pattern: str,
        handler: Callable[[str, dict[str, Any], dict[str, Any]], None],
    ) -> SubscriptionHandle:
        pass

    @abstractmethod
    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        pass

    @abstractmethod
    def unsubscribe_all(self) -> None:
        """Remove every subscription (clean shutdown support)."""

    @abstractmethod
    def subscription_count(self, pattern: str | None = None) -> int:
        """Count subscriptions for an exact pattern key, or all when None.

        The pattern argument matches the subscription pattern literally (no
        wildcard expansion): ``subscription_count("a.*")`` counts handlers
        subscribed with the pattern string ``"a.*"``.
        """

    @abstractmethod
    def close(self) -> None:
        """Shut down the bus. Idempotent; releases transport resources."""

    @abstractmethod
    def wait_idle(self, timeout: float | None = None) -> None:
        """Block until queued async subscriber work completes (or timeout)."""


class EventBus(EventBusProtocol):
    """In-process event bus implementation.

    Features:
    - SYNC/ASYNC dispatch modes
    - Wildcard pattern matching (* and **)
    - Subscriber isolation (one failure doesn't affect others)
    - Cycle detection via propagation_depth and correlation_id
    - Event envelope generation

    Usage:
        # Explicit dependency injection (preferred)
        bus = EventBus()
        handle = bus.subscribe("planning.task.*", handler)
        bus.publish("planning.task.done", {"task_id": "task-0123"}, mode=DeliveryMode.SYNC)

        # Or singleton for bootstrap convenience
        from audiagentic.foundation.event import get_bus
        bus = get_bus()
    """

    def __init__(
        self,
        source_component: str = "default",
        max_depth: int = 10,
        async_executor: ThreadPoolExecutor | None = None,
        config: EventLayerConfig | None = None,
    ) -> None:
        self._config = config
        if config is not None:
            max_depth = config.cycle_detection.max_depth
            self._correlation_tracking = config.cycle_detection.correlation_tracking
            self._max_correlation_chains = max(1, config.cycle_detection.max_correlation_chains)
            self._max_events_per_correlation = config.cycle_detection.max_events_per_correlation
        else:
            self._correlation_tracking = True
            self._max_correlation_chains = 4096
            self._max_events_per_correlation = 1024
        self._source_component = source_component
        self._max_depth = max_depth
        self._async_executor = async_executor or ThreadPoolExecutor(max_workers=4)
        self._pending_async: set[Future] = set()
        self._pending_lock = threading.Lock()
        self._closed = False

        self._subscriptions: dict[str, list[SubscriptionHandle]] = {}
        self._subscription_lock = threading.Lock()

        self._correlation_chains: OrderedDict[str, OrderedDict[str, None]] = OrderedDict()
        self._chain_lock = threading.Lock()

    @property
    def config(self) -> EventLayerConfig | None:
        """The EventLayerConfig this bus was constructed with, if any."""
        return self._config

    def _require_open(self, operation: str) -> None:
        if self._closed:
            raise EventBusError(
                f"event bus is closed; {operation} rejected",
                code="VAL-EVT-002",
                details={"operation": operation},
            )

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        metadata = metadata or {}

        envelope = EventEnvelope(
            type=event_type,
            payload=payload,
            metadata=metadata,
            source_component=self._source_component,
        )
        self.publish_envelope(envelope, mode=mode)

    def publish_envelope(
        self,
        envelope: EventEnvelope,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        """Publish an already-created canonical event envelope."""
        self._require_open("publish")
        self._check_cycle(envelope)

        if mode == DeliveryMode.SYNC:
            self._dispatch_sync(envelope)
        else:
            self._dispatch_async(envelope)

    def subscribe(
        self,
        pattern: str,
        handler: Callable[[str, dict[str, Any], dict[str, Any]], None],
    ) -> SubscriptionHandle:
        self._require_open("subscribe")
        handle = SubscriptionHandle(pattern=pattern, handler=handler)

        with self._subscription_lock:
            if pattern not in self._subscriptions:
                self._subscriptions[pattern] = []
            self._subscriptions[pattern].append(handle)

        logger.debug(
            "Subscribed to pattern: %s",
            pattern,
            extra={
                "operation": "event-subscribe",
                "subscription_pattern": pattern,
                "handler": _handler_name(handler),
            },
        )
        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        with self._subscription_lock:
            if handle.pattern in self._subscriptions:
                self._subscriptions[handle.pattern] = [
                    h for h in self._subscriptions[handle.pattern] if h != handle
                ]

        logger.debug(
            "Unsubscribed from pattern: %s",
            handle.pattern,
            extra={
                "operation": "event-unsubscribe",
                "subscription_pattern": handle.pattern,
                "handler": _handler_name(handle.handler),
            },
        )

    def unsubscribe_all(self) -> None:
        with self._subscription_lock:
            self._subscriptions.clear()
        logger.debug("Unsubscribed all patterns", extra={"operation": "event-unsubscribe-all"})

    def subscription_count(self, pattern: str | None = None) -> int:
        with self._subscription_lock:
            if pattern is not None:
                return len(self._subscriptions.get(pattern, []))
            return sum(len(handles) for handles in self._subscriptions.values())

    def _dispatch_sync(self, envelope: EventEnvelope) -> None:
        """Dispatch event synchronously to all matching subscribers.

        Subscriber isolation invariant: handler failures are wrapped in
        SubscriberError for structured diagnostics and logged — never
        re-raised — so remaining subscribers always receive the event.
        """
        matching = self._find_matching_subscribers(envelope.type)

        for handle in matching:
            try:
                handle.handler(envelope.type, envelope.payload, envelope.metadata)
            except Exception as e:
                error = SubscriberError(
                    str(e),
                    pattern=handle.pattern,
                    handler_name=_handler_name(handle.handler),
                    event_type=envelope.type,
                )
                logger.warning(
                    "Subscriber error for pattern %s: %s",
                    handle.pattern,
                    error,
                    exc_info=True,
                    extra={
                        "operation": "event-dispatch",
                        "event_type": envelope.type,
                        "event_id": envelope.id,
                        "subscription_pattern": handle.pattern,
                        "handler": _handler_name(handle.handler),
                        "error_code": error.code,
                    },
                )

    def _dispatch_async(self, envelope: EventEnvelope) -> None:
        """Dispatch event asynchronously to all matching subscribers."""
        future = self._async_executor.submit(self._dispatch_sync, envelope)
        with self._pending_lock:
            self._pending_async.add(future)
        future.add_done_callback(self._discard_pending_async)

    def _find_matching_subscribers(self, event_type: str) -> list[SubscriptionHandle]:
        """Find all subscribers matching the event type."""
        matching = []

        with self._subscription_lock:
            for pattern, handles in self._subscriptions.items():
                if self._pattern_matches(pattern, event_type):
                    matching.extend(handles)

        return matching

    def _pattern_matches(self, pattern: str, event_type: str) -> bool:
        """Check if event type matches pattern with wildcard support."""
        return pattern_matches(pattern, event_type)

    def _check_cycle(self, envelope: EventEnvelope) -> None:
        """Check for cycles in event propagation."""
        if envelope.propagation_depth >= self._max_depth:
            raise CycleDetectedError(
                f"Propagation depth exceeded ({envelope.propagation_depth} >= {self._max_depth})",
                event_id=envelope.id,
                propagation_depth=envelope.propagation_depth,
            )

        if envelope.correlation_id and self._correlation_tracking:
            with self._chain_lock:
                if envelope.correlation_id not in self._correlation_chains:
                    if len(self._correlation_chains) >= self._max_correlation_chains:
                        self._correlation_chains.popitem(last=False)
                    self._correlation_chains[envelope.correlation_id] = OrderedDict()
                else:
                    self._correlation_chains.move_to_end(envelope.correlation_id)

                if envelope.id in self._correlation_chains[envelope.correlation_id]:
                    raise CycleDetectedError(
                        f"Cycle detected for correlation_id {envelope.correlation_id}",
                        event_id=envelope.id,
                        correlation_id=envelope.correlation_id,
                    )

                events = self._correlation_chains[envelope.correlation_id]
                if len(events) >= self._max_events_per_correlation:
                    events.popitem(last=False)
                events[envelope.id] = None

    def close(self) -> None:
        """Close the event bus and cleanup resources. Idempotent."""
        if self._closed:
            return
        self._closed = True
        self._async_executor.shutdown(wait=True)

    def wait_idle(self, timeout: float | None = None) -> None:
        """Wait for currently queued async subscriber work to finish."""
        with self._pending_lock:
            pending = set(self._pending_async)
        if pending:
            wait(pending, timeout=timeout)

    def _discard_pending_async(self, future: Future) -> None:
        with self._pending_lock:
            self._pending_async.discard(future)


# Singleton
_bus_instance: EventBus | None = None
_bus_lock = threading.Lock()


def get_bus(config: EventLayerConfig | None = None) -> EventBus:
    """Get the singleton EventBus instance (thread-safe, double-checked).

    On first creation the bus is configured from *config*, or from
    ``load_event_config()`` when none is passed (missing config file yields
    defaults — the loader never fails on absence). A *config* argument on a
    later call does NOT reconfigure the existing bus; use
    :func:`reset_bus` to swap configuration.

    Note: The event bus is shared across all component profiles within a
    process. Component registration is constrained to one profile per process
    (CP05). Subscriptions from lifecycle observers are bound at registration
    time and persist for the process lifetime.
    """
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                if config is None:
                    from .event_config import load_event_config

                    config = load_event_config()
                _bus_instance = EventBus(config=config)
    return _bus_instance


def reset_bus(config: EventLayerConfig | None = None) -> None:
    """Replace the singleton EventBus, closing the old instance first.

    The new bus reuses the old bus's config unless *config* is passed.
    Lifecycle-observer dispatchers are re-subscribed on the new bus so
    observers registered before the reset keep working. Used by tests for
    isolation and by config hot-swap paths.
    """
    global _bus_instance
    with _bus_lock:
        old = _bus_instance
        if old is not None:
            try:
                old.close()
            except Exception:
                logger.warning("failed to close previous event bus on reset", exc_info=True)
        _bus_instance = EventBus(config=config if config is not None else (old.config if old else None))
    try:
        from .lifecycle_observer import _resubscribe_all

        _resubscribe_all()
    except Exception:
        logger.debug("failed to resubscribe lifecycle observers after bus reset", exc_info=True)
