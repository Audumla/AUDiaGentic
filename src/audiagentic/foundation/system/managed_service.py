"""Atomic managed-service store and lease coordination (PR06)."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, read_json_with_retry
from audiagentic.foundation.observability.timeline import record_timeline_event
from audiagentic.foundation.paths.home import global_service_runtime
from audiagentic.foundation.system.managed_service_contracts import (
    ClientLease,
    EndpointInfo,
    LeaseState,
    ManagedServiceRecord,
    ProcessEvidence,
    ServiceKey,
    ServiceState,
    add_seconds,
    conflict_error,
    normalize_lease_history,
    record_from_dict,
    record_to_dict,
    transition_engine,
    validate_facts,
    validate_id,
    validation_error,
)
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z


class ManagedServiceStore:
    """One service's atomic record, lifecycle transitions, and client leases."""

    def __init__(
        self,
        key: ServiceKey,
        *,
        root: Path | None = None,
        clock: Callable[[], str] = now_iso_z,
        lock_timeout: float = 30.0,
    ) -> None:
        self.key = key
        self.root = (root or global_service_runtime()) / key.scope / key.service_kind / key.service_id
        self.record_path = self.root / "service.json"
        self.lock_path = self.root / "start.lock"
        self.timeline_path = self.root / "timeline.ndjson"
        self._clock = clock
        self._lock_timeout = lock_timeout

    def _lock(self) -> StartupLock:
        return StartupLock(self.lock_path, timeout=self._lock_timeout)

    @property
    def lock_timeout(self) -> float:
        """Return the bounded cross-process lock wait used by lifecycle callers."""
        return self._lock_timeout

    def _read_unlocked(self) -> ManagedServiceRecord:
        if not self.record_path.exists():
            raise validation_error(10, "managed-service record not found", path=str(self.record_path))
        try:
            value = read_json_with_retry(self.record_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise validation_error(11, "managed-service record is unreadable", path=str(self.record_path)) from exc
        if not isinstance(value, dict):
            raise validation_error(11, "managed-service record must be a mapping", path=str(self.record_path))
        try:
            return record_from_dict(value)
        except AudiaGenticError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise validation_error(
                11, "managed-service record is invalid", path=str(self.record_path)
            ) from exc

    def read(self) -> ManagedServiceRecord:
        return self._read_unlocked()

    def _write_unlocked(
        self,
        record: ManagedServiceRecord,
        event: str,
        *,
        correlation_id: str | None = None,
    ) -> ManagedServiceRecord:
        atomic_write_json(self.record_path, record_to_dict(record))
        record_timeline_event(
            self.timeline_path, component="foundation", resource_kind="managed-service",
            resource_id=f"{self.key.service_kind}:{self.key.service_id}", event=event,
            state=record.state, attributes={"revision": record.revision, "owner_epoch": record.owner_epoch},
            correlation_id=correlation_id,
        )
        return record

    def create(self, *, protocol_version: str, owner_epoch: str | None = None) -> ManagedServiceRecord:
        if not protocol_version:
            raise validation_error(12, "protocol version is required")
        with self._lock():
            if self.record_path.exists():
                raise conflict_error(13, "managed-service record already exists", path=str(self.record_path))
            return self._create_unlocked(protocol_version, owner_epoch=owner_epoch)

    def _create_unlocked(
        self, protocol_version: str, *, owner_epoch: str | None = None
    ) -> ManagedServiceRecord:
        timestamp = self._clock()
        record = ManagedServiceRecord(
            key=self.key, state="starting", revision=1,
            owner_epoch=owner_epoch or uuid.uuid4().hex,
            created_at=timestamp, updated_at=timestamp, protocol_version=protocol_version,
        )
        return self._write_unlocked(record, "service.created")

    @staticmethod
    def _check_version(record: ManagedServiceRecord, revision: int, epoch: str) -> None:
        if record.revision != revision or record.owner_epoch != epoch:
            raise conflict_error(14, "stale managed-service writer", expected_revision=revision,
                                 actual_revision=record.revision, expected_epoch=epoch,
                                 actual_epoch=record.owner_epoch)

    def transition(
        self,
        new_state: ServiceState,
        *,
        expected_revision: int,
        expected_epoch: str,
        process: ProcessEvidence | None = None,
        endpoint: EndpointInfo | None = None,
        health_facts: Mapping[str, Any] | None = None,
        failure: Mapping[str, Any] | None = None,
        new_owner_epoch: str | None = None,
    ) -> ManagedServiceRecord:
        with self._lock():
            record = self._read_unlocked()
            self._check_version(record, expected_revision, expected_epoch)
            reason = transition_engine.check(record.state, new_state)
            if reason is not None:
                raise conflict_error(15, "illegal managed-service transition",
                                     current=record.state, target=new_state, reason=reason)
            epoch = new_owner_epoch or record.owner_epoch
            next_record = replace(
                record, state=new_state, revision=record.revision + 1, owner_epoch=epoch,
                updated_at=self._clock(), process=process if process is not None else record.process,
                endpoint=endpoint if endpoint is not None else record.endpoint,
                health_facts=validate_facts(health_facts, "health facts") if health_facts is not None else record.health_facts,
                failure=validate_facts(failure, "failure facts") if failure is not None else record.failure,
            )
            if next_record.process is not None and next_record.process.owner_epoch != epoch:
                raise conflict_error(16, "process evidence owner epoch does not match service epoch")
            return self._write_unlocked(next_record, "service.transitioned")

    def heartbeat(
        self,
        health_facts: Mapping[str, Any],
        *,
        expected_epoch: str,
    ) -> ManagedServiceRecord:
        """Refresh readiness/health facts without changing lifecycle state."""
        safe_facts = validate_facts(health_facts, "health facts")
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            if record.state not in ("running", "draining"):
                raise conflict_error(36, "service does not accept heartbeats", state=record.state)
            timestamp = self._clock()
            next_record = replace(
                record,
                revision=record.revision + 1,
                updated_at=timestamp,
                health_facts=safe_facts,
            )
            return self._write_unlocked(next_record, "service.heartbeat")

    def acquire_lease(
        self,
        client_instance_id: str,
        *,
        ttl_seconds: float,
        expected_epoch: str,
        correlation_id: str | None = None,
        facts: Mapping[str, Any] | None = None,
    ) -> tuple[ManagedServiceRecord, ClientLease]:
        validate_id(client_instance_id, "client-instance-id")
        if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise validation_error(17, "lease ttl must be positive", ttl_seconds=ttl_seconds)
        safe_facts = validate_facts(facts, "lease facts")
        with self._lock():
            record = self._read_unlocked()
            return self._acquire_lease_unlocked(
                record,
                client_instance_id,
                ttl_seconds=ttl_seconds,
                expected_epoch=expected_epoch,
                correlation_id=correlation_id,
                facts=safe_facts,
            )

    def _acquire_lease_unlocked(
        self,
        record: ManagedServiceRecord,
        client_instance_id: str,
        *,
        ttl_seconds: float,
        expected_epoch: str,
        correlation_id: str | None = None,
        facts: Mapping[str, Any] | None = None,
    ) -> tuple[ManagedServiceRecord, ClientLease]:
        self._check_epoch(record, expected_epoch)
        if record.state != "running":
            raise conflict_error(18, "service does not accept leases", state=record.state)
        timestamp = self._clock()
        leases, _ = normalize_lease_history(record.leases, current_time=timestamp)
        lease = ClientLease(
            lease_id=f"lease_{uuid.uuid4().hex[:16]}", client_instance_id=client_instance_id,
            owner_epoch=record.owner_epoch, state="active", acquired_at=timestamp,
            renewed_at=timestamp, expires_at=add_seconds(timestamp, ttl_seconds),
            correlation_id=correlation_id, facts=facts,
        )
        next_record = replace(record, revision=record.revision + 1, updated_at=timestamp,
                              leases=(*leases, lease))
        return self._write_unlocked(
            next_record, "lease.acquired", correlation_id=correlation_id
        ), lease

    def get_lease(self, lease_id: str) -> ClientLease:
        """Return one lease, including released or expired leases."""
        validate_id(lease_id, "lease-id")
        for lease in self.read().leases:
            if lease.lease_id == lease_id:
                return lease
        raise validation_error(20, "managed-service lease not found", lease_id=lease_id)

    def require_active_lease(
        self, lease_id: str, *, expected_epoch: str
    ) -> ClientLease:
        """Validate one current lease under the store lock before protected work."""
        validate_id(lease_id, "lease-id")
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            timestamp = self._clock()
            leases, changed = normalize_lease_history(
                record.leases, current_time=timestamp
            )
            match = next((lease for lease in leases if lease.lease_id == lease_id), None)
            if changed:
                record = self._write_unlocked(
                    replace(
                        record,
                        revision=record.revision + 1,
                        updated_at=timestamp,
                        leases=leases,
                    ),
                    "lease.expired",
                )
                match = next(
                    (lease for lease in record.leases if lease.lease_id == lease_id), None
                )
            if match is None:
                raise validation_error(
                    20, "managed-service lease not found", lease_id=lease_id
                )
            if not match.active or match.owner_epoch != expected_epoch:
                raise conflict_error(
                    19,
                    "managed-service lease is not active",
                    lease_id=lease_id,
                    state=match.state,
                )
            return match

    def renew_lease(self, lease_id: str, *, ttl_seconds: float, expected_epoch: str) -> ManagedServiceRecord:
        if isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
            raise validation_error(17, "lease ttl must be positive", ttl_seconds=ttl_seconds)
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            timestamp = self._clock()
            normalized, _ = normalize_lease_history(record.leases, current_time=timestamp)
            found = False
            leases: list[ClientLease] = []
            for lease in normalized:
                if lease.lease_id == lease_id:
                    if not lease.active or lease.owner_epoch != expected_epoch:
                        raise conflict_error(19, "lease is not renewable", lease_id=lease_id, state=lease.state)
                    lease = replace(lease, renewed_at=timestamp, expires_at=add_seconds(timestamp, ttl_seconds))
                    found = True
                leases.append(lease)
            if not found:
                raise validation_error(20, "managed-service lease not found", lease_id=lease_id)
            return self._write_unlocked(replace(record, revision=record.revision + 1,
                                                updated_at=timestamp, leases=tuple(leases)), "lease.renewed")

    @staticmethod
    def _check_epoch(record: ManagedServiceRecord, expected_epoch: str) -> None:
        if record.owner_epoch != expected_epoch:
            raise conflict_error(14, "stale managed-service writer", expected_epoch=expected_epoch,
                                 actual_epoch=record.owner_epoch)

    def release_lease(self, lease_id: str, *, expected_epoch: str) -> ManagedServiceRecord:
        return self._finish_lease(lease_id, expected_epoch=expected_epoch, target="released")

    def revoke_active_leases(self, *, expected_epoch: str) -> ManagedServiceRecord:
        """Release every active lease during an explicitly forced shutdown.

        A normal stop never calls this method.  It exists so a force-stop can
        converge the durable owner record instead of leaving it permanently
        draining behind leases whose clients cannot contact the stopped host.
        """
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            timestamp = self._clock()
            normalized, normalized_changed = normalize_lease_history(
                record.leases, current_time=timestamp
            )
            changed = False
            leases: list[ClientLease] = []
            for lease in normalized:
                if lease.active:
                    lease = replace(lease, state="released")
                    changed = True
                leases.append(lease)
            retained, _ = normalize_lease_history(tuple(leases), current_time=timestamp)
            if not changed and not normalized_changed:
                return record
            return self._write_unlocked(
                replace(record, revision=record.revision + 1, updated_at=timestamp, leases=retained),
                "lease.revoked-forced-stop",
            )

    def _finish_lease(self, lease_id: str, *, expected_epoch: str, target: LeaseState) -> ManagedServiceRecord:
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            timestamp = self._clock()
            normalized, normalized_changed = normalize_lease_history(
                record.leases, current_time=timestamp
            )
            found = False
            changed = False
            leases: list[ClientLease] = []
            for lease in normalized:
                if lease.lease_id == lease_id:
                    found = True
                    if lease.active:
                        lease = replace(lease, state=target)
                        changed = True
                leases.append(lease)
            if not found:
                raise validation_error(20, "managed-service lease not found", lease_id=lease_id)
            retained, _ = normalize_lease_history(
                tuple(leases), current_time=timestamp
            )
            if not changed and not normalized_changed:
                return record
            return self._write_unlocked(replace(record, revision=record.revision + 1,
                                                updated_at=timestamp, leases=retained), f"lease.{target}")

    def expire_leases(self, *, expected_epoch: str) -> ManagedServiceRecord:
        with self._lock():
            record = self._read_unlocked()
            self._check_epoch(record, expected_epoch)
            timestamp = self._clock()
            leases, changed = normalize_lease_history(record.leases, current_time=timestamp)
            if not changed:
                return record
            return self._write_unlocked(replace(record, revision=record.revision + 1,
                                                updated_at=timestamp, leases=leases), "lease.expired")

    def status(self) -> dict[str, Any]:
        record = self.read()
        return {
            "service-kind": record.key.service_kind, "service-id": record.key.service_id,
            "scope": record.key.scope, "state": record.state, "revision": record.revision,
            "owner-epoch": record.owner_epoch, "protocol-version": record.protocol_version,
            "active-lease-count": record.active_lease_count, "updated-at": record.updated_at,
        }


__all__ = [
    "ClientLease", "EndpointInfo", "ManagedServiceRecord", "ManagedServiceStore",
    "ProcessEvidence", "ServiceKey", "ServiceState",
]
