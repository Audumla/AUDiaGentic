"""Atomic owner publication for explicitly started managed services."""
from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from audiagentic.foundation.system.managed_process import (
    ProcessIdentity,
    observe_process,
    ownership_matches,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import (
    EndpointInfo,
    ManagedServiceRecord,
    ProcessEvidence,
    conflict_error,
    prepare_restart_record,
    validate_facts,
)


class ManagedServiceOwner:
    """Publish or retire the proven process that owns one service record."""

    def __init__(
        self,
        store: ManagedServiceStore,
        *,
        observe: Callable[[ProcessEvidence], ProcessIdentity | None] = observe_process,
    ) -> None:
        self.store = store
        self.observe = observe

    def claim(
        self,
        *,
        protocol_version: str,
        endpoint: EndpointInfo,
        evidence_factory: Callable[[str], ProcessEvidence],
        health_facts: Mapping[str, Any] | None = None,
    ) -> ManagedServiceRecord:
        safe_facts = validate_facts(health_facts, "health facts")
        with self.store._lock():
            if self.store.record_path.exists():
                current = self.store._read_unlocked()
                self._reject_live_owner(current)
                starting = prepare_restart_record(
                    current,
                    owner_epoch=uuid.uuid4().hex,
                    protocol_version=protocol_version,
                    updated_at=self.store._clock(),
                )
                starting = self.store._write_unlocked(starting, "service.owner-claim-requested")
            else:
                starting = self.store._create_unlocked(protocol_version)
            evidence = evidence_factory(starting.owner_epoch)
            if evidence.owner_epoch != starting.owner_epoch:
                raise conflict_error(16, "owner evidence has the wrong service epoch")
            if not ownership_matches(evidence, self._observe(evidence)):
                raise conflict_error(28, "service owner process cannot be proven", pid=evidence.pid)
            running = replace(
                starting,
                state="running",
                revision=starting.revision + 1,
                updated_at=self.store._clock(),
                process=evidence,
                endpoint=endpoint,
                health_facts=safe_facts,
            )
            return self.store._write_unlocked(running, "service.owner-claimed")

    def _reject_live_owner(self, record: ManagedServiceRecord) -> None:
        if record.process is None:
            return
        observed = self._observe(record.process)
        if observed is None:
            return
        if ownership_matches(record.process, observed):
            raise conflict_error(34, "managed service already has a live owner", pid=record.process.pid)
        raise conflict_error(28, "existing service process ownership cannot be proven", pid=record.process.pid)

    def retire(self, *, expected_epoch: str) -> ManagedServiceRecord:
        with self.store._lock():
            current = self.store._read_unlocked()
            self.store._check_epoch(current, expected_epoch)
            if current.state not in ("running", "draining"):
                raise conflict_error(31, "service owner must be running or draining to retire", state=current.state)
            if current.active_lease_count:
                raise conflict_error(35, "managed service still has active client leases")
            if current.process is None or not ownership_matches(
                current.process, self._observe(current.process)
            ):
                raise conflict_error(28, "service owner process cannot be proven")
            stopping = replace(
                current,
                state="stopping",
                revision=current.revision + 1,
                updated_at=self.store._clock(),
            )
            stopping = self.store._write_unlocked(stopping, "service.owner-retiring")
            stopped = replace(
                stopping,
                state="stopped",
                revision=stopping.revision + 1,
                updated_at=self.store._clock(),
                process=None,
                health_facts=None,
            )
            return self.store._write_unlocked(stopped, "service.owner-retired")

    def _observe(self, evidence: ProcessEvidence) -> ProcessIdentity | None:
        try:
            return self.observe(evidence)
        except Exception as exc:
            raise conflict_error(33, "managed-service process observation failed") from exc


__all__ = ["ManagedServiceOwner"]
