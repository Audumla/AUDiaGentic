"""Drain and guarded shutdown coordination for managed services."""
from __future__ import annotations

import time
from dataclasses import replace

from audiagentic.foundation.system.managed_process import ProcessIdentity, ownership_matches
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import (
    ManagedServiceRecord,
    ProcessEvidence,
    conflict_error,
    normalize_lease_history,
    validation_error,
)
from audiagentic.foundation.system.managed_service_lifecycle_contracts import (
    ManagedServiceHooks,
    StopOutcome,
    StopResult,
)


class ManagedServiceShutdown:
    """Stop only after lease, quiescence, epoch, and ownership gates pass."""

    def __init__(self, store: ManagedServiceStore, hooks: ManagedServiceHooks) -> None:
        self.store = store
        self.hooks = hooks

    def request_drain(
        self, *, expected_revision: int, expected_epoch: str
    ) -> ManagedServiceRecord:
        return self.store.transition(
            "draining",
            expected_revision=expected_revision,
            expected_epoch=expected_epoch,
        )

    def stop_if_quiescent(
        self,
        *,
        expected_epoch: str,
        graceful_timeout: float = 5.0,
        force_timeout: float = 2.0,
    ) -> StopResult:
        if graceful_timeout <= 0 or force_timeout <= 0:
            raise validation_error(30, "stop timeouts must be positive")
        with self.store._lock():
            record = self.store._read_unlocked()
            self.store._check_epoch(record, expected_epoch)
            record = self._expire_due_unlocked(record)
            if record.active_lease_count:
                return StopResult(record, "active-leases")
            if record.state != "draining":
                raise conflict_error(
                    31, "service must be draining before guarded stop", state=record.state
                )
            try:
                quiescent = self.hooks.quiescent(record)
            except Exception:  # noqa: BLE001 - safe degraded result
                return StopResult(record, "quiescence-unavailable")
            if not quiescent:
                return StopResult(record, "not-quiescent")
            if record.process is None:
                raise conflict_error(32, "draining service has no process evidence")
            observed = self._observe(record.process)
            if not ownership_matches(record.process, observed):
                return StopResult(record, "ownership-unverified")
            stopping = replace(
                record,
                state="stopping",
                revision=record.revision + 1,
                updated_at=self.store._clock(),
            )
            stopping = self.store._write_unlocked(stopping, "service.stop-requested")

        try:
            self.hooks.request_stop(stopping)
        except Exception:  # noqa: BLE001 - bounded force path remains available
            pass
        if self._wait_dead(stopping.process, graceful_timeout):
            return self._finish_stopped(stopping, forced=False)
        observed = self._observe(stopping.process)
        if not ownership_matches(stopping.process, observed):
            return self._finish_failed(stopping, "ownership-changed", "ownership-unverified")
        try:
            self.hooks.signal(stopping.process, observed, force=True)
        except Exception:  # noqa: BLE001 - persist a safe classified outcome
            return self._finish_failed(stopping, "stop-signal-failed", "stop-failed")
        if self._wait_dead(stopping.process, force_timeout):
            return self._finish_stopped(stopping, forced=True)
        return self._finish_failed(stopping, "stop-timeout", "stop-timeout", forced=True)

    def _expire_due_unlocked(self, record: ManagedServiceRecord) -> ManagedServiceRecord:
        timestamp = self.store._clock()
        leases, changed = normalize_lease_history(record.leases, current_time=timestamp)
        if not changed:
            return record
        expired = replace(
            record, revision=record.revision + 1, updated_at=timestamp, leases=leases
        )
        return self.store._write_unlocked(expired, "lease.expired")

    def _wait_dead(self, evidence: ProcessEvidence, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._observe(evidence) is None:
                return True
            time.sleep(min(0.05, timeout))
        return self._observe(evidence) is None

    def _observe(self, evidence: ProcessEvidence) -> ProcessIdentity | None:
        try:
            return self.hooks.observe(evidence)
        except Exception as exc:
            raise conflict_error(33, "managed-service process observation failed") from exc

    def _finish_stopped(
        self, stopping: ManagedServiceRecord, *, forced: bool
    ) -> StopResult:
        with self.store._lock():
            current = self.store._read_unlocked()
            self.store._check_epoch(current, stopping.owner_epoch)
            stopped = replace(
                current,
                state="stopped",
                revision=current.revision + 1,
                updated_at=self.store._clock(),
                process=None,
                health_facts=None,
            )
            stopped = self.store._write_unlocked(stopped, "service.stopped")
            return StopResult(stopped, "stopped", forced=forced)

    def _finish_failed(
        self,
        stopping: ManagedServiceRecord,
        failure_class: str,
        outcome: StopOutcome,
        *,
        forced: bool = False,
    ) -> StopResult:
        with self.store._lock():
            current = self.store._read_unlocked()
            self.store._check_epoch(current, stopping.owner_epoch)
            failed = replace(
                current,
                state="failed",
                revision=current.revision + 1,
                updated_at=self.store._clock(),
                failure={"failure-class": failure_class},
            )
            failed = self.store._write_unlocked(failed, "service.stop-failed")
            return StopResult(failed, outcome, forced=forced)


__all__ = ["ManagedServiceShutdown"]
