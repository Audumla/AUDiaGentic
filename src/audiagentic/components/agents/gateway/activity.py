"""Thread-safe, source-local request activity relay.

Provider transports can emit observations from a worker thread while the
gateway owns the durable request record.  This relay coalesces those signals;
the store allocates the aggregate sequence under the request lock.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from audiagentic.components.agents.gateway import store
from audiagentic.foundation.transports.agent_session import is_meaningful_activity


class RequestActivityRelay:
    def __init__(
        self,
        project_root: Path,
        request_id: str,
        *,
        owner_epoch: str,
        worker_id: str,
        attempt_epoch: int,
        provider_capability: str = "unknown",
        lease_seconds: float = 300.0,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.project_root = project_root
        self.request_id = request_id
        self.owner_epoch = owner_epoch
        self.worker_id = worker_id
        self.attempt_epoch = attempt_epoch
        self.provider_capability = provider_capability
        self.lease_seconds = lease_seconds
        self.min_interval_seconds = min_interval_seconds
        self._lock = threading.Lock()
        self._last_flush = 0.0
        self._last_source: dict[str, tuple[str | None, int | None]] = {}

    def observe_provider(
        self,
        *,
        source: str = "session-transport",
        source_instance: str | None = None,
        source_sequence: int | None = None,
        phase: str | None = None,
        force: bool = False,
    ) -> None:
        # Only actual provider work renews the gateway lease.  Heartbeats and
        # contextual flags remain useful ownership evidence, but cannot mask
        # a stalled provider turn.
        if not is_meaningful_activity(source, phase):
            return
        self._observe("provider", source, source_instance, source_sequence, phase, force)

    def observe_owner(
        self,
        *,
        source: str,
        source_instance: str | None = None,
        source_sequence: int | None = None,
        force: bool = False,
    ) -> None:
        self._observe("owner-heartbeat", source, source_instance, source_sequence, None, force)

    def flush(self, *, force: bool = True) -> None:
        # Observations are persisted as they arrive; flush exists to make the
        # terminal producer's ordering explicit and is intentionally a no-op.
        return None

    def _observe(
        self,
        kind: str,
        source: str,
        source_instance: str | None,
        source_sequence: int | None,
        phase: str | None,
        force: bool,
    ) -> None:
        with self._lock:
            key = kind
            previous = self._last_source.get(key)
            if (
                source_sequence is not None
                and previous is not None
                and previous[0] == source_instance
                and source_sequence <= int(previous[1] or 0)
            ):
                return
            now = time.monotonic()
            phase_changed = kind == "provider" and getattr(self, "_last_phase", None) != phase
            if not force and not phase_changed and now - self._last_flush < self.min_interval_seconds:
                if source_sequence is not None:
                    self._last_source[key] = (source_instance, source_sequence)
                return
            try:
                store.record_owned_activity(
                    self.project_root,
                    self.request_id,
                    owner_epoch=self.owner_epoch,
                    worker_id=self.worker_id,
                    attempt_epoch=self.attempt_epoch,
                    kind=kind,
                    source=source,
                    source_instance=source_instance,
                    source_sequence=source_sequence,
                    phase=phase,
                    provider_capability=self.provider_capability,
                    activity_lease_seconds=self.lease_seconds,
                )
            except Exception:
                # Activity is advisory and cannot turn a provider response
                # into a request failure (fencing/terminal races are normal).
                return
            self._last_flush = now
            self._last_source[key] = (source_instance, source_sequence)
            if kind == "provider":
                self._last_phase = phase


__all__ = ["RequestActivityRelay"]
