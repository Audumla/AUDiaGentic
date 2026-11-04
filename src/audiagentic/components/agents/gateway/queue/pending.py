"""Deterministic pending-work authority for gateway scheduling (AS101).

This component owns the pending request index, per-lane FIFO queues and fair
project rotation.  A lane defaults to the request's project; a caller may name a
finer lane (one profile definition within a project) so that a blocked head in one
lane never holds back requests of another lane in the same project.  Projects are
still served in fair rotation, and within a project the oldest eligible lane head
goes first.  It intentionally does not know capacity policy or request lifecycle;
a caller supplies an eligibility predicate at claim time.
"""

from __future__ import annotations

import itertools
import threading
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True)
class PendingRequest(Generic[T]):
    request_id: str
    project_key: str
    value: T
    lane: Hashable | None = None
    sequence: int = 0

    @property
    def lane_key(self) -> Hashable:
        """The FIFO lane: a structured key a caller chose, otherwise the project itself."""
        return self.project_key if self.lane is None else self.lane


class PendingAuthority(Generic[T]):
    """One-lock pending index with per-lane FIFO and fair project rotation."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._by_lane: dict[Hashable, deque[PendingRequest[T]]] = {}
        self._lanes_of_project: dict[str, list[Hashable]] = {}
        self._by_request: dict[str, PendingRequest[T]] = {}
        self._rotation: deque[str] = deque()
        self._sequence = itertools.count(1)

    def enqueue(self, *, request_id: str, project_key: str, value: T, lane: Hashable | None = None) -> None:
        if not request_id or not project_key:
            raise ValueError("pending request identity is invalid")
        with self._condition:
            if request_id in self._by_request:
                raise ValueError(f"request is already pending: {request_id}")
            request = PendingRequest(request_id, project_key, value, lane, next(self._sequence))
            queue = self._by_lane.get(request.lane_key)
            if queue is None:
                queue = self._by_lane[request.lane_key] = deque()
                self._lanes_of_project.setdefault(project_key, []).append(request.lane_key)
            queue.append(request)
            self._by_request[request_id] = request
            if project_key not in self._rotation:
                self._rotation.append(project_key)
            self._condition.notify_all()

    def remove(self, request_id: str) -> PendingRequest[T] | None:
        """Cancel an indexed waiter, retaining FIFO for every other request."""
        with self._condition:
            return self._remove_locked(request_id, rotate=False)

    def claim_next(self, eligible: Callable[[PendingRequest[T]], bool]) -> PendingRequest[T] | None:
        """Claim one eligible lane head, rotating the winning project.

        Only each lane's FIFO head is considered.  A blocked head therefore
        cannot be bypassed by later work from that same lane, while another
        project, or another lane of the same project, may make progress.  Within a
        project the oldest eligible lane head is claimed first.  The caller must
        keep ``eligible`` free of I/O and side effects because it runs under this
        authority's lock.
        """
        with self._condition:
            for project_key in tuple(self._rotation):
                for candidate in self._project_heads(project_key):
                    if not eligible(candidate):
                        continue
                    self._remove_locked(candidate.request_id, rotate=True)
                    return candidate
        return None

    def claim(self, request_id: str) -> PendingRequest[T] | None:
        """Atomically remove a specifically selected pending request."""
        with self._condition:
            return self._remove_locked(request_id, rotate=True)

    def contains(self, request_id: str) -> bool:
        with self._condition:
            return request_id in self._by_request

    def get(self, request_id: str) -> PendingRequest[T] | None:
        with self._condition:
            return self._by_request.get(request_id)

    def candidates(self) -> tuple[PendingRequest[T], ...]:
        """Return lane FIFO heads, projects in fair rotation order and each project's oldest head first."""
        with self._condition:
            return tuple(head for project in self._rotation for head in self._project_heads(project))

    def count(self, predicate: Callable[[PendingRequest[T]], bool]) -> int:
        with self._condition:
            return sum(1 for request in self._by_request.values() if predicate(request))

    def count_by(self, key: Callable[[PendingRequest[T]], K]) -> dict[K, int]:
        with self._condition:
            counts: dict[K, int] = {}
            for request in self._by_request.values():
                value = key(request)
                counts[value] = counts.get(value, 0) + 1
            return counts

    def depths(self) -> dict[str, int]:
        """Pending requests per project, whatever lanes they wait in."""
        return self.count_by(lambda request: request.project_key)

    def wait_for_change(self, timeout: float | None = None) -> None:
        """Wait for an enqueue/cancel/claim signal without polling."""
        with self._condition:
            self._condition.wait(timeout)

    def _project_heads(self, project_key: str) -> list[PendingRequest[T]]:
        heads = [queue[0] for lane in self._lanes_of_project.get(project_key, ()) if (queue := self._by_lane.get(lane))]
        return sorted(heads, key=lambda request: request.sequence)

    def _remove_locked(self, request_id: str, *, rotate: bool) -> PendingRequest[T] | None:
        request = self._by_request.pop(request_id, None)
        if request is None:
            return None
        queue = self._by_lane[request.lane_key]
        queue.remove(request)
        if not queue:
            del self._by_lane[request.lane_key]
            lanes = self._lanes_of_project[request.project_key]
            lanes.remove(request.lane_key)
            if not lanes:
                del self._lanes_of_project[request.project_key]
                self._rotation.remove(request.project_key)
        if rotate and request.project_key in self._rotation:
            self._rotation.remove(request.project_key)
            self._rotation.append(request.project_key)
        self._condition.notify_all()
        return request


__all__ = ["PendingAuthority", "PendingRequest"]
