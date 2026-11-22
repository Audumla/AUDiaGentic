"""Process-wide holds on admitting new work to one capacity source.

A hold says "this provider source is limited right now: queue new work, keep what is already running".
The provider that can see the limit sets it and lifts it; the gateway queue only asks. The registry knows
nothing about any provider, so any source id can be held for any stated reason.
"""
from __future__ import annotations

import threading
import weakref
from collections.abc import Callable
from dataclasses import asdict, dataclass

from audiagentic.foundation.time import now_iso_z


@dataclass(frozen=True)
class AdmissionHold:
    source_id: str
    reason: str
    since: str
    detail: str = ""
    next_check_at: str | None = None


class AdmissionHolds:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._holds: dict[str, AdmissionHold] = {}
        self._listeners: list[weakref.WeakMethod] = []

    def hold(self, source_id: str, reason: str, detail: str = "", next_check_at: str | None = None) -> bool:
        """Place or refresh a hold; True when this created it (the source was not held before)."""
        with self._lock:
            current = self._holds.get(source_id)
            since = current.since if current is not None else now_iso_z()
            self._holds[source_id] = AdmissionHold(source_id, reason, since, detail, next_check_at)
            return current is None

    def on_lift(self, callback: Callable[[str], None]) -> None:
        """Call a bound method when a hold is lifted (weakly held, so a dropped owner is forgotten)."""
        with self._lock:
            self._listeners.append(weakref.WeakMethod(callback))

    def lift(self, source_id: str) -> bool:
        """Remove a hold; True when one existed. Listeners run outside the lock; a failing one is ignored."""
        with self._lock:
            existed = self._holds.pop(source_id, None) is not None
            listeners = [method() for method in self._listeners]
            self._listeners = [m for m in self._listeners if m() is not None]
        if existed:
            for listener in listeners:
                if listener is not None:
                    try:
                        listener(source_id)
                    except Exception:  # noqa: BLE001 - a subscriber must never break lifting
                        pass
        return existed

    def get(self, source_id: str) -> AdmissionHold | None:
        with self._lock:
            return self._holds.get(source_id)

    def snapshot(self) -> dict[str, dict[str, str | None]]:
        with self._lock:
            return {key: asdict(value) for key, value in sorted(self._holds.items())}


_HOLDS = AdmissionHolds()


def get_admission_holds() -> AdmissionHolds:
    return _HOLDS
