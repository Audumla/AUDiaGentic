"""Deterministic pending-work authority for gateway scheduling (AS101).

This component owns the pending request index, canonical project queues and
fair project rotation.  It intentionally does not know capacity policy or
request lifecycle; a caller supplies an eligibility predicate at claim time.
"""

from __future__ import annotations

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


class PendingAuthority(Generic[T]):
    """One-lock pending index with per-project FIFO and fair rotation."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._by_project: dict[str, deque[PendingRequest[T]]] = {}
        self._by_request: dict[str, PendingRequest[T]] = {}
        self._rotation: deque[str] = deque()

    def enqueue(self, *, request_id: str, project_key: str, value: T) -> None:
        if not request_id or not project_key:
            raise ValueError("pending request identity is invalid")
        with self._condition:
            if request_id in self._by_request:
                raise ValueError(f"request is already pending: {request_id}")
            request = PendingRequest(request_id, project_key, value)
            queue = self._by_project.setdefault(project_key, deque())
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
        """Claim one eligible project head, rotating the winning project.

        Only each project's FIFO head is considered.  A blocked head therefore
        cannot be bypassed by later work from that same project, while another
        project may make progress.  The caller must keep ``eligible`` free of
        I/O and side effects because it runs under this authority's lock.
        """
        with self._condition:
            for project_key in tuple(self._rotation):
                queue = self._by_project.get(project_key)
                if not queue:
                    continue
                candidate = queue[0]
                if not eligible(candidate):
                    continue
                queue.popleft()
                del self._by_request[candidate.request_id]
                self._drop_empty_project(project_key)
                if project_key in self._rotation:
                    self._rotation.remove(project_key)
                    self._rotation.append(project_key)
                self._condition.notify_all()
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
        """Return project FIFO heads in the current fair rotation order."""
        with self._condition:
            return tuple(
                queue[0] for project in self._rotation
                if (queue := self._by_project.get(project))
            )

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
        with self._condition:
            return {project: len(queue) for project, queue in self._by_project.items()}

    def wait_for_change(self, timeout: float | None = None) -> None:
        """Wait for an enqueue/cancel/claim signal without polling."""
        with self._condition:
            self._condition.wait(timeout)

    def _drop_empty_project(self, project_key: str) -> None:
        if self._by_project.get(project_key):
            return
        self._by_project.pop(project_key, None)
        try:
            self._rotation.remove(project_key)
        except ValueError:
            pass

    def _remove_locked(self, request_id: str, *, rotate: bool) -> PendingRequest[T] | None:
        request = self._by_request.pop(request_id, None)
        if request is None:
            return None
        queue = self._by_project[request.project_key]
        queue.remove(request)
        self._drop_empty_project(request.project_key)
        if rotate and request.project_key in self._rotation:
            self._rotation.remove(request.project_key)
            self._rotation.append(request.project_key)
        self._condition.notify_all()
        return request


__all__ = ["PendingAuthority", "PendingRequest"]
