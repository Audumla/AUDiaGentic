"""Event bus implementation for in-process event dispatch.

Implements EventBusProtocol with SYNC/ASYNC dispatch, wildcard pattern matching,
subscriber isolation, and cycle detection.

MQ Migration: This implementation can be replaced with ExternalMQBus that
implements the same EventBusProtocol interface.
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .envelope import EventEnvelope
from .exceptions import CycleDetectedError
from .queue import AsyncQueue

logger = logging.getLogger(__name__)


class DeliveryMode(Enum):
    """Event delivery mode."""

    SYNC = "sync"  # Blocking, immediate
    ASYNC = "async"  # Non-blocking, queued


@dataclass
class SubscriptionHandle:
    """Handle for unsubscribing from events."""

    pattern: str
    handler: Callable[[str, dict[str, Any], dict[str, Any]], None]
    _id: int = field(default_factory=lambda: id(SubscriptionHandle))

    def __hash__(self) -> int:
        return hash(self._id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SubscriptionHandle):
            return False
        return self._id == other._id


class EventBusProtocol(ABC):
    """Abstract protocol for event bus implementations.

    This interface allows swapping between in-process and external MQ transports.
    """

    @abstractmethod
    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        """Publish an event to all matching subscribers.

        Args:
            event_type: Event type string (e.g., "planning.item.state.changed")
            payload: User-provided payload dict
            metadata: Optional metadata dict
            mode: Delivery mode (SYNC or ASYNC)
        """
        pass

    @abstractmethod
    def subscribe(
        self,
        pattern: str,
        handler: Callable[[str, dict[str, Any], dict[str, Any]], None],
    ) -> SubscriptionHandle:
        """Subscribe to events matching a pattern.

        Args:
            pattern: Event type pattern (supports * and ** wildcards)
            handler: Callback function(event_type, payload, metadata)

        Returns:
            SubscriptionHandle for unsubscribing
        """
        pass

    @abstractmethod
    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Unsubscribe from events.

        Args:
            handle: SubscriptionHandle from subscribe()
        """
        pass


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
        from audiagentic.interoperability import get_bus
        bus = get_bus()
    """

    def __init__(
        self,
        source_component: str = "default",
        max_depth: int = 10,
        async_executor: ThreadPoolExecutor | None = None,
        async_queue: AsyncQueue | None = None,
    ) -> None:
        """Initialize the event bus.

        Args:
            source_component: Default source component name for events
            max_depth: Maximum propagation depth before cycle detection
            async_executor: Optional ThreadPoolExecutor for ASYNC mode
            async_queue: Optional AsyncQueue for ASYNC mode (singleton by default)
        """
        self._source_component = source_component
        self._max_depth = max_depth
        self._async_executor = async_executor or ThreadPoolExecutor(max_workers=4)
        self._async_queue = async_queue or AsyncQueue.get_instance()

        # Subscription registry: pattern -> list of SubscriptionHandle
        self._subscriptions: dict[str, list[SubscriptionHandle]] = {}
        self._subscription_lock = threading.Lock()

        # Cycle detection: track correlation_id chains
        self._correlation_chains: dict[str, set[str]] = {}
        self._chain_lock = threading.Lock()

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        mode: DeliveryMode = DeliveryMode.SYNC,
    ) -> None:
        """Publish an event to all matching subscribers.

        Args:
            event_type: Event type string (e.g., "planning.item.state.changed")
            payload: User-provided payload dict
            metadata: Optional metadata dict
            mode: Delivery mode (SYNC or ASYNC)

        Raises:
            CycleDetectedError: If propagation_depth >= max_depth or correlation_id in chain
        """
        metadata = metadata or {}

        # Create envelope
        envelope = EventEnvelope(
            type=event_type,
            payload=payload,
            metadata=metadata,
            source_component=self._source_component,
        )

        # Cycle detection
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
        """Subscribe to events matching a pattern.

        Args:
            pattern: Event type pattern (supports * and ** wildcards)
            handler: Callback function(event_type, payload, metadata)

        Returns:
            SubscriptionHandle for unsubscribing
        """
        handle = SubscriptionHandle(pattern=pattern, handler=handler)

        with self._subscription_lock:
            if pattern not in self._subscriptions:
                self._subscriptions[pattern] = []
            self._subscriptions[pattern].append(handle)

        logger.debug("Subscribed to pattern: %s", pattern)
        return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Unsubscribe from events.

        Args:
            handle: SubscriptionHandle from subscribe()
        """
        with self._subscription_lock:
            if handle.pattern in self._subscriptions:
                self._subscriptions[handle.pattern] = [
                    h for h in self._subscriptions[handle.pattern] if h != handle
                ]

        logger.debug("Unsubscribed from pattern: %s", handle.pattern)

    def _dispatch_sync(self, envelope: EventEnvelope) -> None:
        """Dispatch event synchronously to all matching subscribers."""
        matching = self._find_matching_subscribers(envelope.type)

        for handle in matching:
            try:
                handle.handler(envelope.type, envelope.payload, envelope.metadata)
            except Exception as e:
                logger.error(
                    "Subscriber error for pattern %s: %s",
                    handle.pattern,
                    e,
                    exc_info=True,
                )

    def _dispatch_async(self, envelope: EventEnvelope) -> None:
        """Dispatch event asynchronously to all matching subscribers.

        Events are queued and processed by background worker thread.
        publish() returns immediately (<5ms target).
        """
        # Queue event for background processing
        self._async_queue.enqueue(
            event_type=envelope.type,
            payload=envelope.payload,
            metadata=envelope.metadata,
        )

        # Start queue if not running
        if not self._async_queue._running:
            self._async_queue.start()

    def _find_matching_subscribers(self, event_type: str) -> list[SubscriptionHandle]:
        """Find all subscribers matching the event type."""
        matching = []

        with self._subscription_lock:
            for pattern, handles in self._subscriptions.items():
                if self._pattern_matches(pattern, event_type):
                    matching.extend(handles)

        return matching

    def _pattern_matches(self, pattern: str, event_type: str) -> bool:
        """Check if event type matches pattern with wildcard support.

        Supports:
        - * matches exactly one segment (e.g., "planning.task.*" matches "planning.task.done")
        - ** matches zero or more segments (e.g., "planning.**" matches all planning events)

        Args:
            pattern: Pattern with wildcards
            event_type: Event type to match

        Returns:
            True if pattern matches event type
        """
        # Convert pattern to regex-friendly format
        # ** matches anything, * matches one segment
        parts = pattern.split(".")
        event_parts = event_type.split(".")

        if "**" in parts:
            # Multi-segment wildcard
            wildcard_idx = parts.index("**")
            prefix = parts[:wildcard_idx]
            suffix = parts[wildcard_idx + 1 :]

            # Check prefix matches
            if len(event_parts) < len(prefix) + len(suffix):
                return False

            if event_parts[: len(prefix)] != prefix:
                return False

            if suffix and event_parts[-len(suffix) :] != suffix:
                return False

            return True
        else:
            # Single-segment wildcard only
            if len(parts) != len(event_parts):
                return False

            for p, e in zip(parts, event_parts):
                if p != "*" and p != e:
                    return False

            return True

    def _check_cycle(self, envelope: EventEnvelope) -> None:
        """Check for cycles in event propagation.

        Raises:
            CycleDetectedError: If propagation_depth >= max_depth or correlation_id in chain
        """
        # Check propagation depth
        if envelope.propagation_depth >= self._max_depth:
            raise CycleDetectedError(
                f"Propagation depth exceeded ({envelope.propagation_depth} >= {self._max_depth})",
                event_id=envelope.id,
                propagation_depth=envelope.propagation_depth,
            )

        # Check correlation_id chain
        if envelope.correlation_id:
            with self._chain_lock:
                if envelope.correlation_id not in self._correlation_chains:
                    self._correlation_chains[envelope.correlation_id] = set()

                if envelope.id in self._correlation_chains[envelope.correlation_id]:
                    raise CycleDetectedError(
                        f"Cycle detected for correlation_id {envelope.correlation_id}",
                        event_id=envelope.id,
                        correlation_id=envelope.correlation_id,
                    )

                self._correlation_chains[envelope.correlation_id].add(envelope.id)

    def close(self) -> None:
        """Close the event bus and cleanup resources."""
        self._async_executor.shutdown(wait=True)
