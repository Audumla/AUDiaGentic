"""Dispatch readiness per provider surface, owned by the gateway service.

Service liveness (port answers, lease renewed) is not dispatch readiness: a gateway whose runtime lacks a
module a provider surface imports is alive and cannot run that provider's work. This registry holds the
readiness the gateway itself established, so admission can refuse work for an unavailable surface up front
(with the cause) instead of queueing it to fail minutes later, and so doctor/MCP/dashboard read one source.

Only facts the process can prove are recorded here. An unprobed surface is ``unknown`` and is admitted: a
watchdog or canary may later mark it degraded, but silence is never turned into a refusal.
"""
from __future__ import annotations

import importlib.util
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

# Modules a provider surface imports inside the GATEWAY's interpreter. A missing one surfaces at attach time
# as "CDP endpoint did not become ready", which reads as a browser fault.
SURFACE_IMPORTS: dict[str, tuple[str, ...]] = {"gpt-auto-cdp": ("websockets",)}

AVAILABLE, UNAVAILABLE, UNKNOWN, SUSPECTED = "available", "unavailable", "unknown", "suspected"
QUEUE = "dispatch-queue"  # the pseudo-surface the queue watchdog reports on; suspicion never refuses admission


@dataclass(frozen=True)
class SurfaceHealth:
    surface_id: str
    status: str
    reason_code: str
    detail: str
    since: str


class DispatchHealth:
    def __init__(self, finder: Callable[[str], object | None] = importlib.util.find_spec,
                 on_change: Callable[[SurfaceHealth], None] | None = None) -> None:
        self._finder = finder
        self._on_change = on_change
        self._lock = threading.Lock()
        self._surfaces: dict[str, SurfaceHealth] = {}

    def refresh_dependencies(self) -> None:
        """Re-check every surface's required modules in this interpreter; record transitions only."""
        for surface, modules in SURFACE_IMPORTS.items():
            missing = [name for name in modules if self._finder(name) is None]
            if missing:
                self._set(surface, UNAVAILABLE, "dependency-missing",
                          f"the gateway runtime lacks {', '.join(missing)}; install a runtime with the provider extras "
                          "(audiagentic runtime install ref origin/main restart yes)")
            else:
                self._set(surface, AVAILABLE, "dependencies-present", "required modules are importable")

    def set_listener(self, on_change: Callable[[SurfaceHealth], None] | None) -> None:
        self._on_change = on_change

    def _set(self, surface: str, status: str, reason: str, detail: str) -> None:
        with self._lock:
            current = self._surfaces.get(surface)
            if current is not None and (current.status, current.reason_code) == (status, reason):
                return
            changed = SurfaceHealth(surface, status, reason, detail, now_iso_z())
            self._surfaces[surface] = changed
        if self._on_change is not None:
            try:
                self._on_change(changed)  # outside the lock; a failing subscriber never breaks health
            except Exception:  # noqa: BLE001
                pass

    def observe_queue(self, findings: list[Any]) -> None:
        """Record the queue watchdog's verdict. Suspicion warns; only a proven fault refuses work."""
        if findings:
            worst = max(findings, key=lambda f: f.age_seconds)
            self._set(QUEUE, SUSPECTED, worst.code, f"{len(findings)} request(s) suspected stuck; {worst.request_id}: {worst.detail}")
        else:
            self._set(QUEUE, AVAILABLE, "no-stall", "no request is stalled in admission or start")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            surfaces = {key: asdict(value) for key, value in sorted(self._surfaces.items())}
        degraded = [key for key, value in surfaces.items() if value["status"] == UNAVAILABLE]
        suspected = [key for key, value in surfaces.items() if value["status"] == SUSPECTED]
        return {"surfaces": surfaces, "degraded": degraded, "suspected": suspected, "ready": not degraded}

    def require_available(self, surface_id: str) -> None:
        with self._lock:
            state = self._surfaces.get(surface_id)
        if state is not None and state.status == UNAVAILABLE:
            raise AudiaGenticError(
                code="RES-AGW-154", kind="agents",
                message=f"provider surface {surface_id} is unavailable: {state.detail}",
                details={"surface_id": surface_id, "reason_code": state.reason_code, "since": state.since},
            )


_HEALTH = DispatchHealth()


def get_dispatch_health() -> DispatchHealth:
    return _HEALTH
