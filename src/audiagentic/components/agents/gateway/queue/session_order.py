"""Admission-order fence before concurrent session worker preparation."""
import threading
from collections import deque
from collections.abc import Callable


class SessionDispatchOrder:
    """Serialize explicit session runners without reserving provider capacity."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._queues: dict[tuple[str, str], deque[str]] = {}
        self._keys: dict[str, tuple[str, str]] = {}

    def register(self, request_id: str, project: str, session: str | None) -> None:
        if session is None:
            return
        with self._condition:
            if request_id in self._keys:
                return  # Recovery retries keep their original position.
            key = (project, session)
            self._keys[request_id] = key
            self._queues.setdefault(key, deque()).append(request_id)
            self._condition.notify_all()

    def is_head(self, request_id: str, *, required: bool = True) -> bool:
        with self._condition:
            key = self._keys.get(request_id)
            return not required if key is None else self._queues[key][0] == request_id

    def wait(self, request_id: str, stopped: Callable[[], bool], *, required: bool = True) -> bool:
        while True:
            # Durable cancellation reads must never run under this condition.
            if stopped():
                return False
            with self._condition:
                key = self._keys.get(request_id)
                if key is None:
                    return not required
                if self._queues[key][0] == request_id:
                    return True
                self._condition.wait(.1)

    def complete(self, request_id: str) -> None:
        with self._condition:
            key = self._keys.pop(request_id, None)
            if key is not None:
                queue = self._queues[key]
                queue.remove(request_id)
                if not queue:
                    del self._queues[key]
                self._condition.notify_all()
