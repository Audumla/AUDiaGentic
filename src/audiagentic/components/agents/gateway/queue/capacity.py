"""Source-capacity authority for the gateway scheduler (AS101).

The scheduler owns pending-work selection; this module owns only a bounded
source reservation once a candidate has been selected.  Keeping mutable
resource state here gives later pending-authority work one stable seam.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapacityReservation:
    """An idempotently releasable reservation for one declared source."""

    source_id: str
    resource_id: str | None
    model_id: str | None
    capacity_source_id: str
    declared: bool
    concurrency: int | None


class _ResourceCapacity:
    """Capacity and drain-before-swap state for one physical resource."""

    def __init__(self, *, clock: Callable[[], float], starvation_seconds: float) -> None:
        self._clock = clock
        self._starvation_seconds = starvation_seconds
        self._lock = threading.Lock()
        self._active_source_id: str | None = None
        self._in_flight: dict[str, int] = {}
        self._waiting_since: dict[str, float] = {}

    def try_reserve(self, source_id: str, concurrency: int) -> bool:
        now = self._clock()
        with self._lock:
            if self._active_source_id in (None, source_id):
                blocked_by_waiter = any(
                    waiting_source != source_id
                    and now - since >= self._starvation_seconds
                    for waiting_source, since in self._waiting_since.items()
                )
                if blocked_by_waiter:
                    self._waiting_since.setdefault(source_id, now)
                    return False
                current = self._in_flight.get(source_id, 0)
                if current >= concurrency:
                    self._waiting_since.setdefault(source_id, now)
                    return False
                self._active_source_id = source_id
                self._in_flight[source_id] = current + 1
                self._waiting_since.pop(source_id, None)
                return True

            active_in_flight = self._in_flight.get(self._active_source_id, 0)
            if active_in_flight == 0:
                self._active_source_id = source_id
                self._in_flight[source_id] = 1
                self._waiting_since.pop(source_id, None)
                return True
            self._waiting_since.setdefault(source_id, now)
            return False

    def release(self, source_id: str) -> None:
        with self._lock:
            current = self._in_flight.get(source_id, 0)
            if current > 0:
                self._in_flight[source_id] = current - 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active-source-id": self._active_source_id,
                "in-flight": dict(self._in_flight),
            }


class SourceCapacityAuthority:
    """The sole mutable authority for declared, shared source capacity."""

    def __init__(self, *, clock: Callable[[], float] | None = None, starvation_seconds: float = 30.0) -> None:
        self._clock = clock or time.monotonic
        self._starvation_seconds = starvation_seconds
        self._lock = threading.Lock()
        self._available = threading.Condition()
        self._resources: dict[str, _ResourceCapacity] = {}

    def try_reserve(
        self,
        *,
        source_id: str,
        resource_id: str | None,
        concurrency: int | None,
        model_id: str | None,
        capacity_source_id: str | None = None,
        declared: bool = True,
    ) -> CapacityReservation | None:
        if not source_id:
            raise ValueError("source capacity identity is invalid")
        # A source without a resource declaration is intentionally unbounded.
        # It still receives a reservation so placement has one provider-neutral
        # contract rather than a legacy semaphore branch.
        if resource_id is None and concurrency is None:
            return CapacityReservation(source_id, None, model_id, source_id, False, None)
        if not resource_id or concurrency is None or concurrency < 1:
            raise ValueError("declared source capacity is invalid")
        with self._lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                resource = _ResourceCapacity(clock=self._clock, starvation_seconds=self._starvation_seconds)
                self._resources[resource_id] = resource
        capacity_key = capacity_source_id or source_id
        if not resource.try_reserve(capacity_key, concurrency):
            return None
        return CapacityReservation(
            source_id, resource_id, model_id, capacity_key, declared, concurrency,
        )

    def reserve_when_available(self, template: CapacityReservation) -> CapacityReservation:
        """Block only on capacity availability, never on provider work."""
        while True:
            reservation = self.try_reserve(
                source_id=template.source_id,
                resource_id=template.resource_id,
                concurrency=template.concurrency,
                model_id=template.model_id,
                capacity_source_id=template.capacity_source_id,
                declared=template.declared,
            )
            if reservation is not None:
                return reservation
            with self._available:
                self._available.wait(timeout=0.1)

    def release(self, reservation: CapacityReservation) -> None:
        if reservation.resource_id is None:
            return
        with self._lock:
            resource = self._resources.get(reservation.resource_id)
        if resource is not None:
            resource.release(reservation.capacity_source_id)
        with self._available:
            self._available.notify_all()

    def snapshot(self, resource_id: str) -> dict[str, Any]:
        with self._lock:
            resource = self._resources.get(resource_id)
        return resource.snapshot() if resource is not None else {
            "active-source-id": None, "in-flight": {},
        }


__all__ = ["CapacityReservation", "SourceCapacityAuthority"]
